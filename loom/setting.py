"""loom.setting — the world's card: its authored genre + the register the narrator writes in.

A world's genre / age / tech / magic / peoples / tone live as frontmatter on its lore node (set by
`loom generate`, or hand-authored). This surfaces them as a SETTING clause so the narrator keeps
every scene true to the register — cosmic horror stays cosmic horror, space opera stays space opera
— instead of drifting into a generic voice. Fully authorable: edit the world node to change the theme.

The world card is the lore node flagged `setting: true`; failing that, the lore node carrying the
most world-attributes (a generated or hand-built card); failing that, nothing (an un-themed world).
"""
from __future__ import annotations
from . import canon
from . import prompt_security as sec

_ATTRS = ("genre", "age", "tech", "magic", "peoples", "tone")
_TRUE = ("true", "1", "yes")


def get(world):
    """The world's card node (see module doc for the resolution order), or None."""
    lore = [n for n in canon.load_all(world) if n["frontmatter"].get("kind") == "lore"]
    if not lore:
        return None
    flagged = [n for n in lore if str(n["frontmatter"].get("setting", "")).strip().lower() in _TRUE]
    if flagged:
        return flagged[0]
    richest = max(lore, key=lambda n: sum(1 for a in _ATTRS if n["frontmatter"].get(a)))
    return richest if any(richest["frontmatter"].get(a) for a in _ATTRS) else None


def card(world) -> dict:
    """The world card's attributes (name + genre/age/tech/magic/peoples/tone), or {} if un-themed."""
    n = get(world)
    if not n:
        return {}
    fm = n["frontmatter"]
    c = {"name": n["name"]}
    c.update({a: str(fm.get(a, "")).strip() for a in _ATTRS})
    return c


def clause(world) -> str:
    """The narrator-prompt injection that pins the story's register to the authored genre."""
    c = card(world)
    parts = [f"{a}: {sec.neutralize(c[a])}" for a in _ATTRS if c.get(a)]
    if not parts:
        return ""
    return ("\n\nSETTING (write in THIS register — keep every scene true to it): "
            + "; ".join(parts) + ".")
