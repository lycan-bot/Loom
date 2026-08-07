"""loom.reputation — how the world regards the player, earned over time.

The player DOES things; factions and people react, and remember. Reputation is a standing per named
entity (a faction, a group, a notable person), on a small scale from hostile to allied, plus a short
log of the DEEDS that moved it — the record of what you're known for.

It follows the same diode as everything durable: standings only shift at CONSOLIDATION, from deltas
the archivist reads out of the actual play log and the operator blesses (never self-propagating from
improv). narrate READS the standings to colour how NPCs treat the player, but never writes them.

Stored inside state.json under `_rep` (an internal `_`-key, so it rides undo / sleep / the world
round for free and never leaks into the prompt as a raw continuity fact).
"""
from __future__ import annotations

CLAMP = 3                                       # standing saturates at ±3 — a scale, not a runaway counter
_LOG_CAP = 6                                    # keep the last N deeds per entity (the record stays legible)
_LABELS = {-3: "hostile", -2: "antagonistic", -1: "wary",
           0: "neutral", 1: "friendly", 2: "warm", 3: "allied"}


def label(standing: int) -> str:
    return _LABELS.get(max(-CLAMP, min(CLAMP, int(standing))), "neutral")


def load(state_dict: dict) -> dict:
    """The reputation map out of a loaded state dict: {name: {"standing": int, "log": [str, ...]}}."""
    rep = state_dict.get("_rep")
    return rep if isinstance(rep, dict) else {}


def apply_delta(rep: dict, who: str, delta: int, because: str) -> dict:
    """Shift `who`'s standing by `delta` (clamped) and record the deed. Mutates + returns `rep`."""
    who = str(who).strip()
    if not who:
        return rep
    try:
        delta = int(delta)
    except (TypeError, ValueError):
        return rep
    entry = rep.get(who)
    if not isinstance(entry, dict):
        entry = {"standing": 0, "log": []}
    standing = max(-CLAMP, min(CLAMP, int(entry.get("standing", 0) or 0) + delta))
    log = [s for s in entry.get("log", []) if isinstance(s, str)]
    because = str(because).strip()
    if because:
        arrow = "▲" if delta > 0 else "▼" if delta < 0 else "•"
        log.append(f"{arrow} {because}")
    rep[who] = {"standing": standing, "log": log[-_LOG_CAP:]}
    return rep


def clause(rep: dict) -> str:
    """A prompt fragment telling the narrator how the world currently regards the player, so NPCs
    of a faction act on its standing. '' when the player has no reputation yet."""
    def _flat(s: str) -> str:
        return " ".join(str(s).split())          # collapse newlines/whitespace so an interpolated

    lines = []                                   # value can't break the prompt frame (defense-in-depth)
    for who, entry in sorted(rep.items()):
        if not isinstance(entry, dict):
            continue
        standing = int(entry.get("standing", 0) or 0)
        recent = (entry.get("log") or [])[-1:]
        why = f" — {_flat(recent[0]).lstrip('▲▼• ')}" if recent else ""
        lines.append(f"- {_flat(who)} regards the player as {label(standing)}{why}")
    if not lines:
        return ""
    return ("\n\nSTANDING (how factions and people regard the player right now — let it shape how "
            "their members treat the player; do NOT state it outright):\n" + "\n".join(lines))
