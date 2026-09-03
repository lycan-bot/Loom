"""loom.ablation — the retrieval-miss instrument (the embeddings kill-criterion).

Storyteller-memory's honest question: does BM25 retrieval ever MISS a canon node that mattered — often
enough to justify the semantic-embeddings spend (a co-resident embed server + a doc-vector cache)? Rather
than assume, MEASURE. Each turn this logs any canon entity the PLAYER NAMED whose node the retrieval did
NOT surface (scored out, or cut below the top-k) — a concrete miss. When the same entity is missed twice,
the kill-criterion ('a node that mattered, twice') has evidence; until then the cheap wins suffice and the
spend is unjustified. A logger that stays empty is itself the answer.

Read-only, advisory, default-OFF (the `retrieval_log` toggle → byte-identical when off). Append-only and
CAPPED. Never a canon write, never a model call.
"""
from __future__ import annotations
import json
from pathlib import Path
from . import extract

_CAP = 500                          # keep the last N miss rows — bounded, like every loom ledger


def _path(spath):
    return Path(spath).parent / "ablation_log.jsonl"


def record(spath, player_input, retrieved_names, world) -> list:
    """Log the canon entities the player NAMED that retrieval did NOT surface this turn. `retrieved_names`
    is the set/iterable of node names retrieved with score>0. Returns the missed names ([] when retrieval
    covered every named entity). Only a MISS writes a row (the log stays lean). Never raises — an
    instrument must not break a turn."""
    try:
        named = extract.present(player_input or "", world)
    except Exception:
        return []
    if not named:
        return []
    retrieved = {str(n) for n in (retrieved_names or [])}
    missed = [n for n in named if n not in retrieved]
    if not missed:
        return []
    row = {"input": (player_input or "")[:200], "named": named, "missed": missed}
    try:
        p = _path(spath)
        lines = p.read_text("utf-8").splitlines() if p.exists() else []
        lines.append(json.dumps(row, ensure_ascii=False))
        p.write_text("\n".join(lines[-_CAP:]) + "\n", encoding="utf-8")   # keep only the last _CAP rows
    except Exception:
        pass
    return missed


def entries(spath) -> list:
    """The miss log, oldest first. Malformed lines skipped, never fatal."""
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


def report(spath) -> dict:
    """Aggregate the miss log: total miss-turns, per-entity miss counts, and the entities missed >= 2×
    (the kill-criterion — 'a node that mattered, twice' — the trigger to CONSIDER semantic retrieval).
    `kill_criterion_met` False (the common case at loom's scale) is the evidence that embeddings are not
    yet earning their cost."""
    from collections import Counter
    counts = Counter()
    for r in entries(spath):
        for name in (r.get("missed") or []):
            if isinstance(name, str) and name.strip():
                counts[name] += 1
    repeated = [n for n, c in counts.most_common() if c >= 2]
    return {"miss_turns": len(entries(spath)), "distinct_missed": len(counts),
            "by_entity": dict(counts.most_common()),
            "repeated_misses": repeated,           # >= 2× → the embeddings kill-criterion has evidence
            "kill_criterion_met": bool(repeated)}
