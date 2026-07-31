"""loom.character — per-character voice + evolving disposition.

A character's manner of speech (canon frontmatter `voice:`) is injected when they are in
the scene, so NPCs sound like themselves turn to turn rather than blurring into one
narrator voice. Their `disposition:` toward the player (updated by consolidation as the
relationship grows) colors how they treat you.

Pairs with npc.py: the characters that *want* things (drives) now also *sound* like
themselves and warm or cool toward the player.
"""
from __future__ import annotations


def scene_characters(nodes) -> list:
    """Characters present in the retrieved scene, with their voice + disposition."""
    out = []
    for n in nodes:
        if n["frontmatter"].get("kind") != "character":
            continue
        out.append({"name": n["name"],
                    "voice": str(n["frontmatter"].get("voice", "")).strip(),
                    "disposition": str(n["frontmatter"].get("disposition", "")).strip()})
    return out


def voice_clause(nodes) -> str:
    """A prompt clause giving each in-scene character's voice + disposition, so the narrator
    keeps them consistent. Empty when no voiced characters are present."""
    lines = []
    for c in scene_characters(nodes):
        bits = []
        if c["voice"]:
            bits.append(f"speaks {c['voice']}")
        if c["disposition"]:
            bits.append(f"is {c['disposition']} toward the player")
        if bits:
            lines.append(f"- {c['name']} {'; '.join(bits)}")
    if not lines:
        return ""
    return "\n\nVOICES (keep each character consistent, distinct from the narrator):\n" + "\n".join(lines)
