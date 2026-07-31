"""loom.transcript — the append-only record of play (the OBSERVE tier).

The raw log: the audit trail and the source for consolidation. It is NOT what the
narrator reasons from turn to turn — that is CANON. Keeping these separate is the
whole point (see consolidate.py: narrate from canon, never from the raw log).
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append(path: Path, role: str, text: str, **extra) -> dict:
    """Append one entry. role ∈ {'player','narrator','system'}."""
    entry = {"t": _now(), "role": role, "text": text}
    entry.update(extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_all(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def recent(path: Path, n: int) -> list[dict]:
    return read_all(path)[-n:]
