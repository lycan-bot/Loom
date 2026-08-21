"""loom.mood — an NPC's felt mood, as a READ-VIEW (NPC-agency R3).

A mood is NOT a stored feeling that could self-reinforce (feel→act→re-read→deepen = an idée-fixe). It
is COMPOSED at read time from signals that are already blessed:
  • TENOR   — how they feel toward the player, from the canon `disposition` (provenance._valence), and
              the world's regard of the player via reputation standing,
  • DRIVE   — the felt state of their pursuit, read off their agenda's status (their relational thread's
              ripening, which the director advances from blessed play).
So a character reads 'warm and keyed-up' or 'cool, holding something back' with no writable mood state
to drift into. Sized by char_rung — only a character the story affords personhood carries a mood.
"""
from __future__ import annotations
from . import provenance


def _drive(status) -> str:
    """The felt tenor of a pursuit, from agenda's status phrase (a blessed thread-ripeness read)."""
    s = (status or "").lower()
    if "at a head" in s:
        return "keyed-up, ready to act"
    if "pressing" in s:
        return "restless, the pull building"
    if "reached" in s or "passed" in s:
        return "at ease, a goal behind them"
    if "first step" in s:                              # seeded: 'stirring — a first step taken'
        return "quietly stirring"
    if "private wish" in s or "not yet" in s or "latent" in s or "held in check" in s:
        return "holding something back"                # matched BEFORE a bare 'stirring' ('not yet stirring')
    if "stirring" in s:
        return "quietly stirring"
    return ""


def read(disposition, standing, pursuit_status) -> dict:
    """A composed mood {tenor, gravity, drive} — all from blessed signals, nothing stored."""
    val = provenance._valence(disposition or "")
    tenor = "warm toward you" if val > 0 else "cool toward you" if val < 0 else ""
    try:
        st = int(standing or 0)
    except (TypeError, ValueError):
        st = 0
    gravity = "buoyed" if st >= 2 else "beleaguered" if st <= -2 else ""
    return {"tenor": tenor, "gravity": gravity, "drive": _drive(pursuit_status)}


def label(disposition, standing, pursuit_status) -> str:
    """A short mood phrase, or '' when nothing composes."""
    m = read(disposition, standing, pursuit_status)
    return ", ".join(b for b in (m["tenor"], m["gravity"], m["drive"]) if b)


def clause(name, disposition, standing, pursuit_status, rung) -> str:
    """A one-line mood for the world-round / scene prompt — '' when rung 0 or no signal composes."""
    if float(rung or 0) <= 0:
        return ""
    lab = label(disposition, standing, pursuit_status)
    return f"{name} feels {lab}." if lab else ""
