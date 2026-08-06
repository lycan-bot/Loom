"""loom.director — decides WHEN a pending thread becomes a beat, and WHAT kind.

The governor (pacing.py) says whether there's ROOM for a beat; the director says
whether one is WARRANTED and picks it. Surprise here is always a ripe, scene-coherent,
seeded thread — never invented drama. Priority:

  1. payoff — there's room (a stall) and the player is near a READY thread → pay it off
  2. world  — a clock thread has come due → the world moves on its own behalf (if calm)
  3. seed   — the player just wandered near a new thread → plant a quiet foreshadow
  4. hook   — room, but nothing seeded nearby → a generic gentle nudge
  5. none   — hold

Every world/seed/payoff beat is gated on low tension: nothing lands mid-intensity.
"""
from __future__ import annotations
from dataclasses import dataclass
from . import prompt_security as sec

_TENSION_CEIL = 0.45


@dataclass(frozen=True)
class Beat:
    mode: str            # "payoff" | "world" | "seed" | "hook" | "none"
    thread: object = None


def decide(threads, scene_names, pacing, newly_seeded=None) -> Beat:
    scene = set(scene_names or [])
    newly_seeded = newly_seeded or []
    calm = pacing.tension < _TENSION_CEIL

    near = [t for t in threads if t.kind == "question" and t.status != "resolved"
            and any(e in scene for e in t.entities)]

    # 1. room (stall) AND a ripe thread the player is near → pay it off
    if pacing.directive == "offer" and calm:
        ready = [t for t in near if t.status == "ready"]
        if ready:
            return Beat("payoff", max(ready, key=lambda t: t.readiness))

    # 2. the world moves on its own clock, independent of the player (never mid-tension)
    clocks = [t for t in threads if t.kind == "clock" and t.status == "ready"]
    if clocks and calm:
        return Beat("world", clocks[0])

    # 3. the player just wandered near a new thread → plant a quiet seed (even while engaged)
    if newly_seeded and calm:
        return Beat("seed", newly_seeded[0])

    # 4. room but nothing seeded nearby → a generic gentle nudge
    if pacing.directive == "offer":
        return Beat("hook")

    return Beat("none")


def settle(beat) -> None:
    """Apply the consequence of delivering a beat. A staged thread advances one stage and
    resolves at the end of its arc; an unstaged thread cools down to re-ripen."""
    t = beat.thread
    if t is None:
        return
    if beat.mode == "payoff":
        if getattr(t, "stages", None):
            t.stage += 1
            if t.stage >= len(t.stages):
                t.status, t.readiness = "resolved", 1.0    # the arc is complete
            else:
                t.readiness, t.status = 0.3, "ripening"    # next stage will deepen it
        else:
            t.readiness, t.status = 0.3, "ripening"
    elif beat.mode == "world":
        t.status = "resolved"                        # the scheduled event has happened


def clause(beat) -> str:
    t = beat.thread
    # thread text is model-authored (consolidation / imagine); fence it as untrusted DATA so an
    # injected instruction inside a blessed/imagined thread can't read as a trusted narrator
    # directive. The imperative framing is fixed template text; only the datum is fenced.
    if beat.mode == "payoff":
        stages = getattr(t, "stages", None)
        step = stages[t.stage] if stages and t.stage < len(stages) else t.payoff
        tail = f"\nmoving it toward: {sec.wrap(step, 'thread')}" if step else ""
        return (f"\n\nPACING: the moment is right to draw this thread a little closer:\n"
                f"{sec.wrap(t.question, 'thread')}{tail}\nOffer the player a gentle opening toward it, "
                f"kept low-key and easy to decline. No forced drama or danger.")
    if beat.mode == "world":
        return (f"\n\nTHE WORLD MOVES: independently of the player, the following comes to pass:\n"
                f"{sec.wrap(t.payoff or t.question, 'thread')}\nLet this enter the scene naturally and in "
                f"proportion, woven into what the player is already doing — a turn of events, not an ambush.")
    if beat.mode == "seed":
        return (f"\n\nUNDERCURRENT: something is latent here:\n{sec.wrap(t.seed or t.question, 'thread')}\n"
                f"Weave only the faintest hint of it into the scene as a passing detail or atmosphere. "
                f"Plant it; do NOT explain or develop it yet.")
    if beat.mode == "hook":
        from . import pacing as _p
        return _p._OFFER_CLAUSE
    return ""
