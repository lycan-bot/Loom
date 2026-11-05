"""The check resolver (D&D-mode S3): the smooth-ratio base + engine modifiers + bands. Offline, deterministic."""
import unittest
from loom import resolve, sheet


class _RNG:
    def __init__(self, r):
        self.r = r

    def randint(self, a, b):
        return self.r


class BaseThresholdTest(unittest.TestCase):
    def test_matches_the_designed_example(self):
        self.assertEqual(resolve.base_threshold(78, 36), 46)   # the higher skill's easier bar
        self.assertEqual(resolve.base_threshold(36, 78), 54)   # the lower skill's inverse
        self.assertEqual(resolve.base_threshold(50, 50), 50)   # equal → coin flip, no singularity

    def test_monotonic_and_gentle(self):
        self.assertLess(resolve.base_threshold(60, 50), 50)          # the higher is favoured (bar < 50)
        self.assertLessEqual(resolve.base_threshold(100, 5), 41)     # even a huge gap is only ~40 (≈61% — gentle)
        self.assertGreater(resolve.base_threshold(100, 5), 35)       # …not a blowout
        # a wider gap monotonically lowers the higher side's bar (no V-shape, no singularity)
        self.assertGreater(resolve.base_threshold(60, 50), resolve.base_threshold(90, 50))


class BandTest(unittest.TestCase):
    def test_bands_by_margin(self):
        self.assertEqual(resolve.band(45)[0], "critical success")
        self.assertEqual(resolve.band(0)[0], "success")
        self.assertEqual(resolve.band(-10)[0], "partial")
        self.assertEqual(resolve.band(-50)[0], "critical failure")


class CheckTest(unittest.TestCase):
    def _fighter(self, name, race="human", size=None, **skills):
        s = sheet.blank(name, race)
        s["skills"].update(skills)
        if size:
            s["size"] = size
        return s

    def test_static_difficulty_and_stat_bonus(self):
        gorm = self._fighter("Gorm", "dragonborn", melee=40)   # Might 6 → +3
        r = resolve.check(gorm, "melee", difficulty="medium", rng=_RNG(50))
        self.assertEqual(r["opp_skill"], 45)                   # medium difficulty = pseudo-skill 45
        self.assertEqual(r["modifier"], 3)                     # Might 6 → +3, no other mods
        self.assertLess(r["threshold"], r["base"])             # the bonus lowered the bar
        self.assertEqual(r["roll"], 50)

    def test_the_shield_does_not_save_the_nerd(self):
        psion = self._fighter("Vex", "human", psionics=60)
        mark = self._fighter("Aldric", "human")
        bypass = resolve.check(psion, "psionics", vs=mark, attack_type="psionic_mental",
                               defense="arcane_barrier", rng=_RNG(50))
        warded = resolve.check(psion, "psionics", vs=mark, attack_type="psionic_mental",
                               defense="mental_ward", rng=_RNG(50))
        self.assertEqual(bypass["modifier"], 0)                       # the arcane barrier gives the defender NOTHING
        self.assertEqual(warded["modifier"], -resolve._DEFENSE_MOD)   # the ward raises the bar
        self.assertGreater(warded["threshold"], bypass["threshold"])  # harder to land through a ward
        self.assertTrue(bypass["success"]); self.assertFalse(warded["success"])   # 50 lands unshielded, not warded

    def test_the_rat_cannot_fight_the_dragonborn(self):
        rat = self._fighter("Rat", "human", size="tiny", melee=20)
        gorm = self._fighter("Gorm", "dragonborn", size="large", melee=20)
        r = resolve.check(rat, "melee", vs=gorm, attack_type="physical_melee", rng=_RNG(50))
        self.assertLessEqual(r["modifier"], -40)               # −45 size crush
        self.assertFalse(r["success"])                          # even a 50 can't land
        back = resolve.check(gorm, "melee", vs=rat, attack_type="physical_melee", rng=_RNG(50))
        self.assertGreaterEqual(back["modifier"], 40)           # +45 size + the Might bonus
        self.assertTrue(back["success"])                        # the dragonborn auto-lands

    def test_size_only_in_a_physical_clash(self):
        # a rat's STEALTH isn't crushed by a dragonborn's size — size is a physical-clash modifier only
        rat = self._fighter("Rat", "human", size="tiny", stealth=30)
        gorm = self._fighter("Gorm", "dragonborn", size="large")
        r = resolve.check(rat, "stealth", vs=gorm, attack_type="psionic_mental", rng=_RNG(50))
        self.assertEqual(r["modifier"], 0)                      # non-physical → no size mod

    def test_circumstantial_is_capped(self):
        gorm = self._fighter("Gorm", "human", melee=40)
        self.assertEqual(resolve.check(gorm, "melee", circumstantial=999, rng=_RNG(50))["modifier"],
                         resolve._CIRC_CAP)                     # the model can't hand itself +999
        self.assertEqual(resolve.check(gorm, "melee", circumstantial=-999, rng=_RNG(50))["modifier"],
                         -resolve._CIRC_CAP)

    def test_no_sheet_actor_is_skill_zero(self):
        r = resolve.check(None, "melee", difficulty="easy", rng=_RNG(50))
        self.assertEqual((r["doer_skill"], r["modifier"]), (0, 0))

    def test_infinity_circumstantial_fails_soft(self):
        # red-team fix: the model's one number — a crafted Infinity must coerce to 0, not crash the resolver
        gorm = self._fighter("Gorm", "human", melee=40)
        self.assertEqual(resolve.check(gorm, "melee", circumstantial=float("inf"), rng=_RNG(50))["modifier"], 0)
        self.assertEqual(resolve.check(gorm, "melee", circumstantial=float("-inf"), rng=_RNG(50))["modifier"], 0)


if __name__ == "__main__":
    unittest.main()
