"""loom.mechanics — an optional, toggleable dice layer (default OFF).

When on (config `mechanics: true`), each turn carries an impartial d20 fate-roll injected
into the narrator's prompt. If the player's action has an uncertain outcome, the roll —
not the model's whim — decides it, including real failure. This is the 'no plot armor'
option: chance gets a vote, so stakes are honest. It composes with the restraint
architecture — the world still never manufactures conflict; it just resolves fairly.
"""
from __future__ import annotations
import random

_BANDS = [
    (1,  1,  "critical failure", "it goes badly wrong, with a real complication"),
    (2,  5,  "failure",          "it does not work — a setback or cost"),
    (6,  10, "partial",          "it half-works — success with a cost, or a mixed result"),
    (11, 15, "success",          "it works"),
    (16, 19, "strong success",   "it works well, better than hoped"),
    (20, 20, "critical success", "an exceptional, lucky outcome"),
]


def roll(rng=None) -> int:
    return (rng or random).randint(1, 20)


def band(r: int):
    for lo, hi, label, guide in _BANDS:
        if lo <= r <= hi:
            return label, guide
    return "success", "it works"


def clause(r: int) -> str:
    label, guide = band(r)
    return (f"\n\nMECHANICS: this turn's impartial fate-roll is d20 = {r} ({label} — {guide}). "
            f"IF the player's action has a genuinely uncertain outcome (a risk, a contest, a feat of "
            f"skill or chance), let THIS roll decide it — narrate the result honestly, including "
            f"failure and cost. If the action carries no real uncertainty, ignore the roll.")
