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


def _atomic_write(spath, rows) -> None:
    """Rewrite the whole timeline via a temp + os.replace — used only on the rare who-merge path (a torn
    write can't corrupt the log)."""
    p = _path(spath)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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


def _who_list(w):
    """Normalize an event's actor(s) to a clean list of names — accepts a string or a list."""
    if isinstance(w, (list, tuple)):
        return [str(x).strip() for x in w if str(x).strip()]
    w = str(w or "").strip()
    return [w] if w else []


def record(spath, events, entry_start=None, entry_end=None, source="play") -> int:
    """Append events to the timeline. Each event is {what, when?, who?}; the real clock is the TRANSCRIPT-
    ENTRY range (entry_start, entry_end) — entry indices, not turn/pair counts — plus the source. An
    optional `who` (the acting NPC name, or a list) makes the beat addressable per-agent for npc_memory.
    Dedup by (entry_start, normalized what) so a re-consolidated window doesn't double-log. Returns
    how many were newly written."""
    existing = entries(spath)
    by_key = {}
    for e in existing:                                    # first occurrence per key (rows carry references)
        by_key.setdefault((e.get("entry_start"), _norm(e.get("what"))), e)
    fresh, merged = [], False
    for e in events or []:
        if not (isinstance(e, dict) and str(e.get("what", "")).strip()):
            continue
        row = {"what": str(e.get("what", "")).strip(), "entry_start": entry_start, "entry_end": entry_end,
               "source": source}
        when = str(e.get("when", "")).strip()
        if when:
            row["when"] = when                            # the in-fiction 'story time' clock (best-effort)
        who = _who_list(e.get("who"))
        if who:
            row["who"] = who                              # the actor(s) — lets an NPC recall its OWN beats
        key = (entry_start, _norm(row["what"]))
        prior = by_key.get(key)
        if prior is not None:
            if who:                                       # a re-fold that names an actor the stored beat MISSED
                have = {_norm(c) for c in _who_list(prior.get("who"))}   # → union the who instead of dropping it,
                add = [w for w in who if _norm(w) not in have]           # so the added actor still recalls the beat
                if add:
                    prior["who"] = _who_list(prior.get("who")) + add
                    merged = True
            continue
        by_key[key] = row
        fresh.append(row)
    if merged:                                            # a stored row's who grew → rewrite the log (rare path)
        _atomic_write(spath, existing + fresh)
        return len(fresh)
    if fresh:
        with open(_path(spath), "a", encoding="utf-8") as f:
            for row in fresh:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(fresh)


_STOP = frozenset((
    "the a an and or but of to in on at by for with when where why how what who whom which that this"
    " these those did do does was were is are be been am has have had will would can could may might"
    " we you they she he it him her them us i me my your our their his its there then from as so if"
    " about into over under after before again ago long time happen happened").split())


def query(spath, q, k: int = 6) -> list[dict]:
    """Timeline events most relevant to `q`. Query stopwords are dropped, then BM25 (the ranker recall
    uses) over the event text + story time — so 'when did the ritual fail?' searches on 'ritual fail'
    and never surfaces an unrelated dragon beat on a shared 'the'. Only genuine matches (score>0)."""
    from . import retrieve
    evs = entries(spath)
    if not evs:
        return []
    qtoks = [t for t in re.findall(r"[a-z0-9]+", (q or "").lower()) if len(t) > 2 and t not in _STOP]
    if not qtoks:
        return []
    docs = [{"name": str(i), "body": (str(e.get("what", "")) + " " + str(e.get("when", ""))).strip()}
            for i, e in enumerate(evs)]
    by_i = {str(i): e for i, e in enumerate(evs)}
    return [by_i[name] for name, score in retrieve._bm25(" ".join(qtoks), docs)[:k] if score > 0 and name in by_i]
