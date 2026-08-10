"""loom.steer — the register weight engine (living-world control-vector steering, Phase 0).

Generalizes tone.py from a snap-scalar into a SMOOTHED, reactive weight per behavioral axis: a trait
is a response CURVE, not a fixed number. Each turn, context (genre + the scene's place `tone:` + the
tension homeostat) sets a TARGET intensity per axis; the live weight EASES toward that target and, as
the signal relaxes, the target itself returns to a baseline — so the register moves over TIME (a scene
ramps grim, then settles warm) instead of snapping. That movement-over-time is where the 'life' lives.

`compose()` collapses the axes to the single scalar the server's `control_vector_scale` accepts today
(one axis for now; the abstraction is ready for more, gated on a composability harness — see
docs/LIVING_WORLD_VECTORS.md). Advisory + off-by-default via `tone_steer`; an absent served vector just
ignores the scale (harmless). State lives in `_steer` — internal, so it rides undo/sleep like
`_tension`/`_memory` and is excluded from the facts view.
"""
from __future__ import annotations
from . import tone

_SNAP_DELTA = 3.0        # a big shift (walking into a strongly-toned place) snaps; a small one drifts
_K_DRIFT = 0.45          # EMA rate for a gentle drift (slow, ~2-3 turns to settle)
_K_SNAP = 0.78           # EMA rate for a scene-change jump (fast, but still eased, never a hard cut)


def read(st: dict) -> dict:
    """The live steer weights {axis: value} from a loaded state dict, or {}."""
    s = st.get("_steer") if isinstance(st, dict) else None
    return dict(s) if isinstance(s, dict) else {}


def step(world, st: dict, tension, scene_nodes=None) -> dict:
    """Advance the smoothed weights one turn toward their targets. Pure — returns the new {axis: value};
    the caller persists it into state `_steer`. The tone axis's target reuses tone.scale (genre + place
    tone + tension); its baseline is that same computation at neutral tension (what it eases back to)."""
    target = tone.scale(world, tension, scene_nodes)
    baseline = tone.scale(world, 0.2, scene_nodes)          # neutral-tension register (the resting point)
    prev = read(st).get("tone", baseline)
    delta = target - prev
    k = _K_SNAP if abs(delta) >= _SNAP_DELTA else _K_DRIFT
    val = round(max(tone.FLOOR, min(tone.CEIL, prev + k * delta)), 2)
    return {"tone": val}


def compose(weights: dict):
    """Collapse the axis weights into the ONE scalar the server accepts today. One axis → its value.
    (True multi-vector composition is a later phase, gated on the composability harness.)"""
    if not weights:
        return None
    return weights.get("tone")
