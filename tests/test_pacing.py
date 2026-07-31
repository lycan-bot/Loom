"""The governor of restraint: HOLD by default, OFFER only on a genuine stall, and never
while tension is still high. Calm is not boredom. Pure, offline."""
import unittest
from loom import pacing


def T(*pairs):
    return [{"role": r, "text": t} for r, t in pairs]


class PacingTest(unittest.TestCase):
    def test_engaged_player_holds(self):
        log = T(("player", "I ask the dockhand about his family and listen closely."),
                ("narrator", "He softens, and speaks of a daughter lost to the sea."))
        self.assertEqual(pacing.read(log).directive, "hold")

    def test_calm_but_engaged_is_not_boredom(self):
        # quiet, substantive actions must NOT trigger a hook — calm != boredom
        log = T(("player", "I sit and sketch the moored boats, noting each name."),
                ("narrator", "The Gull's Mercy, the Two Sisters, a nameless skiff."),
                ("player", "I add the lighthouse to the corner of the page, dark and thin."))
        self.assertEqual(pacing.read(log).directive, "hold")

    def test_two_passive_beats_low_tension_offers(self):
        log = T(("narrator", "The rain settles into a soft, quiet hush over the pier."),
                ("player", "hmm"),
                ("narrator", "The water laps gently at the pilings."),
                ("player", "look around"))
        self.assertEqual(pacing.read(log).directive, "offer")

    def test_single_passive_beat_holds(self):
        log = T(("player", "I search the tide-line carefully for anything the sea left behind."),
                ("narrator", "Kelp, a broken oar, a child's shoe."),
                ("player", "wait"))
        self.assertEqual(pacing.read(log).directive, "hold")

    def test_stall_but_high_tension_holds(self):
        # after an intense beat, a passive player gets breathing room, not more drama
        log = T(("narrator", "The knife flashes — blood, a scream, you run as the attack lands."),
                ("player", "..."),
                ("narrator", "You flee, heart pounding, the chase close behind, fear cold in your chest."),
                ("player", "wait"))
        p = pacing.read(log)
        self.assertEqual(p.directive, "hold")
        self.assertGreater(p.tension, 0.45)

    def test_offer_clause_only_on_offer(self):
        self.assertEqual(pacing.prompt_clause(pacing.Pacing("hold", 0.3, 0.2, "")), "")
        self.assertIn("gentle", pacing.prompt_clause(pacing.Pacing("offer", 0.2, 0.1, "")))


if __name__ == "__main__":
    unittest.main()
