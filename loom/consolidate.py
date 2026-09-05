"""loom.consolidate — the diode: the ONLY path from transcript → canon.

Between sessions, the model reads the raw play log and PROPOSES canon/state
updates. Nothing is written until the operator blesses it. This is what keeps the
narrator grounded in curated truth instead of drifting on its own improv (the
write→re-read collapse the Sigilus floor exists to prevent, in miniature).
"""
from __future__ import annotations
import difflib
import hashlib
import json
import re
from pathlib import Path
from . import llm, canon, state, threads, reputation, transcript, inbox, episodic, provenance
from . import world as world_layer    # aliased: `world` is the canon-dir Path param in apply()/etc.
from . import npc_standing

_JSON_RE = re.compile(r"\{[\s\S]*\}")

# generic words that must NOT anchor a fuzzy merge (many colleges, many orders) — a match needs a
# DISTINCTIVE shared token (a proper-noun-ish word), so "The Silent Order" won't fold into "The Orders"
_GENERIC = {"the", "a", "an", "of", "college", "order", "orders", "guild", "hall", "tower", "house",
            "school", "academy", "city", "town", "statutes", "council", "company", "band", "keep"}


def _norm(s) -> str:
    s = re.sub(r"^\s*the\s+", "", str(s).strip().lower())
    return re.sub(r"[^a-z0-9 ]+", "", s).strip()


def _resolve_existing(world, name: str):
    """The existing canon node a proposed name refers to — exact, or a CONFIDENT near-miss the
    archivist invented ('The Inquisitor' → 'Inquisitor Vael') — else None (a genuinely new entity).
    Conservative: when unsure it returns None (create a new node), never a wrong merge, so new
    content is never silently swallowed into the wrong node."""
    exact = canon.read_node(world, name)
    if exact is not None:
        return exact["name"]
    n = _norm(name)
    if not n:
        return None
    fuzzy = None
    for node in canon.load_all(world):
        ex = node["name"]
        e = _norm(ex)
        if not e:
            continue
        if n == e:
            return ex                                        # identical after stripping the/punct/case
        nt, et = set(n.split()), set(e.split())
        sig = {w for w in (nt & et) if len(w) > 3 and w not in _GENERIC}
        if sig and (nt <= et or et <= nt):                   # one name's tokens ⊆ the other, sharing a
            return ex                                        # distinctive word → the same entity
        if difflib.SequenceMatcher(None, n, e).ratio() >= 0.9:
            fuzzy = ex                                        # very close spelling (typo/variant)
    return fuzzy


_REP_APPLIED_CAP = 100                          # remember the last N folded deed-ids (re-folds only touch recent windows)


def _deed_id(who, window) -> str:
    """A stable idempotency key for a reputation deed: the entity + the transcript window it was read
    from. Keyed on IMMUTABLE inputs only (no timestamp, no re-worded `because`) so re-proposing the
    SAME window (after an undo/crash/manual re-run) mints the SAME id and the additive apply_delta is
    no-op'd — the double-apply the panel red-team proved every coordination-only fix left reachable."""
    start, end = window
    raw = f"{_norm(who)}|{int(start)}|{int(end)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def window_fingerprint(lines) -> str:
    """A content hash of a transcript window — (role, text) of each entry. Lets a parked fold job be
    matched to the EXACT turns it was proposed from: a length check alone can't tell an undone-then-
    REGROWN window (same length, different play) from the original, so without this a stale fold would
    apply over different transcript entries and the watermark would skip the real new turns."""
    h = hashlib.sha1()
    for e in lines or []:
        if isinstance(e, dict):
            h.update((str(e.get("role", "")) + "\x1f" + str(e.get("text", "")) + "\x1e").encode("utf-8"))
    return h.hexdigest()[:16]


def _looks_like_place_name(loc: str) -> bool:
    """A place NAME is short and name-like ('The Salt & Anchor'); a corrupted location is a prose
    CLAUSE ('The library of Aldermere College, where she continues to study ancient texts with
    Fáelán.'). Reject the clause without a canon lookup — length, word count, sentence markers."""
    low = loc.lower()
    return (len(loc) <= 40 and len(loc.split()) <= 6
            and not loc.rstrip().endswith((".", "!", "?"))
            and not any(m in low for m in (",", " where ", " which ", " who ", " that ", " with ", " to ")))


def _resolve_place(world, loc: str):
    """A proposed NPC location, cleaned to a place: the canonical name of the place node it refers to,
    a plausible NEW place name not yet in canon, or None. Consolidation must NEVER write free-text
    into a `location` field — a bad archivist reply once wrote a whole narrative clause there, which
    broke co-location routing and made the world round narrate the player as an off-scene NPC.
      • resolves to an existing PLACE node → that node's name (normalizes the clause down to it)
      • resolves to a NON-place node (a character, e.g. 'same as Wren') → None (a person isn't a place)
      • no node match but looks like a place NAME → keep it (NPCs move to not-yet-noded places)
      • otherwise (a prose clause) → None"""
    loc = (loc or "").strip()
    if not loc or world is None:
        return None
    resolved = _resolve_existing(world, loc)
    if resolved:
        node = canon.read_node(world, resolved)
        return resolved if node and node["frontmatter"].get("kind") == "place" else None
    return loc if _looks_like_place_name(loc) else None


def _dicts(x):
    """Model output is grammar-valid JSON but NOT shape-checked; keep only the dict elements
    of a list so a botched container type is skipped, never crashed on."""
    return [e for e in x if isinstance(e, dict)] if isinstance(x, list) else []


def _s(x, default=""):
    """A model scalar coerced to a clean string — a non-str field becomes the default, never a
    crash (`.strip()` / slug on a list or number is the whole class of bug this closes)."""
    return x if isinstance(x, str) else default


_PLACEHOLDER_KEYS = {"key", "value", "fact", "fact name", "fact_name", "factname"}


def _real_key(k) -> bool:
    """Reject the schema's example placeholder echoed back verbatim as a literal fact — a wild model
    copies '{"key": "value"}' or a '<...>' template straight into its output. A real fact key is a
    concrete name, never the template, so those are dropped before they pollute state."""
    s = str(k).strip().lower()
    return bool(s) and s not in _PLACEHOLDER_KEYS and "<" not in s and ">" not in s


def _no_template(s) -> bool:
    """True unless the string is a schema-template echo ('<...>'). Unlike _real_key it does NOT blocklist
    'key'/'value'/'fact' — for a WORLD fact those are legitimate object names ('the key'), not placeholders."""
    s = str(s)
    return "<" not in s and ">" not in s


def _normalize(proposals: dict) -> dict:
    """Coerce grammar-valid-but-unshaped model output into clean, typed structures so the write
    loop can never crash on a bad type or leave a partial commit. Every malformed field is
    dropped here, up front — nothing downstream ever sees a non-string where a string is due."""
    def _named(d):
        n = d.get("name")
        return n if isinstance(n, str) and n.strip() else None

    nodes = []
    for n in _dicts(proposals.get("nodes")):
        name = _named(n)
        if not name:
            continue
        rf = n.get("fields")
        fields = {k: v for k, v in rf.items() if isinstance(v, str) and v} if isinstance(rf, dict) else {}
        nodes.append({"name": name, "body": _s(n.get("body")).strip(),
                      "kind": _s(n.get("kind"), "lore"), "fields": fields})

    threads_new = []
    for t in _dicts(proposals.get("threads_new")):
        q = _s(t.get("question")).strip()
        if not q:
            continue
        re_ = t.get("entities")
        ents = ([e for e in re_ if isinstance(e, str)] if isinstance(re_, list)
                else [re_] if isinstance(re_, str) and re_ else [])
        threads_new.append({"question": q, "entities": ents,
                            "seed": _s(t.get("seed")), "payoff": _s(t.get("payoff"))})

    updates = []
    for c in _dicts(proposals.get("character_updates")):
        name = _named(c)
        disp, loc = _s(c.get("disposition")).strip(), _s(c.get("location")).strip()
        if name and (disp or loc):
            updates.append({"name": name, "disposition": disp, "location": loc})

    rep = []
    for r in _dicts(proposals.get("reputation")):
        who = _s(r.get("who")).strip()
        if not who:
            continue
        try:
            delta = int(r.get("delta"))
        except (TypeError, ValueError):
            continue
        if delta == 0:                                    # a no-op delta isn't a reputation change
            continue
        rep.append({"who": who, "delta": max(-3, min(3, delta)), "because": _s(r.get("because")).strip()})

    events = []
    for ev in _dicts(proposals.get("events")):
        what = _s(ev.get("what")).strip()
        if what:
            who_raw = ev.get("who")                        # who ACTED in this beat — makes a played beat
            cand = ([w for w in who_raw if isinstance(w, str) and w.strip()]  # addressable per-agent so an NPC
                    if isinstance(who_raw, list) else                         # (or the player) recalls its OWN deeds
                    ([who_raw.strip()] if isinstance(who_raw, str) and who_raw.strip() else []))
            # the archivist's `who` is MODEL-PROPOSED, over a player-authored log — validate each actor
            # against the beat text so a poisoned/hallucinated who can't plant a false deed or shared
            # history in BLESSED memory (a name not in the beat is dropped; the honest ones pass).
            low_what = provenance._norm(what)
            who = [w for w in cand
                   if provenance._norm(w) and re.search(r"\b" + re.escape(provenance._norm(w)) + r"\b", low_what)]
            events.append({"what": what, "when": _s(ev.get("when")).strip(), "who": who})

    world_facts = []
    for wf in _dicts(proposals.get("world")):
        subj = _s(wf.get("subject")).strip()
        attr = _s(wf.get("attribute")).strip()
        val = _s(wf.get("value")).strip()
        # a real fact needs all three; drop a schema-template echo ('<...>') — but NOT a real object named
        # 'key'/'value' — and drop an unkeyable subject/attribute (norms to '' → would collide on one slot)
        if (subj and attr and val and _no_template(subj) and _no_template(attr) and _no_template(val)
                and world_layer.keyable(subj, attr)):
            world_facts.append({"subject": subj, "attribute": attr, "value": val})

    npc_std = []
    for s in _dicts(proposals.get("npc_standing")):
        a, b = _s(s.get("a")).strip(), _s(s.get("b")).strip()
        try:
            delta = int(s.get("delta"))
        except (TypeError, ValueError):
            continue
        # a real inter-NPC delta needs two DISTINCT keyable people and a non-zero shift (pair_key rejects
        # same/empty), and neither name a template echo
        if delta != 0 and _no_template(a) and _no_template(b) and npc_standing.pair_key(a, b) is not None:
            npc_std.append({"a": a, "b": b, "delta": max(-3, min(3, delta)), "because": _s(s.get("because")).strip()})

    resolved_raw = proposals.get("threads_resolved")
    return {
        "nodes": nodes,
        "state": {str(k): v for k, v in proposals["state"].items() if _real_key(k)} if isinstance(proposals.get("state"), dict) else {},
        "threads_new": threads_new,
        "threads_resolved": [r for r in resolved_raw if isinstance(r, str)] if isinstance(resolved_raw, list) else [],
        "character_updates": updates,
        "reputation": rep,
        "events": events,
        "world": world_facts,
        "npc_standing": npc_std,
    }


def _loads_lenient(text: str):
    """json.loads, but if the object was truncated (e.g. hit max_tokens), repair it by
    closing any open string and balancing braces/brackets. The grammar guarantees valid
    JSON *syntax*; this guards against a valid-but-cut-off object."""
    try:
        return json.loads(text)
    except Exception:
        pass
    stack, in_str, esc = [], False, False
    closer = {"{": "}", "[": "]"}
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in closer:
            stack.append(closer[ch])
        elif ch in ("}", "]") and stack and stack[-1] == ch:
            stack.pop()
    repaired = text + ('"' if in_str else "") + "".join(reversed(stack))
    return json.loads(repaired)

_PROMPT = """You are the archivist of an ongoing story. Read the play log and propose durable \
updates to the world. Extract only what is now ESTABLISHED; do not invent beyond the log.

Also tend the STORY THREADS — the open dramatic questions and pending tensions that give the \
story momentum. Currently open threads:
%s

EXISTING CANON NODES — when an update concerns one of these, use its EXACT name below so it MERGES \
into that node instead of forking a near-duplicate. Only invent a NEW name for a genuinely new entity:
%s

Respond with ONE json object:
{
  "nodes":   [{"name": "...", "body": "markdown, may use [[links]]", "kind": "character|place|faction|event|lore", "fields": {"role": "(character only) who/what they are, short", "met": "(character only) when + where they were first met"}}],
  "state":   {"<a short snake_case fact name>": "<what is now true>"},
  "threads_new":      [{"question": "a NEW open dramatic question this session RAISED", "entities": ["canon names it involves"], "seed": "a subtle detail to foreshadow it later", "payoff": "what answering it might look like"}],
  "threads_resolved": ["<id of an open thread the session ANSWERED, if any>"],
  "character_updates": [{"name": "an existing character", "disposition": "how they now feel toward the player, ONLY if it clearly shifted this session", "location": "the place they are now, ONLY if they moved this session"}],
  "reputation": [{"who": "a faction, group, or notable person", "delta": -1, "because": "the DEED this session that moved their regard for the player (a small integer -3..3; negative = worse)"}],
  "events":  [{"what": "a concrete thing that HAPPENED this session — a beat worth remembering later, in past tense", "when": "(optional) the in-fiction time it happened ('the next morning', 'that night', 'days later') — ONLY if the prose states it", "who": ["the character name(s) who ACTED in this beat — the player and/or the NPCs involved, EXACTLY as named in canon"]}][[WORLD_LINE]][[NPC_LINE]],
  "summary": "one sentence on what changed"
}
Only open a thread for a genuine NEW dramatic question the session actually raised; only resolve \
one it truly closed. In `events`, list what actually happened (grounded in the log, not invented); \
give `when` only if the prose says so.[[WORLD_GUIDE]][[NPC_GUIDE]] If a section has nothing, use an empty list.

PLAY LOG:
%s
"""


# the server enforces json_schema as a token-level grammar (unlike json_object, a soft hint a wild RP
# model ignores) — so consolidation gets valid JSON from ANY model. Permissive by design: no `required`
# (the model omits empty sections), open `state`/`fields` maps, so the grammar shapes without starving.
_SCHEMA = {
    "type": "object",
    "properties": {
        "nodes": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "body": {"type": "string"},
            "kind": {"type": "string"}, "fields": {"type": "object"}}}},
        "state": {"type": "object"},
        "threads_new": {"type": "array", "items": {"type": "object", "properties": {
            "question": {"type": "string"}, "entities": {"type": "array", "items": {"type": "string"}},
            "seed": {"type": "string"}, "payoff": {"type": "string"}}}},
        "threads_resolved": {"type": "array", "items": {"type": "string"}},
        "character_updates": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "disposition": {"type": "string"}, "location": {"type": "string"}}}},
        "reputation": {"type": "array", "items": {"type": "object", "properties": {
            "who": {"type": "string"}, "delta": {"type": "integer"}, "because": {"type": "string"}}}},
        "events": {"type": "array", "items": {"type": "object", "properties": {
            "what": {"type": "string"}, "when": {"type": "string"},
            "who": {"type": "array", "items": {"type": "string"}}}}},
        "summary": {"type": "string"},
    },
}

# the symbolic-object layer's proposal shape — added to the prompt + schema ONLY when the world_state
# toggle is on (else consolidation is byte-identical to before: no world section, no _world ever written)
_WORLD_LINE = (',\n  "world":   [{"subject": "a concrete THING or place whose state CHANGED this session '
               '(an object, a door, an item)", "attribute": "state|condition|location|holder|owner|contains", '
               '"value": "what is now TRUE of it (e.g. \'locked\', \'burned\', \'Wren\', \'the vault\')"}]')
_WORLD_GUIDE = (" In `world`, record only a concrete OBJECT/place state that CHANGED and is now settled truth "
                "(a locked door, a burned letter, who holds an item) — not a feeling, not an event, only the "
                "durable current state of a thing.")
_WORLD_SCHEMA_PROP = {"type": "array", "items": {"type": "object", "properties": {
    "subject": {"type": "string"}, "attribute": {"type": "string"}, "value": {"type": "string"}}}}

# NPC↔NPC standing — added to the prompt + grammar ONLY when the npc_standing toggle is on (else the
# archivist prompt/schema are byte-identical and _npc_standing is never written)
_NPC_LINE = (',\n  "npc_standing": [{"a": "one character", "b": "another character", "delta": 1, '
             '"because": "the thing BETWEEN them this session that moved how they regard EACH OTHER (a small '
             'integer -3..3; negative = worse) — allies who cooperated, rivals who clashed"}]')
_NPC_GUIDE = (" In `npc_standing`, record only how two NAMED characters now regard EACH OTHER after something "
              "between THEM this session — not their feelings toward the player (that is `character_updates`/"
              "`reputation`), and only if it clearly shifted.")
_NPC_SCHEMA_PROP = {"type": "array", "items": {"type": "object", "properties": {
    "a": {"type": "string"}, "b": {"type": "string"}, "delta": {"type": "integer"}, "because": {"type": "string"}}}}


def propose(cfg: dict, session_lines: list[dict], existing_threads=None, world=None) -> dict:
    """Ask the model for proposed canon/state/thread changes. Returns a dict; writes nothing.

    `existing_threads` (Thread objects) are shown to the archivist so it can avoid opening
    duplicates and can name a thread it has answered. Uses the optional archivist endpoint
    (consolidate_llm_url / consolidate_model) — consolidation wants reliable JSON, which a
    wild uncensored narrator may botch.
    """
    ccfg = dict(cfg)
    if cfg.get("consolidate_llm_url"):
        ccfg["llm_url"] = cfg["consolidate_llm_url"]
    if cfg.get("consolidate_model"):
        ccfg["llm_model"] = cfg["consolidate_model"]
    if cfg.get("consolidate_api_key"):
        ccfg["api_key"] = cfg["consolidate_api_key"]
    open_str = "\n".join(f"- [{t.id}] {t.question}" for t in (existing_threads or [])
                         if getattr(t, "status", "") != "resolved"
                         and not getattr(t, "hidden", False)) or "(none yet)"   # hidden = director-only, never shown
    roster_str = ("\n".join(f"- {n['name']} ({n['frontmatter'].get('kind', 'lore')})"
                            for n in canon.load_all(world)) or "(none yet)") if world is not None else "(none yet)"
    log_text = "\n".join(f"{e.get('role', '?')}: {e.get('text', '')}" for e in session_lines)
    # the world (symbolic-object) section is added to the prompt + grammar ONLY when world_state is on, so
    # a game with the layer off gets the byte-identical archivist prompt + schema — and never writes _world.
    world_on, npc_on = bool(cfg.get("world_state")), bool(cfg.get("npc_standing"))
    prompt = (_PROMPT.replace("[[WORLD_LINE]]", _WORLD_LINE if world_on else "")
                     .replace("[[WORLD_GUIDE]]", _WORLD_GUIDE if world_on else "")
                     .replace("[[NPC_LINE]]", _NPC_LINE if npc_on else "")
                     .replace("[[NPC_GUIDE]]", _NPC_GUIDE if npc_on else ""))
    props = dict(_SCHEMA["properties"])
    if world_on:
        props["world"] = _WORLD_SCHEMA_PROP
    if npc_on:
        props["npc_standing"] = _NPC_SCHEMA_PROP
    schema = {**_SCHEMA, "properties": props} if (world_on or npc_on) else _SCHEMA
    raw = llm.complete(prompt % (open_str, roster_str, log_text), ccfg, max_tokens=1400, temperature=0.2,
                       response_format={"type": "json_schema",             # token-level grammar (enforced)
                                        "json_schema": {"name": "consolidation", "schema": schema}})
    m = _JSON_RE.search(raw)
    if not m:
        raise ValueError(f"no JSON object in consolidation output: {raw[:200]}")
    data = _loads_lenient(m.group(0))
    for key, default in (("nodes", []), ("state", {}), ("threads_new", []), ("threads_resolved", []),
                         ("character_updates", []), ("reputation", []), ("events", []), ("world", []),
                         ("npc_standing", []), ("summary", "")):
        data.setdefault(key, default)
    return data


def apply(proposals: dict, world: Path, state_path: Path, approve,
          deed_window=None, watermark=None, hold_reversals=False, world_state=False, npc_standing_on=False) -> dict:
    """Write approved proposals to canon + state. `approve(kind, name, payload) -> bool` is
    called for EVERY change; nothing is written unless it returns True — the diode, the operator's
    hand between improv and canon.

    Model output is grammar-valid JSON but NOT shape-checked, so it is normalized to clean typed
    structures first (`_normalize`): a mistyped field is dropped, never crashed on mid-write, so a
    garbled reply can't leave half-written canon (propose→bless atomicity).

    `deed_window=(start, end)` keys each reputation deed by the transcript window it came from, so a
    re-fold of the same window can't double-apply the additive standing (idempotency; see `_deed_id`).
    `watermark` (an int), when given, advances `_consolidated` in the SAME state save as `_rep` —
    collapsing the old split-commit (apply saves `_rep`, mark_consolidated separately saves the
    watermark) whose crash window re-armed the double-apply. None on both = legacy behaviour.
    """
    p = _normalize(proposals)
    written: dict[str, list] = {"nodes": [], "state": [], "threads": [], "resolved": [],
                                "dispositions": [], "locations": [], "reputation": [], "events": [],
                                "world": [], "npc_standing": [], "held_reversals": []}
    held_revs = []               # functional-field FLIPS the auto-drain proposed w/o operator authority → hold
    for node in p["nodes"]:
        name, body, fields = node["name"], node["body"], node["fields"]
        if not approve("node", name, node):
            continue
        resolved = _resolve_existing(world, name)                # a near-miss the archivist invented
        existing = canon.read_node(world, resolved) if resolved else None
        if existing is None:                                      # genuinely new → create it
            canon.write_node(world, name, body, {"kind": node["kind"], **fields})
            written["nodes"].append(name)
            continue
        name = existing["name"]                                   # merge under the CANONICAL name, not the dup
        fm = dict(existing["frontmatter"])                        # preserve drives, voice, etc.
        new_body, touched = existing["body"], False
        if body and body not in existing["body"]:                 # append novel content
            new_body = existing["body"].rstrip() + "\n\n" + body
            touched = True
        changes = []
        for k, v in fields.items():                               # merge card fields
            if fm.get(k) != v:
                old = str(fm.get(k, "")).strip()
                if old and str(v).strip():                        # a SET field changed → reconcile, don't clobber blind
                    changes.append({"kind": "character", "name": name, "field": k, "old": old, "new": v,
                                    "source": "consolidate", "reversal": provenance.is_reversal(k, old, v)})
                fm[k] = v
                touched = True
        if changes:                                               # log-FIRST (like the other branches): an
            ts, te = (deed_window if deed_window else (None, None))   # audit row can outlive a crashed write,
            for c in changes:                                     # but a write must never outlive its record
                c["entry_start"], c["entry_end"] = ts, te
            provenance.log(state_path, changes)
        if touched:
            canon.write_node(world, name, new_body, fm)
            written["nodes"].append(name)
    st = state.load(state_path)
    ts, te = (deed_window if deed_window else (None, None))   # the turn-window, for provenance + events
    changed = False
    for key, val in p["state"].items():
        if approve("state", key, val):
            old = st.get(key)
            if old is not None and str(old) != str(val):     # a fact CHANGED — record old→new, never clobber blind
                provenance.log(state_path, [{"kind": "state", "name": key, "field": key, "old": old, "new": val,
                                             "entry_start": ts, "entry_end": te, "source": "consolidate",
                                             "reversal": provenance.is_reversal("state", old, val)}])
            st[key] = val
            written["state"].append(key)
            changed = True
    # the symbolic-object layer: settle concrete world state (a door locked, an item's holder) into the
    # structured _world store. Gated per fact by approve("world", ...); a CHANGE is logged old->new via
    # provenance (never a blind clobber) exactly like a state fact. world.upsert is PURE, so this rides the
    # SAME batched state.save below (calling world.set_fact here would clobber that save). A concrete state
    # transition, not a valence flip — it supersedes with an audit row; it is not held like a disposition.
    # The WRITE side is gated too: world_state off => never touch _world, even if a proposal carries a `world`
    # array (a stale fold queued while ON then drained OFF, or a non-compliant model). Byte-identical-off is
    # enforced HERE, not only in propose() — apply() is the universal chokepoint every fold path passes through.
    for wf in (p["world"] if world_state else []):
        subj, attr, val = wf["subject"], wf["attribute"], wf["value"]
        if not approve("world", subj, wf):
            continue
        new_facts, delta = world_layer.upsert(st.get(world_layer._KEY), subj, attr, val, since=ts, source="consolidate")
        if not delta["applied"]:
            continue
        if delta["old"] is not None:                      # a CHANGE (not a first assertion) → audit old->new
            provenance.log(state_path, [{"kind": "world", "name": subj, "field": attr, "old": delta["old"],
                                         "new": delta["new"], "entry_start": ts, "entry_end": te,
                                         "source": "consolidate", "reversal": delta["reversal"]}])
        st[world_layer._KEY] = new_facts
        written["world"].append(subj)
        changed = True
    # NPC↔NPC standing: additive like reputation, so it needs the SAME re-fold idempotency (a re-proposed
    # window must not double-shift a standing) — each deed keyed by (pair, window). Gated on the toggle too,
    # so a stale fold drained while off writes nothing (byte-identical-off, like the world block).
    if npc_standing_on and p["npc_standing"]:
        ns_store = st.get(npc_standing._KEY)
        ns_store = ns_store if isinstance(ns_store, dict) else {}
        prev_ns = [d for d in (st.get("_npc_standing_applied") or []) if isinstance(d, str)]
        seen_ns, new_ns = set(prev_ns), []
        for s in p["npc_standing"]:
            pk = npc_standing.pair_key(s["a"], s["b"])
            did = (hashlib.sha1(f"{pk}|{int(deed_window[0])}|{int(deed_window[1])}".encode("utf-8")).hexdigest()[:16]
                   if pk and deed_window is not None else None)
            if did is not None and did in seen_ns:
                continue                                  # this window's delta for the pair was already folded
            if approve("npc_standing", f"{s['a']} & {s['b']}", s):
                npc_standing.apply_delta(ns_store, s["a"], s["b"], s["delta"], s["because"])
                written["npc_standing"].append(f"{s['a']} & {s['b']}")
                changed = True
                if did is not None:
                    new_ns.append(did)
        st[npc_standing._KEY] = ns_store
        if new_ns:
            st["_npc_standing_applied"] = (prev_ns + new_ns)[-_REP_APPLIED_CAP:]
            changed = True
    # reputation: shift each blessed standing (the diode gates each deed) and log the deed that moved
    # it — stored in the same state under _rep so it commits atomically with the rest of the state.
    # A deed already folded (its window-keyed id is in _rep_applied) is skipped: additive apply_delta
    # must never run twice for the same window, or a re-fold double-counts the standing.
    rep = reputation.load(st)
    prev_applied = [d for d in (st.get("_rep_applied") or []) if isinstance(d, str)]
    seen = set(prev_applied)
    new_ids = []
    for r in p["reputation"]:
        did = _deed_id(r["who"], deed_window) if deed_window is not None else None
        if did is not None and did in seen:
            continue                                  # this window's deed for `who` was already folded
        if approve("reputation", r["who"], r):
            reputation.apply_delta(rep, r["who"], r["delta"], r["because"])
            written["reputation"].append(r["who"])
            changed = True
            if did is not None:
                new_ids.append(did)
    if rep:
        st["_rep"] = rep
    if new_ids:                                       # remember what we folded (bounded — recent windows only)
        st["_rep_applied"] = (prev_applied + new_ids)[-_REP_APPLIED_CAP:]
        changed = True
    if watermark is not None:                         # advance the watermark in the SAME save as _rep (no split).
        # MONOTONIC — never regress: a stale manual apply (its dialog opened BEFORE a later fold advanced
        # the watermark) must not roll it back, or the turns between re-fold under a fresh deed-key and
        # double-apply reputation. max() makes the write safe under an out-of-order/two-tab manual apply.
        st["_consolidated"] = max(int(st.get("_consolidated", 0) or 0), int(watermark))
        changed = True
    if changed:
        state.save(state_path, st)

    # the timeline spine: record the session's events with the real-turn range they came from (deed_window)
    # so "when was that?" resolves on two clocks. A factual log (blessed side of the diode) — always recorded.
    if p["events"]:
        ts, te = (deed_window if deed_window else (None, None))
        n_ev = episodic.record(state_path, p["events"], entry_start=ts, entry_end=te)
        if n_ev:
            written["events"] = [e["what"] for e in p["events"]][:n_ev]

    # story threads: open new dramatic questions, resolve answered ones (the diode gates both)
    thpath = Path(state_path).parent / "threads.json"
    th = threads.load(thpath)
    by_id = {t.id: t for t in th}
    th_changed = False
    for nt in p["threads_new"]:
        q = nt["question"]
        tid = threads.make_id(q)
        if tid in by_id:                                 # dedup against existing
            continue
        if approve("thread", q, nt):
            new = threads.Thread(id=tid, question=q, kind="question", status="dormant",
                                 entities=nt["entities"], seed=nt["seed"], payoff=nt["payoff"])
            th.append(new)
            by_id[tid] = new
            written["threads"].append(q)
            th_changed = True
    for rid in p["threads_resolved"]:
        t = by_id.get(rid)
        # a HIDDEN (director-only) thread must never be resolved by consolidation — only an operator reveal()
        # un-hides it, after which it resolves normally. Else the narrator's own prose could silently end the
        # horizon before the reveal, and it could never fire (mirrors every other consumer of the hidden signal).
        if t and t.status != "resolved" and not getattr(t, "hidden", False) and approve("resolve", rid, t.question):
            t.status = "resolved"
            written["resolved"].append(rid)
            th_changed = True
    if th_changed:
        threads.save(thpath, th)

    # a character's disposition toward the player, updated in place (relationship growth)
    for cu in p["character_updates"]:
        name = cu["name"]
        node = canon.read_node(world, name)
        if node is None or node["frontmatter"].get("kind") != "character":
            continue
        fm = dict(node["frontmatter"])
        touched = False
        # disposition (a feeling) and location (a MOVE) are DISTINCT changes — gate them separately
        # so a relocation is disclosed and independently refusable, not smuggled in under a feeling
        if cu["disposition"] and approve("disposition", name, cu["disposition"]):
            old = str(fm.get("disposition", "")).strip()
            held = False
            if old and old != cu["disposition"]:         # a feeling SHIFTED
                if hold_reversals and provenance.is_reversal("disposition", old, cu["disposition"]):
                    # CONTRADICTION-REPAIR: a valence FLIP (warm↔hostile) proposed by the auto-drain, which
                    # has no operator authority — HOLD it for the operator instead of silently overwriting an
                    # established feeling (a functional relation; a genuine contradiction, not a progression).
                    held_revs.append({"name": name, "field": "disposition", "old": old, "new": cu["disposition"],
                                      "entry_start": ts, "entry_end": te, "source": "consolidate"})
                    written["held_reversals"].append(name)
                    held = True
                else:                                    # a progression (warm→warmer) or an authorised path → log + apply
                    provenance.log(state_path, [{"kind": "character", "name": name, "field": "disposition",
                                                 "old": old, "new": cu["disposition"], "entry_start": ts, "entry_end": te,
                                                 "source": "consolidate",
                                                 "reversal": provenance.is_reversal("disposition", old, cu["disposition"])}])
            if not held:
                fm["disposition"] = cu["disposition"]
                written["dispositions"].append(name)
                touched = True
        # a location MUST resolve to a real place node — never write the archivist's free-text clause
        # (that corruption is what put Wren 'elsewhere with Fáelán' and broke co-location)
        place = _resolve_place(world, cu["location"]) if cu["location"] else None
        if place and approve("location", name, place):
            old = str(fm.get("location", "")).strip()
            if old and old != place:                     # a MOVE from a known place — record the relocation
                provenance.log(state_path, [{"kind": "character", "name": name, "field": "location",
                                             "old": old, "new": place, "entry_start": ts, "entry_end": te,
                                             "source": "consolidate", "reversal": provenance.is_reversal("location", old, place)}])
            fm["location"] = place                       # NPCs relocate over play → world-round groups shift
            written["locations"].append(name)
            touched = True
        if touched:
            canon.write_node(world, name, node["body"], fm)
    if held_revs:                                    # contradiction-repair: park the held flips for the operator
        queue_reversal(state_path, held_revs)
    return written


# --- incremental consolidation: only fold in the turns SINCE the last pass, so the prompt stays
# bounded no matter how long the campaign runs (the fix for the long-session consolidate timeout) ---

def unconsolidated(tpath, spath):
    """(new transcript entries since the last consolidation, current total count). The watermark is
    `_consolidated` in state — how many transcript entries have already been folded in."""
    lines = transcript.read_all(tpath)
    wm = int(state.load(spath).get("_consolidated", 0) or 0)
    return lines[wm:], len(lines)


def mark_consolidated(spath, total: int) -> None:
    """Advance the watermark past everything consolidated so far (blessed or declined — either way
    those turns won't be re-proposed; they still live in the transcript + scene memory)."""
    state.set_fact(spath, "_consolidated", int(total))


def queue_pending(spath, nodes) -> None:
    """Park proposed canon-node updates in `_pending_canon` for the operator to bless later — the
    diode's holding pen. Auto consolidation applies the low-risk structured continuity itself but
    PARKS canon here instead of dropping it (the original bug: advancing the watermark past
    un-blessed nodes lost them forever, since those turns are never re-proposed). Dedup by name,
    latest proposal wins."""
    nodes = [n for n in (nodes or []) if isinstance(n, dict) and n.get("name")]
    if not nodes:
        return
    st = state.load(spath)
    q = st.get("_pending_canon")
    by_name = {n["name"]: n for n in (q if isinstance(q, list) else [])
               if isinstance(n, dict) and n.get("name")}
    for n in nodes:
        by_name[n["name"]] = n
    st["_pending_canon"] = list(by_name.values())
    state.save(spath, st)


def pending(spath):
    """The queued canon-node proposals awaiting the operator's bless (from auto consolidation)."""
    q = state.load(spath).get("_pending_canon")
    return [n for n in q if isinstance(n, dict) and n.get("name")] if isinstance(q, list) else []


def apply_pending(world: Path, spath, approve=None) -> dict:
    """Bless the queued canon into the world-bible, then empty the pen. `approve(kind, name, payload)`
    gates each node (default: bless all); a review pass is final — declined nodes are dropped from the
    queue too, so it never re-nags. Reuses the exact merge/dedup path a manual consolidate takes."""
    pend = pending(spath)
    if not pend:
        return {"nodes": []}
    if approve is None:
        approve = lambda *a: True
    # date the blessed changes by the windows they were parked from — (earliest start, latest end) across
    # the pen, so provenance rows carry a when instead of None (approximate when the pen spans folds)
    wins = [n["_window"] for n in pend if isinstance(n.get("_window"), (list, tuple)) and len(n["_window"]) == 2]
    dw = (min(w[0] for w in wins), max(w[1] for w in wins)) if wins else None
    written = apply({"nodes": pend, "state": {}, "threads_new": [], "threads_resolved": [],
                     "character_updates": [], "reputation": []}, world, spath,
                    lambda kind, name, p: kind == "node" and approve(kind, name, p), deed_window=dw)
    st = state.load(spath)
    st.pop("_pending_canon", None)
    state.save(spath, st)
    return written


def queue_reversal(spath, reversals) -> None:
    """Park held functional-field REVERSALS — contradictions the AUTO-drain proposed without operator
    authority (a disposition FLIP against an established feeling). The diode's holding pen for
    contradictions: the world never silently overwrites an established value on the archivist's say-so;
    the operator blesses or rejects. Dedup by (name, field): the latest proposed flip wins the slot."""
    reversals = [r for r in (reversals or []) if isinstance(r, dict) and r.get("name") and r.get("field")]
    if not reversals:
        return
    st = state.load(spath)
    pen = [r for r in (st.get("_pending_reversal") or []) if isinstance(r, dict) and r.get("name") and r.get("field")]
    for hr in reversals:
        pen = [r for r in pen if not (r.get("name") == hr["name"] and r.get("field") == hr["field"])]
        pen.append(hr)
    # UNCAPPED, like the sibling _pending_canon pen — a held flip advances the watermark past its source
    # turns, so a silently-evicted contradiction is lost forever (never re-proposed, no canon change, no
    # ledger row). Dedup-by-(name,field) already bounds this to one slot per distinct unresolved decision.
    st["_pending_reversal"] = pen
    state.save(spath, st)


def pending_reversals(spath):
    """The held reversals awaiting the operator's decision (from the auto-drain)."""
    q = state.load(spath).get("_pending_reversal")
    return [r for r in q if isinstance(r, dict) and r.get("name") and r.get("field")] if isinstance(q, list) else []


def apply_reversal(world: Path, spath, name, field, approve=None) -> bool:
    """The operator's decision on a held reversal: bless it (apply the flip to canon + log old->new) or,
    if `approve` returns False, reject it — either way it leaves the pen (a decision is final, never
    re-nags). Returns True if the flip was applied. Re-reads the CURRENT canon value so a bless logs the
    real old->new even if canon moved since the hold."""
    approve = approve or (lambda *a: True)
    match = next((r for r in pending_reversals(spath) if r.get("name") == name and r.get("field") == field), None)
    if match is None:
        return False
    applied = False
    if approve("reversal", name, match):
        node = canon.read_node(world, name)
        if node is not None and node["frontmatter"].get("kind") == "character":
            fm = dict(node["frontmatter"])
            old = str(fm.get(field, "")).strip() or str(match.get("old", "")).strip()
            new = str(match.get("new", "")).strip()
            if new and old != new:
                provenance.log(spath, [{"kind": "character", "name": name, "field": field, "old": old, "new": new,
                                        "entry_start": match.get("entry_start"), "entry_end": match.get("entry_end"),
                                        "source": "reversal_bless", "reversal": provenance.is_reversal(field, old, new)}])
                fm[field] = new
                canon.write_node(world, name, node["body"], fm)
                applied = True
    st = state.load(spath)                                # drop it from the pen (blessed OR rejected)
    st["_pending_reversal"] = [r for r in (st.get("_pending_reversal") or [])
                               if not (isinstance(r, dict) and r.get("name") == name and r.get("field") == field)]
    state.save(spath, st)
    return applied


def _fold_proposals(proposals, world, spath, start, end, apply_canon, world_state=False, npc_standing_on=False):
    """Fold ONE window's proposals into the durable stores — the shared body of both the synchronous
    `auto()` and the background-then-drain path. The DIODE: by default only low-risk structured
    continuity (facts, reputation, disposition/location, thread ripening) applies; canon nodes + thread
    RESOLUTION stay gated and PARK in the pen unless apply_canon. The watermark is advanced to `end` in
    the same save as `_rep`, and reputation is keyed on (start, end) so a re-fold can't double-count.
    Returns (written, pending_node_names). ALWAYS runs on the turn thread — never a background one."""
    def approve(kind, name, payload):
        if kind in ("node", "resolve") and not apply_canon:
            return False
        return True

    pending_names = []
    if not apply_canon:
        norm_nodes = _normalize(proposals)["nodes"]
        if norm_nodes:
            for n in norm_nodes:
                n["_window"] = [start, end]           # remember the fold window so a later bless can DATE the
            queue_pending(spath, norm_nodes)          # change (else parked provenance rows carry no when).
            pending_names = [n["name"] for n in norm_nodes]   # PARK FIRST — a crash before the watermark
            #                                                    advance just re-parks (dedup by name)
    # the auto path (apply_canon False) has no operator authority → HOLD a disposition FLIP for the
    # operator instead of auto-overwriting an established feeling (contradiction-repair). apply_canon
    # True = an operator-authorised fold → apply directly.
    written = apply(proposals, world, spath, approve, deed_window=(start, end), watermark=end,
                    hold_reversals=not apply_canon, world_state=world_state, npc_standing_on=npc_standing_on)
    return written, pending_names


def auto(cfg, tpath, world, spath, apply_canon: bool = False):
    """Synchronous consolidation: propose from the NEW turns and fold the result in one call. Kept for
    the manual/test path; the LIVE auto path is background-propose + drain_inbox (single-writer). Now
    routes through `_fold_proposals`, so it gets the idempotent reputation + combined watermark save."""
    new_lines, total = unconsolidated(tpath, spath)
    wm = total - len(new_lines)
    if len([e for e in new_lines if e.get("role") == "player"]) < 1:
        return {"applied": {}, "pending_nodes": [], "summary": "", "new": len(new_lines)}
    existing = threads.load(spath.parent / "threads.json")
    try:
        proposals = propose(cfg, new_lines, existing, world=world)
    except Exception as e:
        return {"error": str(e), "new": len(new_lines)}
    written, pending_names = _fold_proposals(proposals, world, spath, wm, total, apply_canon,
                                             world_state=bool(cfg.get("world_state")),
                                             npc_standing_on=bool(cfg.get("npc_standing")))
    return {"applied": written, "pending_nodes": pending_names,
            "summary": proposals.get("summary", ""), "new": len(new_lines)}


def drain_inbox(cfg, tpath, world, spath) -> dict:
    """Apply every fold job the background archivist parked in the inbox — on the TURN thread, so it is
    the single writer of state/canon/threads and the fold-vs-turn race cannot occur. Called at the top
    of each turn (before undo.snapshot, so a fold survives an undo of the turn it drained on).

    Guards, per job (each carries the transcript window [start, end) it proposed from):
      • malformed / already-folded (end ≤ current watermark) → drop
      • ORPHANED — the transcript shrank below `end` (an undo took those turns back) → drop
      • start < watermark (overlaps folded turns) → drop; the un-folded tail is re-proposed next cadence
      • start > watermark (an earlier window's job is still pending) → RE-QUEUE for a later drain
      • start == watermark (contiguous) → apply, advancing the watermark to `end`
    Jobs are sorted by start so out-of-order daemon completion still applies contiguously."""
    jobs = inbox.take(spath)
    if not jobs:
        return {"applied": 0}
    jobs.sort(key=lambda j: int(j.get("start", 0) or 0))
    applied = 0
    for job in jobs:
        try:
            start = int(job.get("start", 0) or 0)
            end = int(job.get("end", 0) or 0)
            if end <= start:
                continue                              # malformed → drop
            wm_now = int(state.load(spath).get("_consolidated", 0) or 0)
            if end <= wm_now:
                continue                              # already folded → drop
            tlines = transcript.read_all(tpath)
            if len(tlines) < end:
                continue                              # orphaned by an undo (turns gone) → drop
            fp = job.get("fp")
            if fp is not None and window_fingerprint(tlines[start:end]) != fp:
                continue                              # window REGROWN with different content (undo→replay) → stale, drop
            if start < wm_now:
                continue                              # overlaps folded turns → drop; tail re-proposed later
            if start > wm_now:
                inbox.append(spath, job)              # predecessor window still pending → re-queue
                continue
            _fold_proposals(job.get("proposals") or {}, world, spath, start, end, bool(job.get("apply_canon")),
                            world_state=bool(cfg.get("world_state")), npc_standing_on=bool(cfg.get("npc_standing")))
            applied += 1
        except Exception:
            continue
    return {"applied": applied}
