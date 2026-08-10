"""Incremental consolidation (only the turns since a watermark, so the prompt stays bounded) +
automated consolidation on a turn cadence — diode-gated: canon nodes stay queued unless opted in.
Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import consolidate, narrate, canon, state, transcript, llm, config


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class IncrementalTest(unittest.TestCase):
    def test_watermark_slices_to_new_turns_only(self):
        camp = _camp()
        transcript.append(camp / "t.jsonl", "player", "a")
        transcript.append(camp / "t.jsonl", "narrator", "b")
        new, total = consolidate.unconsolidated(camp / "t.jsonl", camp / "state.json")
        self.assertEqual([e["text"] for e in new], ["a", "b"])
        self.assertEqual(total, 2)
        consolidate.mark_consolidated(camp / "state.json", 2)
        transcript.append(camp / "t.jsonl", "player", "c")
        transcript.append(camp / "t.jsonl", "narrator", "d")
        new2, total2 = consolidate.unconsolidated(camp / "t.jsonl", camp / "state.json")
        self.assertEqual([e["text"] for e in new2], ["c", "d"])       # only the un-consolidated turns
        self.assertEqual(total2, 4)


class AutoTest(unittest.TestCase):
    def _proposal(self):
        return ('{"nodes":[{"name":"A New Place","kind":"place","body":"x"}],"state":{"mood":"warm"},'
                '"threads_new":[],"threads_resolved":[],'
                '"character_updates":[{"name":"Wren","disposition":"warmer"}],"reputation":[]}')

    def test_auto_gates_canon_but_applies_structured(self):
        camp = _camp()
        canon.write_node(camp / "world", "Wren", "a cadet", {"kind": "character"})
        transcript.append(camp / "t.jsonl", "player", "I talk to Wren")
        transcript.append(camp / "t.jsonl", "narrator", "Wren warms to you")
        orig = llm.complete
        llm.complete = lambda *a, **k: self._proposal()
        try:
            rep = consolidate.auto(dict(config.DEFAULTS), camp / "t.jsonl", camp / "world", camp / "state.json",
                                   apply_canon=False)
        finally:
            llm.complete = orig
        self.assertIsNone(canon.read_node(camp / "world", "A New Place"))   # canon node GATED (queued)
        self.assertIn("A New Place", rep["pending_nodes"])
        self.assertEqual(state.load(camp / "state.json").get("mood"), "warm")   # structured fact applied
        self.assertEqual(canon.read_node(camp / "world", "Wren")["frontmatter"].get("disposition"), "warmer")
        self.assertEqual(state.load(camp / "state.json").get("_consolidated"), 2)   # watermark advanced

    def test_auto_writes_canon_when_opted_in(self):
        camp = _camp()
        transcript.append(camp / "t.jsonl", "player", "x")
        transcript.append(camp / "t.jsonl", "narrator", "y")
        orig = llm.complete
        llm.complete = lambda *a, **k: '{"nodes":[{"name":"A New Place","kind":"place","body":"x"}],"state":{},"threads_new":[],"threads_resolved":[],"character_updates":[],"reputation":[]}'
        try:
            consolidate.auto(dict(config.DEFAULTS), camp / "t.jsonl", camp / "world", camp / "state.json",
                             apply_canon=True)
        finally:
            llm.complete = orig
        self.assertIsNotNone(canon.read_node(camp / "world", "A New Place"))   # written when opted in

    def test_narrate_auto_consolidates_on_cadence(self):
        camp = _camp()
        canon.write_node(camp / "world", "Room", "a room")
        state.save(camp / "state.json", {})
        cfg = dict(config.DEFAULTS)
        cfg.update(auto_consolidate=True, consolidate_every=2, scene_memory=False)
        calls = []
        oc, ocmp = llm.chat, llm.complete
        llm.chat = lambda *a, **k: "A beat."
        llm.complete = lambda *a, **k: (calls.append(1), '{"nodes":[],"state":{"x":"y"},"threads_new":[],"threads_resolved":[],"character_updates":[],"reputation":[]}')[1]
        try:
            narrate.turn("t1", cfg, camp / "t.jsonl", camp / "world", camp / "state.json")   # _cturn → 1
            self.assertEqual(len(calls), 0)
            narrate.turn("t2", cfg, camp / "t.jsonl", camp / "world", camp / "state.json")   # → 2 → auto fires
            self.assertEqual(len(calls), 1)
        finally:
            llm.chat, llm.complete = oc, ocmp
        self.assertEqual(state.load(camp / "state.json").get("x"), "y")        # auto-applied a structured fact


if __name__ == "__main__":
    unittest.main()
