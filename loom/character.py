"""loom.character — per-character voice + evolving disposition.

A character's manner of speech (canon frontmatter `voice:`) is injected when they are in
the scene, so NPCs sound like themselves turn to turn rather than blurring into one
narrator voice. Their `disposition:` toward the player (updated by consolidation as the
relationship grows) colors how they treat you.

Pairs with npc.py: the characters that *want* things (drives) now also *sound* like
themselves and warm or cool toward the player.
"""
from __future__ import annotations
from . import prompt_security as sec


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
            bits.append(f"speaks {sec.neutralize(c['voice'])}")
        if c["disposition"]:
            bits.append(f"is {sec.neutralize(c['disposition'])} toward the player")
        if bits:
            lines.append(f"- {sec.neutralize(c['name'])} {'; '.join(bits)}")
    if not lines:
        return ""
    return "\n\nVOICES (keep each character consistent, distinct from the narrator):\n" + "\n".join(lines)


def card(node) -> dict:
    """A structured character card from a canon node — who/what they are, when/where they
    were met, their drive, voice, and disposition. Frontmatter fields + the body."""
    fm = node["frontmatter"]

    def g(k):
        return str(fm.get(k, "")).strip()

    return {"name": node["name"], "role": g("role"), "met": g("met"),
            "voice": g("voice"), "disposition": g("disposition"),
            "want": g("wants"), "bound": g("bound"),
            "description": node["body"].strip()}
