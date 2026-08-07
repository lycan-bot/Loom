"""loom.length — how wordy the narrator is.

A single dial from terse to lavish. The PROMPT DIRECTIVE does the shaping; the token cap is only a
LOOSE backstop against a model (like Mag-Mell) that ignores its instructions entirely — set well
above each target so a compliant, or even mildly verbose, response finishes naturally and is never
clipped into a broken sentence or nothing. Lean on the directive, not the clamp.

The default 'vivid' reins the sprawl without going clipped; 'lavish' restores the old expansive
feel. Tune with `loom length <level>` or the ⚙ settings.
"""
from __future__ import annotations
import re

# a clean-cut point: everything up to the LAST sentence-ender (. ! ?) at a word boundary
_CLIP = re.compile(r'.*[.!?]["”\'’)]?(?=\s|$)', re.S)

# level -> (prompt directive, LOOSE token backstop). Caps are generous: a terse 1-2 sentence reply
# is ~40 words, far under 200 tokens, so it ends on its own — only a model wholly ignoring the
# directive is trimmed, and even then to a couple of sentences, never to nothing.
_LEVELS = {
    "terse":  ("Answer in 1-2 tight sentences — just what happens; no scene-painting.", 220),
    "brief":  ("Keep it to a short paragraph: a few spare, concrete sentences.", 400),
    "vivid":  ("Write 2-3 short paragraphs — vivid but economical; do not pad or over-describe.", 650),
    "lavish": ("Write richly and at length.", 900),
}
DEFAULT = "vivid"
LEVELS = tuple(_LEVELS)


def normalize(level) -> str:
    return level if level in _LEVELS else DEFAULT


def clause(level) -> str:
    """The narrator-prompt directive for this level (empty only if a level had none)."""
    d = _LEVELS[normalize(level)][0]
    return f"\n\nLENGTH: {d}" if d else ""


def max_tokens(level, fallback) -> int:
    """The soft token cap for this level, falling back to the config default."""
    return _LEVELS[normalize(level)][1] or fallback


def trim(text) -> str:
    """If the token cap clipped the narration mid-sentence (it doesn't end on terminal punctuation),
    drop the dangling fragment back to the last COMPLETE sentence — so the cap shortens cleanly
    instead of leaving 'To your right,' hanging. A no-op when the model ended on its own."""
    t = (text or "").rstrip()
    if not t or t[-1] in '.!?"”\'’)':
        return t
    m = _CLIP.match(t)
    return m.group(0).rstrip() if m else t
