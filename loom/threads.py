"""loom.threads — the plan above canon.

Canon is what's TRUE; threads are what's PENDING — the open dramatic questions and
scheduled world events the director paces into the story. A thread ripens with time
and, faster, when the player drifts NEAR its subject (the same canon the scene is
grounded on). The director (director.py) decides when a ripe, scene-coherent thread
becomes a beat — so surprise is seeded and earned, never invented from nowhere.

Lifecycle:  dormant → seeded → ripening → ready → resolved
  - dormant:  known to the plan, not yet in play. Activates (→seeded) only when the
              player comes near its canon — that's the moment to plant a foreshadow.
  - ready:    ripe enough to pay off, if the governor allows and the scene fits.
  - clock:    a world event that fires on a countdown, on the world's own behalf.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field, asdict, fields
from pathlib import Path


def make_id(text: str) -> str:
    """A stable, readable thread id from its question (first few words)."""
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return "-".join(words[:6]) or "thread"

READY = 0.7          # readiness at which a thread may pay off
NEAR = 0.30          # readiness gained per beat while the player is near its subject
DRIFT = 0.05         # slow ambient ripening once a thread is seeded


@dataclass
class Thread:
    id: str
    question: str                       # the open dramatic question / pending event
    kind: str = "question"              # "question" (proximity-driven) | "clock" (time-driven)
    status: str = "dormant"             # dormant → seeded → ripening → ready → resolved
    readiness: float = 0.0              # 0..1
    entities: list = field(default_factory=list)   # canon node names it involves
    clock: object = None                # beats until a clock thread fires (int) or None
    seed: str = ""                      # the subtle foreshadow to plant
    payoff: str = ""                    # what advancing / answering it looks like (if unstaged)
    stages: list = field(default_factory=list)   # optional arc: successive payoff beats
    stage: int = 0                      # position along the arc


def load(path) -> list:
    p = Path(path)
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    known = {f.name for f in fields(Thread)}
    out = []
    for t in raw if isinstance(raw, list) else []:
        if isinstance(t, dict) and t.get("id") and t.get("question"):
            th = Thread(**{k: v for k, v in t.items() if k in known})
            try:                                         # a non-int clock must not crash advance()
                th.clock = int(th.clock) if th.clock is not None else None
            except (TypeError, ValueError):
                th.clock = None
            out.append(th)
    return out


def save(path, threads) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps([asdict(t) for t in threads], indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(p)


def advance(threads, scene_names) -> list:
    """Ripen every thread by one beat and return the ones newly SEEDED this beat
    (dormant → seeded, i.e. the player just wandered near them — the moment to plant a
    foreshadow). Proximity ripens fast, time ripens seeded threads slowly, clocks tick
    down. Mutates in place."""
    scene = set(scene_names or [])
    newly_seeded = []
    for th in threads:
        if th.status == "resolved":
            continue
        if th.kind == "clock":
            if th.clock is not None:
                th.clock -= 1
                if th.clock <= 0:
                    th.status, th.readiness = "ready", 1.0
                elif th.status != "ready":
                    th.status = "ripening"
            continue
        near = any(e in scene for e in th.entities)
        if th.status == "dormant":
            if near:
                th.status, th.readiness = "seeded", max(th.readiness, 0.30)
                newly_seeded.append(th)
            continue
        th.readiness = min(1.0, th.readiness + (NEAR if near else DRIFT))
        th.status = "ready" if th.readiness >= READY else "ripening"
    return newly_seeded
