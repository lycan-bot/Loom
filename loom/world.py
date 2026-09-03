"""loom.world — the symbolic-object layer: the world's concrete state as TRACKED facts, not drifting prose.

Canon (the *.md bible) holds what things ARE; threads hold the open questions; reputation holds standing.
What was MISSING is the world's mutable concrete STATE — a door locked, a key in someone's hand, a ledger
burned — which the narrator otherwise tracks only in prose, and prose drifts (the classic continuity break:
a gate said locked three turns ago is open now with no reason). world.py holds that state as structured,
diffable, queryable FACTS.

A fact is (subject, attribute, value): ("the north gate", "state", "locked") · ("the sealed key",
"holder", "Wren") · ("the ledger", "condition", "burned"). It is uniquely keyed by (subject, attribute):
a new value SUPERSEDES the old — logged old->new via provenance, never clobbered blind. The current fact
SET is bounded (objects x their tracked attributes); the change LOG is append-only (provenance, undo-truncated).

The diode, same as canon: the narrator READS world facts as grounding but never WRITES them. Every change
flows through the consolidation diode (the archivist proposes from the play log, the operator blesses) or an
explicit operator edit — never from the narrator's own re-read of its own prose (write->re-read = collapse).
The store lives under `_world` in state.json, so it rides the atomic save + undo. Loom's low-stakes prototype
of the being's world_model: a structured, verified-only, updatable model of reality that grounds behaviour.
"""
from __future__ import annotations
import re
from . import state, provenance

_KEY = "_world"                    # the slot in state.json (an internal _-key, like _rep / _pending_canon)
_MAX_FACTS = 200                   # the SET is bounded (objects x attributes) — a runaway proposal can't grow it forever

# a small conventional vocabulary the archivist is steered toward (free-form attributes still allowed); how a
# fact reads back in prose depends on its attribute
_PHRASING = {
    "state": "{subj} is {val}",
    "condition": "{subj} is {val}",
    "status": "{subj} is {val}",
    "location": "{subj} is at {val}",
    "holder": "{subj} is held by {val}",
    "owner": "{subj} belongs to {val}",
    "contains": "{subj} contains {val}",
}


def _norm(s) -> str:
    """Normalize a subject/attribute for keying — strip a leading 'the', lowercase, drop punctuation."""
    s = re.sub(r"^\s*the\s+", "", str(s or "").strip().lower())
    return re.sub(r"[^a-z0-9 ]+", "", s).strip()


def key(subject, attribute) -> str:
    """The unique id of a fact slot — normalized (subject, attribute). A new value at the same key supersedes."""
    return _norm(subject) + "\x1f" + _norm(attribute)


def keyable(subject, attribute) -> bool:
    """True only when BOTH fields survive normalization to something non-empty. A punctuation-only or
    'the'-only field norms to '' and would collide with every other such field on the one empty-key slot
    (clobbering distinct facts + logging a false reversal), so such a fact is not storable. The gate for
    _clean / upsert / consolidation / the operator POST, so no unkeyable fact ever enters the store."""
    return bool(_norm(subject)) and bool(_norm(attribute))


def _clean(f):
    """A well-formed fact dict, or None — subject/attribute/value must all be non-empty strings."""
    if not isinstance(f, dict):
        return None
    subj = str(f.get("subject", "")).strip()
    attr = str(f.get("attribute", "")).strip()
    val = str(f.get("value", "")).strip()
    if not subj or not attr or not val or not keyable(subj, attr):
        return None                                    # empty, or a subject/attribute that norms to '' (collides)
    out = {"subject": subj, "attribute": attr, "value": val}
    if f.get("hidden"):                                # director-known: characters do NOT know it — kept OUT of the
        out["hidden"] = True                           # character-facing read (clause_visible); omitted when false
    if f.get("since") is not None:
        try:
            out["since"] = int(f["since"])
        except (TypeError, ValueError):
            pass
    out["source"] = str(f.get("source", "")).strip() or "play"
    return out


def load(spath) -> list:
    """The current world facts (well-formed only), from _world in state.json. Pure read."""
    raw = state.load(spath).get(_KEY)
    if not isinstance(raw, list):
        return []
    return [c for c in (_clean(f) for f in raw) if c]


def get(facts, subject, attribute=None):
    """Query a loaded fact list: all facts about a subject (attribute=None), else the single
    (subject, attribute) value or None. Takes the loaded list so a caller avoids a re-read."""
    ks = _norm(subject)
    hits = [f for f in facts if _norm(f["subject"]) == ks]
    if attribute is None:
        return hits
    ka = _norm(attribute)
    return next((f["value"] for f in hits if _norm(f["attribute"]) == ka), None)


def describe(fact) -> str:
    """A fact rendered as a short clause — attribute-aware ('the north gate is locked', 'the sealed key is
    held by Wren'); a generic 'subject — attribute: value' for an attribute outside the small vocabulary."""
    tmpl = _PHRASING.get(_norm(fact["attribute"]))
    if tmpl:
        return tmpl.format(subj=fact["subject"], val=fact["value"])
    return f"{fact['subject']} — {fact['attribute']}: {fact['value']}"


def upsert(facts, subject, attribute, value, since=None, source="play", hidden=False):
    """PURE supersede on an in-memory fact list — the single owner of keying/supersession, so both
    set_fact (its own save) and the batched consolidate.apply (one save) share it. Returns
    (new_facts, {applied, old, new, reversal}); `applied` is False for a no-op (unchanged) or an empty
    field, in which case new_facts is the (cleaned) input. Does NO I/O and logs NOTHING — the caller
    persists new_facts and, if applied and old is not None, logs the old->new to provenance."""
    subject, attribute, value = str(subject).strip(), str(attribute).strip(), str(value).strip()
    clean = [c for c in (_clean(f) for f in (facts or [])) if c]
    if not subject or not attribute or not value or not keyable(subject, attribute):
        return clean, {"applied": False, "old": None, "new": value, "reversal": False}   # empty or unkeyable
    k = key(subject, attribute)
    old, kept = None, []
    for f in clean:
        if key(f["subject"], f["attribute"]) == k:
            old = f["value"]                                # the superseded value (last one wins if dupes)
        else:
            kept.append(f)
    if old is not None and old == value:
        return clean, {"applied": False, "old": old, "new": value, "reversal": False}   # no-op: unchanged
    rev = bool(old is not None and provenance.is_reversal("world", old, value))
    fact = {"subject": subject, "attribute": attribute, "value": value, "source": source or "play"}
    if hidden:                                             # ride the DATA (the signal), not the caller — a hidden
        fact["hidden"] = True                              # fact is redacted at the source read (clause_visible)
    if since is not None:
        try:
            fact["since"] = int(since)
        except (TypeError, ValueError):
            pass
    kept.append(fact)
    if len(kept) > _MAX_FACTS:                              # bound the SET — a runaway proposal can't grow it forever
        kept = kept[-_MAX_FACTS:]
    return kept, {"applied": True, "old": old, "new": value, "reversal": rev}


def set_fact(spath, subject, attribute, value, since=None, source="play", hidden=False) -> dict:
    """Set/supersede one world fact in state.json's _world, keyed by (subject, attribute). If the value
    CHANGED, log the old->new via provenance (never a blind clobber). Returns {applied, old, new,
    reversal}. The single-writer entry point for a standalone edit (an operator set, a test)."""
    st = state.load(spath)
    kept, delta = upsert(st.get(_KEY), subject, attribute, value, since=since, source=source, hidden=hidden)
    if not delta["applied"]:
        return delta
    st[_KEY] = kept
    state.save(spath, st)
    if delta["old"] is not None:                            # a CHANGE (not a first assertion) → audit old->new
        provenance.log(spath, [{"kind": "world", "name": str(subject).strip(), "field": str(attribute).strip(),
                                "old": delta["old"], "new": delta["new"], "entry_start": since, "entry_end": since,
                                "source": source or "play", "reversal": delta["reversal"]}])
    return delta


def remove(spath, subject, attribute) -> bool:
    """Retract a fact (an operator edit — the world moved on, or the fact was wrong). Returns True if one
    was removed; records the retraction in the ledger (old->'(retracted)')."""
    st = state.load(spath)
    raw = st.get(_KEY)
    if not isinstance(raw, list):
        return False
    k = key(subject, attribute)
    kept, removed = [], None
    for f in raw:
        c = _clean(f)
        if c and key(c["subject"], c["attribute"]) == k:
            removed = c
        else:
            kept.append(f)
    if removed is None:
        return False
    st[_KEY] = kept
    state.save(spath, st)
    # the retraction marker must DIFFER from the old value, else provenance.log no-ops it (old==new) and the
    # retraction goes unrecorded — a fact literally valued "(retracted)" would otherwise vanish silently
    marker = "(retracted)" if removed["value"].strip().lower() != "(retracted)" else "(retracted by operator)"
    provenance.log(spath, [{"kind": "world", "name": removed["subject"], "field": removed["attribute"],
                            "old": removed["value"], "new": marker, "source": "operator", "reversal": False}])
    return True


def by_subject(facts) -> list:
    """The facts grouped for display — [{subject, facts:[...]}] in stable first-seen order. Pure."""
    order, groups = [], {}
    for f in facts:
        s = f["subject"]
        if s not in groups:
            groups[s] = []
            order.append(s)
        groups[s].append(f)
    return [{"subject": s, "facts": groups[s]} for s in order]


def clause(facts, subjects=None, cap=40) -> str:
    """The grounding read-view — current concrete world state as one line per fact ('- the north gate is
    locked'), so the narrator can't contradict a tracked fact. `subjects` (an iterable of names) filters to
    things in the scene; None = all. '' when there is nothing to state. The CALLER fences it as story data."""
    rows = facts
    if subjects is not None:
        keep = {_norm(s) for s in subjects}
        rows = [f for f in facts if _norm(f["subject"]) in keep]
    if not rows:
        return ""
    return "\n".join(f"- {describe(f)}" for f in rows[:cap])


def clause_visible(facts, subjects=None, cap=40) -> str:
    """The CHARACTER-facing grounding read — excludes HIDDEN facts before describe(), so the narrator's
    grounding view can never STATE a fact the director alone knows. narrate._world_clause (the one in-fiction
    reader) uses this; every other reader is operator-facing (the director console) and keeps full visibility."""
    return clause([f for f in facts if not f.get("hidden")], subjects=subjects, cap=cap)


def clause_hidden(facts, subjects=None, cap=40) -> str:
    """The DIRECTOR-side read — ONLY hidden facts, for the foreshadow clause (Brick D). The narrator may
    FORESHADOW these (an omen, an unease) but never STATE them until a blessed reveal clears the flag."""
    return clause([f for f in facts if f.get("hidden")], subjects=subjects, cap=cap)
