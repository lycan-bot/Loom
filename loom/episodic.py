"""loom.episodic — the timeline spine (storyteller-memory Phase 6).

Consolidation extracts the session's EVENTS; each is recorded here with WHEN it happened on two
clocks: the real transcript range it was consolidated from, and an optional in-fiction 'story time'
the archivist read off the prose ('the next morning', 'three days later'). So "when was that?" is
always resolvable — query the log by what happened and get both clocks back.

Append-only, blessed side of the diode (events are consolidation output, like canon). Deterministic
lexical query; a vector index rides on top once embeddings land (Phase 0).
"""
from __future__ import annotations
import json
import os
import re
import tempfile
from pathlib import Path


def _path(spath) -> Path:
    return Path(spath).parent / "episodic.jsonl"


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", str(s).lower()).strip()


def entries(spath) -> list[dict]:
    """The whole timeline, oldest first. Malformed lines are skipped, never fatal."""
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
            e = json.loads(ln)
            if isinstance(e, dict) and str(e.get("what", "")).strip():
                out.append(e)
        except Exception:
            continue
    return out


def record(spath, events, turn_start=None, turn_end=None, source="play") -> int:
    """Append events to the timeline. Each event is {what, when?}; the real-turn clock (turn_start,
    turn_end) and source are stamped here. Dedup by (turn_start, normalized what) so a re-consolidated
    window doesn't double-log. Returns how many were newly written."""
    fresh, seen = [], {(e.get("turn_start"), _norm(e.get("what"))) for e in entries(spath)}
    for e in events or []:
        if not (isinstance(e, dict) and str(e.get("what", "")).strip()):
            continue
        row = {"what": str(e.get("what", "")).strip(), "turn_start": turn_start, "turn_end": turn_end,
               "source": source}
        when = str(e.get("when", "")).strip()
        if when:
            row["when"] = when                            # the in-fiction 'story time' clock (best-effort)
        key = (turn_start, _norm(row["what"]))
        if key in seen:
            continue
        seen.add(key)
        fresh.append(row)
    if not fresh:
        return 0
    with open(_path(spath), "a", encoding="utf-8") as f:
        for row in fresh:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(fresh)


def query(spath, q, k: int = 6) -> list[dict]:
    """Timeline events most relevant to `q` (lexical token-overlap over the event text + story time).
    'when did we meet the professor?' → the event(s) with both clocks."""
    qtoks = {t for t in re.findall(r"\w+", (q or "").lower()) if len(t) > 2}
    if not qtoks:
        return []
    scored = []
    for e in entries(spath):
        etoks = set(re.findall(r"\w+", (str(e.get("what", "")) + " " + str(e.get("when", ""))).lower()))
        overlap = len(qtoks & etoks)
        if overlap:
            scored.append((overlap, e))
    scored.sort(key=lambda x: (-x[0], x[1].get("turn_start") or 0))
    return [e for _s, e in scored[:k]]
