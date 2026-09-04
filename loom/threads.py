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
import os
import re
import tempfile
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
    span: object = None                 # the AUTHORED countdown length captured at seed time (int) or None — a
                                        # STABLE denominator for foreshadow intensity (clock is decremented in place)
    seed: str = ""                      # the subtle foreshadow to plant
    payoff: str = ""                    # what advancing / answering it looks like (if unstaged)
    stages: list = field(default_factory=list)   # optional arc: successive payoff beats
    stage: int = 0                      # position along the arc
    ready_beats: int = 0                # consecutive player-turns spent 'ready' without paying off (staleness)
    hidden: bool = False                # director-known; characters do NOT know it (drives foreshadow-only framing)
    scope: str = "local"                # "local" | "horizon" — a horizon thread is world-round metaplot (Brick C)


def from_dict(t):
    """Build ONE Thread from a dict — a stored row OR an operator/UI seed payload — with fail-soft
    coercion so a hand-edited/corrupted value can't crash advance() mid-turn (the pacing enhancement
    must never fail-closed). Returns None if the row lacks an id or a question. The SINGLE
    construction+coercion site, shared by load() and the operator seed path (web /api/thread/save + the
    CLI), so every field (clock, span, stages, hidden, …) is authored through identical coercion."""
    if not (isinstance(t, dict) and t.get("id") and t.get("question")):
        return None
    known = {f.name for f in fields(Thread)}
    th = Thread(**{k: v for k, v in t.items() if k in known})
    try:                                         # a non-int clock must not crash advance()
        th.clock = int(th.clock) if th.clock is not None else None
    except (TypeError, ValueError):
        th.clock = None
    try:                                         # the authored span: a stable denominator, immutable across ticks
        th.span = int(th.span) if th.span is not None else None
    except (TypeError, ValueError):
        th.span = None
    try:
        th.readiness = min(1.0, max(0.0, float(th.readiness)))
    except (TypeError, ValueError):
        th.readiness = 0.0
    try:
        th.stage = max(0, int(th.stage))         # a negative stage would index a stages arc from the end
    except (TypeError, ValueError):
        th.stage = 0
    try:
        th.ready_beats = max(0, int(th.ready_beats))
    except (TypeError, ValueError):
        th.ready_beats = 0
    th.hidden = bool(th.hidden)                  # fail-soft: a hand-edited non-bool can't crash advance()
    th.scope = th.scope if th.scope in ("local", "horizon") else "local"
    th.kind = th.kind or "question"              # empty kind/status → the dataclass defaults (matches the seed path)
    th.status = th.status or "dormant"
    if not isinstance(th.entities, list):
        th.entities = []
    if not isinstance(th.stages, list):
        th.stages = []
    return th


def load(path) -> list:
    p = Path(path)
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [th for th in (from_dict(t) for t in (raw if isinstance(raw, list) else [])) if th is not None]


def save(path, threads) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.name + ".", suffix=".tmp")   # unique: no concurrent collision
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump([asdict(t) for t in threads], f, indent=2, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def seed(path, payload):
    """Upsert one operator-authored thread into threads.json — the shared seed/edit path for the web
    endpoint AND the CLI, so the collision + clock guards live in ONE place. Returns (thread, error):
      • a NEW thread (no explicit id) whose derived id COLLIDES with an existing thread is REFUSED
        (None, msg) — the save would silently clobber it, and a clock carries structural fields
        (clock/span/hidden) whose loss is destructive; an explicit-id payload is an EDIT and updates.
      • a clock payload must count down >= 1 beat; span defaults to the authored clock at seed time.
    Operator-authored (blessed by construction) — no model in the loop for the schedule."""
    q = str(payload.get("question", "")).strip()
    if not q:
        return None, "question required"
    tid = payload.get("id") or make_id(q)
    current = load(path)
    if not payload.get("id") and any(x.id == tid for x in current):
        return None, "a thread '" + tid + "' already exists — rename the question, or edit that thread"
    p = {**payload, "id": tid, "question": q}
    if p.get("clock") is not None:
        try:
            if int(p["clock"]) < 1:                       # a 0/negative countdown fires before play — refuse it
                return None, "clock (beats) must be >= 1"
        except (TypeError, ValueError):
            return None, "clock must be an integer number of beats"
        if p.get("span") is None:
            p["span"] = p["clock"]                         # capture the AUTHORED length at seed time
    th = from_dict(p)
    if th is None:
        return None, "invalid thread"
    save(path, [x for x in current if x.id != tid] + [th])
    return th, None


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
            # a 'ready' clock has already come due — stop ticking (mirrors how a 'resolved' clock is skipped
            # above). Without this a director-only (hidden) clock, which Brick A never settles to resolved,
            # decrements forever into unbounded negative state.
            if th.clock is not None and th.status != "ready":
                th.clock -= 1
                if th.clock <= 0:
                    th.status, th.readiness = "ready", 1.0
                elif th.status != "ready":
                    th.status = "ripening"
            th.ready_beats = th.ready_beats + 1 if th.status == "ready" else 0
            continue
        near = any(e in scene for e in th.entities)
        if th.status == "dormant":
            if near:
                th.status, th.readiness = "seeded", max(th.readiness, 0.30)
                newly_seeded.append(th)
            th.ready_beats = 0                            # dormant/seeded is not 'ready' — no staleness accrues
            continue
        th.readiness = min(1.0, th.readiness + (NEAR if near else DRIFT))
        th.status = "ready" if th.readiness >= READY else "ripening"
        # staleness: count consecutive beats spent READY without paying off (the director settling it → resolved
        # clears this; a resolved thread is skipped above). A long count = an overdue / forgotten arc.
        th.ready_beats = th.ready_beats + 1 if th.status == "ready" else 0
    return newly_seeded
