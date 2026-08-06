"""loom.depth — the realness dial's PROACTIVE half.

The referee (referee.py) is the REACTIVE half: it catches, after the fact, when the world
got rewritten on the player's say-so. This is the complement — as `depth` rises, it instills
the "other" disposition into the narrator *itself*, telling it to embody a world with its own
life that doesn't rearrange itself around the player. Belt (this clause) and suspenders (the
referee) together turn a mirror into an other.

depth 0 = mirror (nothing added — exactly today's narrator); depth 1 = other.

`depth` is the MIRROR↔OTHER axis ONLY. Tone (cozy↔grim, via tension_baseline) and dice
(mechanics) are orthogonal knobs, deliberately NOT folded in here — a deeply-real world can
be cozy, and a shallow one can be grim.
"""
from __future__ import annotations

# clauses turn on as depth crosses each threshold, so the disposition intensifies smoothly
_LEVELS = (
    (0.25, "The world has a life of its own and does not simply rearrange itself around the player."),
    (0.50, "Characters pursue their own wants and are not here to serve the player; trust, help, "
           "and favors are earned, never assumed."),
    (0.75, "Do not hand the player convenient outcomes or bend events in their favor — let the "
           "world, and the people in it, resist being used, and let real attempts sometimes simply fail."),
)


def disposition_clause(depth) -> str:
    d = float(depth or 0)
    parts = [text for thresh, text in _LEVELS if d >= thresh]
    if not parts:
        return ""
    return "\n\nTHE WORLD RESISTS (realness):\n" + "\n".join(f"- {p}" for p in parts)
