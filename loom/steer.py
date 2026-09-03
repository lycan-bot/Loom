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
import re
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


# --- the runtime shatter clamp (LIVING_WORLD_VECTORS §5): the FLOOR/CEIL band bounds the scale, but a
# generation can still collapse WITHIN it (and composed axes shatter below their solo sweet spots). No
# automated shatter detector existed; this is the "wired as a runtime clamp" the doc calls for. ---

_MIN_TOKENS = 12         # too short to judge — a brief line isn't a loop
_UNIQUE_FLOOR = 0.35     # unique/total below this over real length = a collapsed vocabulary (normal prose ~0.6+)
_RUN_LIMIT = 5           # one token repeated this many times in a row
_RUN_UNIQUE_CEIL = 0.5   # …but only counts as shatter when the vocabulary is ALSO degenerate (else it's dramatic


def shattered(text) -> bool:
    """A deterministic tell that a control-vector scale collapsed the generation into a degenerate
    repetition loop (STEERING.md's '11 11 1 1'): a tiny vocabulary over enough length, or a long single-token
    run IN A TEXT WHOSE VOCABULARY IS ALSO COLLAPSING. Tuned to fire ONLY on real degeneration — legitimate
    dramatic repetition ('Knock. Knock. Knock. Knock. Knock. The sound came from behind the door.') keeps a
    rich vocabulary, so the run alone never fires."""
    toks = re.findall(r"[^\W_]+", str(text or "").lower())
    if len(toks) < _MIN_TOKENS:
        return False
    ratio = len(set(toks)) / len(toks)
    if ratio < _UNIQUE_FLOOR:                            # collapsed vocabulary over real length
        return True
    if ratio >= _RUN_UNIQUE_CEIL:                        # rich vocabulary → a run is dramatic prose, not a loop
        return False
    run, prev = 1, None
    for t in toks:
        run = run + 1 if t == prev else 1
        if run >= _RUN_LIMIT:                            # a long run AND a middling-to-collapsing vocabulary
            return True
        prev = t
    return False


def declamp(scale):
    """Ease a control-vector scale toward neutral (halve its magnitude) — the runtime response to a
    detected shatter, so the register survives but the degenerate attractor is escaped. None on a bad type."""
    try:
        return round(float(scale) * 0.5, 2)
    except (TypeError, ValueError):
        return None
