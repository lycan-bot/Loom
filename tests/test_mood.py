"""NPC mood (NPC-agency R3): a felt mood COMPOSED at read time from blessed signals — disposition
tenor + reputation gravity + agenda drive — never a stored feeling. Offline, deterministic."""
import unittest
from loom import mood


class MoodTest(unittest.TestCase):
    def test_tenor_from_disposition(self):
        self.assertIn("warm toward you", mood.label("warm and fond", 0, ""))
        self.assertIn("cool toward you", mood.label("cold, wary", 0, ""))
        self.assertEqual(mood.label("focused on the relic", 0, ""), "")     # neutral, no other signal

    def test_gravity_from_standing(self):
        self.assertIn("buoyed", mood.label("", 3, ""))
        self.assertIn("beleaguered", mood.label("", -2, ""))
        self.assertEqual(mood.label("", 1, ""), "")                         # mild standing → no gravity

    def test_drive_from_pursuit_status(self):
        self.assertIn("keyed-up", mood.label("", 0, "at a head — ready to move on it"))
        self.assertIn("at ease", mood.label("", 0, "reached — the moment has passed"))
        self.assertIn("holding something back", mood.label("", 0, "a private wish, not yet stirring"))

    def test_composes_all_three(self):
        lab = mood.label("warm and fond", 3, "at a head — ready")
        self.assertIn("warm toward you", lab)
        self.assertIn("buoyed", lab)
        self.assertIn("keyed-up", lab)

    def test_clause_is_rung_gated(self):
        self.assertEqual(mood.clause("Wren", "warm and fond", 2, "at a head", 0.0), "")   # walk-on → silent
        cl = mood.clause("Wren", "warm and fond", 2, "at a head", 1.0)
        self.assertIn("Wren feels", cl)
        self.assertIn("warm toward you", cl)

    def test_bad_standing_is_zero_not_crash(self):
        self.assertEqual(mood.read("warm", None, "")["gravity"], "")
        self.assertEqual(mood.read("warm", "x", "")["gravity"], "")


if __name__ == "__main__":
    unittest.main()
