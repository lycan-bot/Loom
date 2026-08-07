"""Undo: a snapshot before each turn lets the last turn be taken back — restoring the transcript,
threads, and state (tension, location) to exactly their pre-turn bytes. Offline."""
import json
import tempfile
import unittest
from pathlib import Path
from loom import undo, narrate, canon, state, transcript, llm, config


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class UndoTest(unittest.TestCase):
    def test_undo_reverts_a_full_turn(self):
        camp = _camp()
        canon.write_node(camp / "world", "Hall", "a long hall", {"kind": "place"})
        state.save(camp / "state.json", {"_tension": 0.5, "hero": "awake"})
        orig = llm.chat
        llm.chat = lambda *a, **k: "The hall echoes with sudden danger and blood."
        try:
            narrate.turn("I enter the Hall.", dict(config.DEFAULTS), camp / "t.jsonl", camp / "world", camp / "state.json")
        finally:
            llm.chat = orig
        self.assertEqual(len(transcript.read_all(camp / "t.jsonl")), 2)          # player + narrator committed
        self.assertTrue(undo.undo(camp / "t.jsonl", camp / "state.json"))
        self.assertEqual(transcript.read_all(camp / "t.jsonl"), [])              # both lines gone
        self.assertEqual(state.load(camp / "state.json"), {"_tension": 0.5, "hero": "awake"})  # tension/location reverted

    def test_undo_with_nothing_to_undo(self):
        camp = _camp()
        self.assertFalse(undo.undo(camp / "t.jsonl", camp / "state.json"))

    def test_can_undo_tracks_the_stack(self):
        camp = _camp()
        self.assertFalse(undo.can_undo(camp / "t.jsonl"))
        undo.snapshot(camp / "t.jsonl", camp / "state.json")
        self.assertTrue(undo.can_undo(camp / "t.jsonl"))
        undo.undo(camp / "t.jsonl", camp / "state.json")
        self.assertFalse(undo.can_undo(camp / "t.jsonl"))

    def test_stack_is_capped(self):
        camp = _camp()
        for i in range(undo._CAP + 5):
            state.save(camp / "state.json", {"n": i})
            undo.snapshot(camp / "t.jsonl", camp / "state.json")
        kept = [ln for ln in (camp / "undo.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual(len(kept), undo._CAP)

    def test_corrupt_snapshot_line_is_skipped(self):
        camp = _camp()
        (camp / "undo.jsonl").write_text(
            "not json\n" + json.dumps({"n_transcript": 0, "threads": None, "state": None}) + "\n", encoding="utf-8")
        self.assertTrue(undo.undo(camp / "t.jsonl", camp / "state.json"))    # newest (valid) pops first
        self.assertFalse(undo.undo(camp / "t.jsonl", camp / "state.json"))   # only the corrupt line left → skipped


if __name__ == "__main__":
    unittest.main()
