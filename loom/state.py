"""loom.state — continuity deltas (the MUTATE tier): the small set of facts that
change as play proceeds ("king_dead": true, "party_gold": 40). Plain JSON.
"""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}   # tolerate a non-object state file
    except Exception:
        return {}


def save(path: Path, state: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # a UNIQUE temp per write — a fixed '.tmp' collides when two turns save concurrently (the world
    # round adds a second per-turn state write), and one tmp.replace then fails with FileNotFoundError
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def set_fact(path: Path, key: str, value) -> dict:
    s = load(path)
    s[key] = value
    save(path, s)
    return s
