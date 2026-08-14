"""Undo: a snapshot before each turn lets the last turn be taken back — restoring the transcript,
threads, and state (tension, location) to exactly their pre-turn bytes. Offline."""
import json
import tempfile
import unittest
from pathlib import Path
from loom import undo, narrate, canon, state, transcript, llm, config, provenance


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


class ConsolidationFloorTest(unittest.TestCase):
    """A turn already folded into canon can't be undone — canon isn't snapshotted, so rolling back
    below the consolidation watermark would tear canon from the ledger (red-team #1/#10)."""

    def test_undo_refuses_below_the_watermark(self):
        camp = _camp()
        tp, sp = camp / "t.jsonl", camp / "state.json"
        transcript.append(tp, "player", "a turn")
        transcript.append(tp, "narrator", "a beat")
        undo.snapshot(tp, sp)                                # snapshot at n_transcript=2
        transcript.append(tp, "player", "another")
        # a consolidation folds the transcript up to entry 3 (past the snapshot's position)
        state.save(sp, {"_consolidated": 3})
        self.assertFalse(undo.undo(tp, sp))                 # refused — the turn is canonized
        self.assertFalse(undo.can_undo(tp, sp))             # and the UI reflects it
        self.assertEqual(len(transcript.read_all(tp)), 3)   # nothing rolled back
        self.assertTrue((camp / "undo.jsonl").read_text(encoding="utf-8").strip())  # stack left intact

    def test_undo_allowed_above_the_watermark(self):
        camp = _camp()
        tp, sp = camp / "t.jsonl", camp / "state.json"
        transcript.append(tp, "player", "old")
        state.save(sp, {"_consolidated": 1})                # everything up to 1 is canon
        transcript.append(tp, "player", "new unconsolidated turn")
        undo.snapshot(tp, sp)                               # snapshot at n_transcript=2 (>= floor 1)
        transcript.append(tp, "narrator", "beat")
        self.assertTrue(undo.can_undo(tp, sp))
        self.assertTrue(undo.undo(tp, sp))                  # allowed — above the floor
        self.assertEqual(len(transcript.read_all(tp)), 2)

    def test_manual_consolidate_then_undo_preserves_provenance(self):
        # red-team #1: a manual consolidate writes facts + advances the watermark past the turn; a
        # following undo must NOT truncate those provenance records back to the stale pre-turn count
        camp = _camp()
        tp, sp = camp / "t.jsonl", camp / "state.json"
        transcript.append(tp, "player", "a turn")
        undo.snapshot(tp, sp)                                # n_transcript=1, n_facts=0 captured here
        transcript.append(tp, "narrator", "a beat")         # the turn's own narration → n_transcript=2
        provenance.log(sp, [{"name": "Mara", "field": "disposition", "old": "cold", "new": "warm",
                             "entry_start": 1, "entry_end": 2}])
        state.save(sp, {"_consolidated": 2})                # the manual fold canonized entries up to 2
        self.assertFalse(undo.undo(tp, sp))                 # refused: snapshot n=1 < watermark 2
        self.assertEqual(len(provenance.entries(sp)), 1)    # the provenance record survives — not erased


if __name__ == "__main__":
    unittest.main()
