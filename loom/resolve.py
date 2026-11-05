"""loom.resolve — the check resolver (D&D-mode S3): the dice math that decides an uncertain action.

A check compares a doer's SKILL against an opposition (another skill, or a static DIFFICULTY that plays the
part of a skill) on a smooth percentile curve: the higher skill gets the lower bar (50 − 11×gap/sum), the
lower skill the inverse, equal skills a coin-flip — a GENTLE lean, so the underdog always has a chance and the
real gulfs live in the MODIFIERS. The doer's ability lends a flat bonus (off the sheet), a physical size
mismatch and a defense that doesn't cover the attack's domain add more (off the bible), and the narrator may
propose a bounded circumstantial modifier — but the number is the dice + the rules, never the model's to grant.
The result bands by the margin: critical failure → critical success.

The diode: the model proposes the FRAME (which skill, how hard, any circumstantial ±); the engine reads the
sheet + the bible, computes the bar, and rolls; the model narrates the band. The sheet is the truth.
"""
from __future__ import annotations
import random
from . import sheet as _sheet, bible

_BASE = 50          # equal skills → a coin flip (no singularity)
_SLOPE = 11         # how much the skill GAP leans the odds (gentle: 78 vs 36 → ~55/45)
_CIRC_CAP = 20      # the most a model-proposed circumstantial modifier may swing a roll
_DEFENSE_MOD = 30   # a defense that COVERS the incoming attack raises the bar this much (a non-covering one is bypassed)

# a static difficulty plays the part of an opposing skill
DIFFICULTY = {"trivial": 10, "easy": 25, "medium": 45, "hard": 65, "deadly": 85}

# the margin (roll − effective threshold) bands the outcome
_BANDS = [(40, "critical success", "an exceptional result, better than they could have hoped"),
          (15, "strong success", "it works well"),
          (0, "success", "it works"),
          (-15, "partial", "it half-works — success at a cost, or a mixed result"),
          (-40, "failure", "it fails — a setback or cost"),
          (-10 ** 9, "critical failure", "it goes badly wrong, with a real complication")]


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError, ArithmeticError):   # ArithmeticError covers int(inf)'s OverflowError
        return 0


def difficulty_skill(name) -> int:
    """A static difficulty plays the part of an opposing skill (trivial 10 … deadly 85; unknown → medium)."""
    return DIFFICULTY.get(str(name or "").strip().lower(), DIFFICULTY["medium"])


def base_threshold(skill, opposing) -> int:
    """The doer's base bar on a d100 (roll ≥ it to succeed), from the smooth ratio: the higher skill gets the
    lower (easier) bar 50 − 11×gap/sum, the lower skill the inverse; equal skills → 50, no singularity."""
    skill, opposing = max(0, _int(skill)), max(0, _int(opposing))
    hi, lo = max(skill, opposing), min(skill, opposing)
    if hi + lo == 0:
        return _BASE
    thr = _BASE - _SLOPE * (hi - lo) / (hi + lo)             # the HIGHER side's easier bar
    return round(thr if skill >= opposing else 100 - thr)   # the doer gets theirs; the lower side the inverse


def band(margin) -> tuple:
    """(label, guide) for a roll's margin over the bar."""
    for cut, label, guide in _BANDS:
        if margin >= cut:
            return label, guide
    return _BANDS[-1][1], _BANDS[-1][2]


def check(doer, skill, difficulty="medium", vs=None, attack_type=None, defense=None,
          circumstantial=0, rng=None) -> dict:
    """Resolve one uncertain action. `doer` is a sheet (or None → a skill-0 actor); `skill` the skill rolled;
    the opposition is `vs` (another sheet, opposed on the SAME skill) or the static `difficulty`. Engine
    modifiers stack onto the bar: the doer's ability bonus (from the sheet); a PHYSICAL size mismatch (from
    the bible, only when it's a physical clash); a defense that COVERS the attack_type (a non-covering one is
    bypassed → no help); and the model's `circumstantial` proposal (clamped ±20). Returns the full breakdown
    + the banded outcome. Deterministic with an injected `rng`."""
    rng = rng or random
    doer_skill = _sheet.skill_level(doer, skill)
    opp_skill = _sheet.skill_level(vs, skill) if vs is not None else difficulty_skill(difficulty)
    bar = base_threshold(doer_skill, opp_skill)

    mod = _sheet.stat_bonus(doer, skill)                                      # the doer's ability (from the sheet)
    if vs is not None and str(attack_type or "").startswith("physical"):     # size matters in a PHYSICAL clash
        mod += bible.size_mod((doer or {}).get("size"), (vs or {}).get("size"))
    if attack_type and defense and bible.covers(defense, attack_type):       # a covering defense makes it HARDER
        mod -= _DEFENSE_MOD                                                   # (a non-covering defense is bypassed)
    mod += max(-_CIRC_CAP, min(_CIRC_CAP, _int(circumstantial)))             # the model's bounded proposal

    eff = max(1, min(100, bar - mod))                                        # a bonus LOWERS the bar
    roll = rng.randint(1, 100)
    margin = roll - eff
    lbl, guide = band(margin)
    return {"skill": skill, "doer_skill": doer_skill, "opp_skill": opp_skill, "base": bar,
            "modifier": mod, "threshold": eff, "roll": roll, "margin": margin,
            "band": lbl, "guide": guide, "success": margin >= 0}
