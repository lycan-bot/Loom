"""The retrieval-miss instrument (ablation.py): log a canon entity the player NAMED that retrieval didn't
surface, aggregate per-entity, and flag the embeddings kill-criterion (missed twice). Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import ablation, canon


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class AblationTest(unittest.TestCase):
    def _world(self, camp):
        canon.write_node(camp / "world", "Wren", "a cadet", {"kind": "character"})
        canon.write_node(camp / "world", "Vault", "a locked vault", {"kind": "place"})
        return camp / "world"

    def test_named_but_not_retrieved_is_logged(self):
        camp = _camp(); w = self._world(camp); sp = camp / "state.json"
        missed = ablation.record(sp, "I ask Wren about the plan", set(), w)   # named Wren; nothing retrieved
        self.assertIn("Wren", missed)
        self.assertEqual(ablation.report(sp)["miss_turns"], 1)

    def test_named_and_retrieved_is_not_a_miss(self):
        camp = _camp(); w = self._world(camp); sp = camp / "state.json"
        self.assertEqual(ablation.record(sp, "I ask Wren", {"Wren"}, w), [])   # retrieval covered it
        self.assertEqual(ablation.entries(sp), [])                             # nothing logged

    def test_no_named_entities_is_silent(self):
        camp = _camp(); w = self._world(camp); sp = camp / "state.json"
        self.assertEqual(ablation.record(sp, "I wander, thinking of nothing", set(), w), [])

    def test_report_flags_the_kill_criterion_at_two(self):
        camp = _camp(); w = self._world(camp); sp = camp / "state.json"
        ablation.record(sp, "Wren?", set(), w)
        self.assertFalse(ablation.report(sp)["kill_criterion_met"])            # one miss → not yet
        ablation.record(sp, "where is Wren", set(), w)
        r = ablation.report(sp)
        self.assertEqual(r["by_entity"]["Wren"], 2)
        self.assertTrue(r["kill_criterion_met"])                              # missed 2× → evidence
        self.assertIn("Wren", r["repeated_misses"])

    def test_retry_of_the_same_turn_is_idempotent(self):
        # red-team: a Retry (undo-then-replay of the same input) must NOT double-count and falsely trip the criterion
        camp = _camp(); w = self._world(camp); sp = camp / "state.json"
        ablation.record(sp, "Wren?", set(), w, turn=5)
        ablation.record(sp, "Wren?", set(), w, turn=5)          # the retry — same turn
        r = ablation.report(sp)
        self.assertEqual(r["miss_turns"], 1)                    # one row, not two
        self.assertFalse(r["kill_criterion_met"])               # not spuriously tripped by a retry
        ablation.record(sp, "Wren?", set(), w, turn=6)          # a genuinely new turn does add a row
        self.assertEqual(ablation.report(sp)["miss_turns"], 2)

    def test_log_is_capped(self):
        camp = _camp(); w = self._world(camp); sp = camp / "state.json"
        for _ in range(ablation._CAP + 25):
            ablation.record(sp, "Wren?", set(), w)
        self.assertLessEqual(len(ablation.entries(sp)), ablation._CAP)        # bounded, never grows forever


if __name__ == "__main__":
    unittest.main()
