"""The wordiness dial: each level shapes the narrator's prompt AND caps its tokens. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import length, narrate, canon, llm, config


class LengthLevelsTest(unittest.TestCase):
    def test_levels_shape_prompt_and_cap(self):
        self.assertIn("1-2 tight sentences", length.clause("terse"))
        self.assertIn("LENGTH", length.clause("brief"))
        self.assertEqual(length.max_tokens("terse", 700), 220)      # a loose backstop, not a tight clamp
        self.assertEqual(length.max_tokens("lavish", 700), 900)

    def test_unknown_level_falls_back_to_default(self):
        self.assertEqual(length.normalize("bogus"), "vivid")
        self.assertEqual(length.max_tokens(None, 700), length.max_tokens("vivid", 700))

    def test_trim_clean_cuts_a_clipped_tail(self):
        # a cap-clipped fragment is trimmed back to the last complete sentence
        clipped = "The lock gives with a groan. The room beyond is dark. To your right,"
        self.assertEqual(length.trim(clipped), "The lock gives with a groan. The room beyond is dark.")
        # a naturally-ended narration is left untouched
        whole = 'She nods. "Go, then." The door closes.'
        self.assertEqual(length.trim(whole), whole)


class LengthInNarrateTest(unittest.TestCase):
    def test_narrate_applies_directive_and_cap(self):
        camp = Path(tempfile.mkdtemp())
        (camp / "world").mkdir()
        canon.write_node(camp / "world", "Room", "a plain room")
        cfg = dict(config.DEFAULTS); cfg["length"] = "terse"
        cap = {}
        orig = llm.chat
        llm.chat = lambda m, c, max_tokens=None, **k: (cap.__setitem__("sys", m[0]["content"]),
                                                       cap.__setitem__("mt", max_tokens), "ok.")[1]
        try:
            narrate.turn("I look around.", cfg, camp / "t.jsonl", camp / "world", camp / "state.json")
        finally:
            llm.chat = orig
        self.assertIn("tight sentences", cap["sys"])          # the directive reached the prompt
        self.assertEqual(cap["mt"], 220)                      # and the loose backstop cap was applied


if __name__ == "__main__":
    unittest.main()
