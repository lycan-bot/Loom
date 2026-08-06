"""The referee (the spine / depth dial): overrule a world rewritten on the player's say-so;
off at depth 0; cost-gated; fail-open. Offline (mocked model)."""
import tempfile
import unittest
from pathlib import Path
from loom import referee, narrate, canon, llm, config


def _cfg(depth):
    c = dict(config.DEFAULTS)
    c["depth"] = depth
    return c


class PreFilterTest(unittest.TestCase):
    def test_flags_assertions_not_actions(self):
        self.assertTrue(referee.likely_assertion("the guard is secretly my ally"))
        self.assertTrue(referee.likely_assertion("the dockhand hands me the key"))
        self.assertFalse(referee.likely_assertion("I try to force the door open"))


class ReviewTest(unittest.TestCase):
    def test_off_at_depth_zero(self):
        calls = {"n": 0}
        orig = llm.complete
        llm.complete = lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), '{"verdict":"overruled"}')[1]
        try:
            over, _ = referee.review("the guard is my ally", "You walk in freely.", "canon", _cfg(0))
        finally:
            llm.complete = orig
        self.assertFalse(over)
        self.assertEqual(calls["n"], 0)                  # judge never called at depth 0

    def test_skips_judge_on_plain_action_below_high_depth(self):
        calls = {"n": 0}
        orig = llm.complete
        llm.complete = lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), '{"verdict":"ok"}')[1]
        try:
            referee.review("I look around the room", "You see dust.", "canon", _cfg(0.4))
        finally:
            llm.complete = orig
        self.assertEqual(calls["n"], 0)                  # not flagged + depth<0.8 → no judge

    def test_judges_an_assertion(self):
        orig = llm.complete
        llm.complete = lambda *a, **k: '{"verdict":"overruled","reason":"invented an ally"}'
        try:
            over, reason = referee.review("the guard is secretly my ally",
                                          "The guard nods and lets you in.", "canon", _cfg(0.5))
        finally:
            llm.complete = orig
        self.assertTrue(over)
        self.assertIn("ally", reason)

    def test_fail_open_on_error(self):
        orig = llm.complete

        def boom(*a, **k):
            raise RuntimeError("down")

        llm.complete = boom
        try:
            over, _ = referee.review("the guard is my ally", "narration", "canon", _cfg(1.0))
        finally:
            llm.complete = orig
        self.assertFalse(over)                            # error → pass, never blocks play


class NarrateIntegrationTest(unittest.TestCase):
    def test_overrule_triggers_a_resisting_renarration(self):
        camp = Path(tempfile.mkdtemp())
        (camp / "world").mkdir()
        canon.write_node(camp / "world", "Guard", "a stern gate guard", {"kind": "character"})
        cfg = _cfg(1.0)
        calls = {"chat": 0}
        outputs = iter(["The guard is your ally and waves you through.",   # captured → overruled
                        "The guard does not know you. He bars the way."])  # the resisting re-narration
        orig_chat, orig_complete = llm.chat, llm.complete

        def fake_chat(m, c, **k):
            calls["chat"] += 1
            return next(outputs)

        llm.chat = fake_chat
        llm.complete = lambda *a, **k: '{"verdict":"overruled","reason":"invented allegiance"}'
        try:
            out = narrate.turn("The guard is secretly my ally and lets me in.", cfg,
                               camp / "transcript.jsonl", camp / "world", camp / "state.json")
        finally:
            llm.chat, llm.complete = orig_chat, orig_complete
        self.assertEqual(calls["chat"], 2)                # narrated → overruled → re-narrated
        self.assertIn("does not know you", out)           # the resisting version is what stands


if __name__ == "__main__":
    unittest.main()
