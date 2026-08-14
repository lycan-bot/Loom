"""loom.provenance — the fact ledger (reconciliation + provenance; the memory keystone).

Every gated change to durable truth — a character's disposition, their location, a state fact — is
logged here as old→new with when + why, instead of silently clobbering the prior value (the
`fm[k]=v` last-writer-wins the consolidation floor otherwise does). So three things become possible:
  • "how do I know this?" has an answer (the audit trail),
  • a bad fact can be reversed (undo truncates this log like the transcript),
  • a REVERSAL — a value that contradicts what was established, with no reason — is a FLAGGED
    contradiction surfaced to the operator, not a quiet rewrite.
This is the write-boundary miniature of the anti-collapse floor: truth changes, but never silently.

Append-only, blessed side of the diode (it records what consolidation already gated). On-demand read.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

# a disposition's affective valence, so a warm→hostile flip is caught as a reversal but warm→warmer isn't.
# Matched by WHOLE WORD (not substring — 'cold' must not fire inside 'coldly'), scoring BOTH poles so a
# mixed phrase goes by majority, with negation ('no longer trusting') and dis-/un- prefixes inverting.
_WARM = {"warm", "warmer", "warmth", "friendly", "friend", "allied", "ally", "fond", "affectionate",
         "trusting", "trust", "trusts", "intrigued", "protective", "tender", "loyal", "devoted",
         "curious", "kind", "gentle", "smitten", "welcoming", "welcome", "close", "grateful", "admiring"}
_COLD = {"hostile", "hostility", "antagonistic", "wary", "warier", "cold", "colder", "coldly",
         "suspicious", "afraid", "angry", "anger", "resentful", "resents", "distrustful", "distrust",
         "bitter", "guarded", "fearful", "contemptuous", "betrayed", "betray", "betrays",
         # a lethal/threat intent is a hard flip against any prior warmth, even worded without a mood word
         "dead", "kill", "kills", "killed", "murder", "murderous", "harm", "destroy", "slay", "poison",
         "hate", "hates", "loathe", "enemy", "vengeful", "vengeance", "menacing", "threatening"}
_NEGATORS = {"not", "never", "no", "nor", "none", "isnt", "arent", "wasnt", "werent",
             "cant", "cannot", "dont", "doesnt", "didnt", "wont", "aint"}


def _path(spath) -> Path:
    return Path(spath).parent / "facts_log.jsonl"


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", str(s).lower()).strip()


def _tok_valence(t: str) -> int:
    """One token's valence, with dis-/un- treated as a negated root ('disloyal'/'unfriendly' → cold)."""
    if t in _WARM:
        return 1
    if t in _COLD:
        return -1
    for p in ("dis", "un"):
        if t.startswith(p) and t[len(p):] in _WARM:
            return -1
        if t.startswith(p) and t[len(p):] in _COLD:
            return 1
    return 0


def _valence(disp: str) -> int:
    """+1 warm, −1 cold, 0 neutral/unknown. Majority of whole-word pole hits, flipped by a sentence
    negator ('no longer trusting' reads cold). Neutral on a tie or no lexicon hit — a miss scores 0,
    never a wrong sign (a lexicon-free betrayal is beyond a word list; that's the semantic tier's job)."""
    d = _norm(disp)
    toks = d.split()
    warm = sum(1 for t in toks if _tok_valence(t) > 0)
    cold = sum(1 for t in toks if _tok_valence(t) < 0)
    score = 1 if warm > cold else (-1 if cold > warm else 0)
    if score != 0 and (set(toks) & _NEGATORS or "no longer" in d or "no more" in d):
        score = -score
    return score


def is_reversal(field: str, old, new) -> bool:
    """True when new CONTRADICTS old (not a monotone refinement). Dispositions: opposite affective
    valence (warm↔hostile). Other fields: any change of a previously-set value is a reversal-candidate
    (a location or fact that flips is worth flagging; the archivist rarely relocates a static one)."""
    old, new = str(old or "").strip(), str(new or "").strip()
    if not old or old.lower() == new.lower():
        return False
    if field == "disposition":
        vo, vn = _valence(old), _valence(new)
        return vo != 0 and vn != 0 and vo != vn
    return True                                   # a changed location/fact is a contradiction-candidate


def log(spath, records) -> int:
    """Append change records. Each: {kind, name, field, old, new, entry_start, entry_end, source,
    reversal}. Returns how many were written. Never logs a no-op (old == new)."""
    fresh = []
    for r in records or []:
        if not isinstance(r, dict):
            continue
        old, new = str(r.get("old", "")).strip(), str(r.get("new", "")).strip()
        if not new or old.lower() == new.lower():
            continue
        fresh.append({"kind": r.get("kind", ""), "name": r.get("name", ""), "field": r.get("field", ""),
                      "old": old, "new": new, "entry_start": r.get("entry_start"), "entry_end": r.get("entry_end"),
                      "source": r.get("source", "consolidate"), "reversal": bool(r.get("reversal"))})
    if not fresh:
        return 0
    with open(_path(spath), "a", encoding="utf-8") as f:
        for r in fresh:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(fresh)


def entries(spath) -> list[dict]:
    """The whole ledger, oldest first. Malformed lines skipped."""
    p = _path(spath)
    if not p.exists():
        return []
    out = []
    try:
        raw = p.read_text("utf-8")
    except Exception:
        return []
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
            if isinstance(r, dict):
                out.append(r)
        except Exception:
            continue
    return out


def history(spath, name=None, field=None) -> list[dict]:
    """The change history, newest first, optionally filtered to one entity / field — 'how did we get
    to this value?'."""
    rows = entries(spath)
    if name:
        rows = [r for r in rows if _norm(r.get("name")) == _norm(name)]
    if field:
        rows = [r for r in rows if r.get("field") == field]
    return list(reversed(rows))


def reversals(spath, since_entry: int = 0) -> list[dict]:
    """Flagged contradictions (a value that reversed with no monotone reason) at/after `since_entry` —
    the anti-collapse signal a guard surfaces. A record with no window (entry_start=None, the legacy /
    parked-fold path) is ALWAYS included — never silently dropped by a windowed query, or the operator
    would miss a genuine flip that happens to lack a deed_window."""
    out = []
    for r in entries(spath):
        if not r.get("reversal"):
            continue
        es = r.get("entry_start")
        if es is None or es >= since_entry:
            out.append(r)
    return out
