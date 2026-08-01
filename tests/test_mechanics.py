"""The optional dice layer: an impartial d20 injected only when mechanics are on. Offline."""
import random
import tempfile
import unittest
from pathlib import Path
from loom import mechanics, narrate, canon, llm, config


class MechanicsTest(unittest.TestCase):
    def test_roll_in_range(self):
        self.assertTrue(1 <= mechanics.roll(random.Random(1)) <= 20)

    def test_bands(self):
        self.assertEqual(mechanics.band(1)[0], "critical failure")
        self.assertEqual(mechanics.band(20)[0], "critical success")
        self.assertEqual(mechanics.band(12)[0], "success")

    def test_clause_carries_the_roll(self):
        c = mechanics.clause(7)
        self.assertIn("d20 = 7", c)
        self.assertIn("MECHANICS", c)


class NarrateMechanicsTest(unittest.TestCase):
    def _run(self, mech):
        d = Path(tempfile.mkdtemp())
        (d / "world").mkdir()
        canon.write_node(d / "world", "Room", "a plain room with a heavy door")
        cfg = dict(config.DEFAULTS)
        cfg["mechanics"] = mech
        cap = {}
        orig = llm.chat
        llm.chat = lambda messages, c, **k: (cap.__setitem__("sys", messages[0]["content"]), "You try.")[1]
        try:
            narrate.turn("I try to force the door.", cfg,
                         d / "transcript.jsonl", d / "world", d / "state.json")
        finally:
            llm.chat = orig
        return cap["sys"]

    def test_off_injects_nothing(self):
        self.assertNotIn("MECHANICS", self._run(False))

    def test_on_injects_the_roll(self):
        self.assertIn("MECHANICS", self._run(True))


if __name__ == "__main__":
    unittest.main()
