"""Continue (⤵) extends the last narration in place without a new player action; Retry (↻) undoes
the last turn and re-rolls it fresh. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import narrate, canon, state, transcript, llm, config


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class ContinueTest(unittest.TestCase):
    def test_resume_extends_the_last_narration_as_a_paragraph(self):
        camp = _camp()
        canon.write_node(camp / "world", "Room", "a room")
        state.save(camp / "state.json", {})
        orig = llm.chat
        llm.chat = lambda *a, **k: "A quiet room."
        try:
            narrate.turn("I look.", dict(config.DEFAULTS), camp / "t.jsonl", camp / "world", camp / "state.json")
            llm.chat = lambda *a, **k: "The dust settles."
            merged = narrate.resume(dict(config.DEFAULTS), camp / "t.jsonl", camp / "world", camp / "state.json")
        finally:
            llm.chat = orig
        self.assertEqual(merged, "A quiet room.\n\nThe dust settles.")           # clean end → new paragraph
        tr = transcript.read_all(camp / "t.jsonl")
        self.assertEqual(len(tr), 2)                                             # still one player + one narrator
        self.assertEqual(tr[1]["text"], "A quiet room.\n\nThe dust settles.")

    def test_resume_splices_a_cut_off_beat(self):
        camp = _camp()
        canon.write_node(camp / "world", "Room", "a room")
        transcript.append(camp / "t.jsonl", "player", "I look.")
        transcript.append(camp / "t.jsonl", "narrator", "The door creaks open and")   # truncated, no terminator
        orig = llm.chat
        llm.chat = lambda *a, **k: "a cold wind spills in."
        try:
            merged = narrate.resume(dict(config.DEFAULTS), camp / "t.jsonl", camp / "world", camp / "state.json")
        finally:
            llm.chat = orig
        self.assertEqual(merged, "The door creaks open and a cold wind spills in.")    # mid-sentence → space splice

    def test_resume_with_nothing_to_continue(self):
        camp = _camp()
        self.assertEqual(narrate.resume(dict(config.DEFAULTS), camp / "t.jsonl", camp / "world", camp / "state.json"), "")


class RetryTest(unittest.TestCase):
    def test_retry_rerolls_the_last_turn(self):
        camp = _camp()
        canon.write_node(camp / "world", "Gate", "a gate", {"kind": "place"})
        state.save(camp / "state.json", {"_tension": 0.4})
        orig = llm.chat
        llm.chat = lambda *a, **k: "First telling."
        try:
            narrate.turn("I approach the Gate.", dict(config.DEFAULTS), camp / "t.jsonl", camp / "world", camp / "state.json")
            llm.chat = lambda *a, **k: "A different telling."
            new = narrate.retry(dict(config.DEFAULTS), camp / "t.jsonl", camp / "world", camp / "state.json")
        finally:
            llm.chat = orig
        self.assertEqual(new, "A different telling.")
        tr = transcript.read_all(camp / "t.jsonl")
        self.assertEqual([e["role"] for e in tr], ["player", "narrator"])        # exactly one turn, re-rolled
        self.assertEqual(tr[0]["text"], "I approach the Gate.")                   # same input
        self.assertEqual(tr[1]["text"], "A different telling.")                   # fresh narration

    def test_retry_with_nothing(self):
        camp = _camp()
        self.assertIsNone(narrate.retry(dict(config.DEFAULTS), camp / "t.jsonl", camp / "world", camp / "state.json"))


if __name__ == "__main__":
    unittest.main()
