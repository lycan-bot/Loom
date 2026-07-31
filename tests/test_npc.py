"""NPC drives → relational threads: characters that want things, held against a vow or
fear, become pending dramatic questions. Model-free, offline."""
import tempfile
import unittest
from pathlib import Path
from loom import npc, canon, threads


def _world():
    d = Path(tempfile.mkdtemp()) / "world"
    d.mkdir(parents=True)
    return d


class MoralTest(unittest.TestCase):
    def test_tension_when_want_and_bound(self):
        m = npc.moral_read("to leave the harbor", "a debt he can't repay")
        self.assertTrue(m.tension)
        self.assertIn("leave the harbor", m.because)
        self.assertIn("debt", m.because)

    def test_no_tension_want_only(self):
        self.assertFalse(npc.moral_read("to rest", "").tension)


class DrivesTest(unittest.TestCase):
    def test_reads_character_wants_only(self):
        w = _world()
        canon.write_node(w, "Mara", "A fisher.",
                         {"kind": "character", "wants": "to find her brother", "bound": "the guild's silence"})
        canon.write_node(w, "Reef", "A place.", {"kind": "place"})            # not a character
        canon.write_node(w, "Sil", "No want.", {"kind": "character"})         # no want
        self.assertEqual([name for name, _, _ in npc.drives(w)], ["Mara"])

    def test_relational_thread_has_character_entity(self):
        w = _world()
        canon.write_node(w, "Mara", "A fisher who knows [[The Reef]].",
                         {"kind": "character", "wants": "to find her brother", "bound": "the guild's silence"})
        rts = npc.relational_threads(w)
        self.assertEqual(len(rts), 1)
        self.assertIn("Mara", rts[0].entities)
        self.assertIn("The Reef", rts[0].entities)
        self.assertIn("find her brother", rts[0].question)

    def test_sync_adds_then_dedups(self):
        w = _world()
        canon.write_node(w, "Mara", "A fisher.", {"kind": "character", "wants": "to find her brother"})
        thp = w.parent / "threads.json"
        self.assertEqual(len(npc.sync(w, thp)), 1)
        self.assertEqual(npc.sync(w, thp), [])                                # idempotent
        self.assertEqual(len(threads.load(thp)), 1)


if __name__ == "__main__":
    unittest.main()
