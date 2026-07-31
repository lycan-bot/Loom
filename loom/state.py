"""loom.state — continuity deltas (the MUTATE tier): the small set of facts that
change as play proceeds ("king_dead": true, "party_gold": 40). Plain JSON.
"""
from __future__ import annotations
import json
from pathlib import Path


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def set_fact(path: Path, key: str, value) -> dict:
    s = load(path)
    s[key] = value
    save(path, s)
    return s
