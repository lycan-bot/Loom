"""loom.tone — the register scalar: how grim or warm THIS scene should sound.

Maps the current scene's context to a control-vector scale for loom's patched llama.cpp server
(dynamic tone). Positive = dread, negative = cozy; the vector is asymmetric (dread ~+2.5, cozy ~-5)
and clamped to a coherent band (past ~+4.5 the model shatters). Driven by the world's authored genre,
the scene's location `tone:`, and the tension homeostat — so a calm library reads warm and a
monster-fen reads grim, live, turn to turn. Off unless `tone_steer` is set AND the server is serving
the tone vector (an absent vector just ignores the scale — harmless).
"""
from __future__ import annotations
from . import setting

_DREAD = ("horror", "dread", "grim", "dark", "noir", "gothic", "bleak", "eerie", "macabre",
          "cosmic", "sinister", "ominous", "haunt", "nightmar", "menac", "foreboding")
_COZY = ("cozy", "cosy", "warm", "gentle", "wholesome", "idyllic", "pastoral", "comfort",
         "slice-of-life", "light-hearted", "lighthearted", "whimsical", "hopeful", "tender", "peace")

FLOOR, CEIL = -5.0, 3.0          # the coherent band for the tone vector


def _bias(text) -> float:
    t = (text or "").lower()
    b = 0.0
    if any(w in t for w in _DREAD):
        b += 1.8
    if any(w in t for w in _COZY):
        b -= 3.2                  # cozy needs more push than dread (the vector is asymmetric)
    return b


def scale(world, tension, scene_nodes=None) -> float:
    """The tone control-vector scale for this scene. Genre + location tone set the register; the
    tension homeostat pushes it grimmer as danger rises, warmer as it settles. Clamped to the band."""
    card = setting.card(world)
    base = _bias(f"{card.get('genre', '')} {card.get('tone', '')}")
    # a place IN the scene with its own tone overrides the world's baseline register
    for n in (scene_nodes or []):
        fm = n.get("frontmatter", {})
        if fm.get("kind") == "place" and str(fm.get("tone", "")).strip():
            base = _bias(str(fm["tone"]))
            break
    tterm = (float(tension) - 0.2) * 10.0     # tension 0.05(calm)..0.45(grim) → ~-1.5..+2.5 about neutral 0.2
    return round(max(FLOOR, min(CEIL, base + tterm)), 2)
