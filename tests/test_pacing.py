"""The governor of restraint: HOLD by default, OFFER only on a genuine stall, and never
while tension is still high (tension now comes from the homeostat). Pure, offline."""
import unittest
from loom import pacing


def T(*pairs):
    return [{"role": r, "text": t} for r, t in pairs]


class PacingTest(unittest.TestCase):
    def test_engaged_player_holds(self):
        log = T(("player", "I ask the dockhand about his family and listen closely."))
        self.assertEqual(pacing.read(log, 0.1).directive, "hold")

    def test_calm_but_engaged_is_not_boredom(self):
        log = T(("player", "I sit and sketch the moored boats, noting each name."),
                ("player", "I add the lighthouse to the corner of the page, dark and thin."))
        self.assertEqual(pacing.read(log, 0.1).directive, "hold")

    def test_two_passive_beats_low_tension_offers(self):
        self.assertEqual(pacing.read(T(("player", "hmm"), ("player", "look around")), 0.1).directive, "offer")

    def test_single_passive_beat_holds(self):
        log = T(("player", "I search the tide-line carefully for anything the sea left behind."),
                ("player", "wait"))
        self.assertEqual(pacing.read(log, 0.1).directive, "hold")

    def test_high_tension_suppresses_offer(self):
        # stalled, but tension is still high → let it breathe, don't inject
        self.assertEqual(pacing.read(T(("player", "..."), ("player", "wait")), 0.8).directive, "hold")

    def test_offer_clause_only_on_offer(self):
        self.assertEqual(pacing.prompt_clause(pacing.Pacing("hold", 0.3, 0.2, "")), "")
        self.assertIn("gentle", pacing.prompt_clause(pacing.Pacing("offer", 0.2, 0.1, "")))


class TensionHomeostatTest(unittest.TestCase):
    def test_decays_toward_baseline_on_calm(self):
        t = pacing.update_tension(0.8, "The harbor is quiet and still, a soft, gentle hush.",
                                  baseline=0.15, decay=0.7)
        self.assertLess(t, 0.8)
        self.assertGreater(t, 0.15)

    def test_rises_on_intensity(self):
        t = pacing.update_tension(0.2, "Blood, a scream, the knife — you run from the attack.",
                                  baseline=0.15, decay=0.7)
        self.assertGreater(t, 0.2)

    def test_settles_to_baseline_not_zero(self):
        t = 0.9
        for _ in range(30):
            t = pacing.update_tension(t, "a calm, quiet, still moment", baseline=0.15, decay=0.7)
        self.assertAlmostEqual(t, 0.15, places=2)


if __name__ == "__main__":
    unittest.main()
