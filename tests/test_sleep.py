"""The world lives between sessions: sleep advances clocks along the world's OWN pending logic,
proposes a 'while you were away' recap (propose-only, blessable), and that recap greets the
player once on return. Depth-gated — a mirror world doesn't move. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import sleep, threads, canon, state, narrate, llm, config
from loom.threads import Thread


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class AdvanceTest(unittest.TestCase):
    def test_mirror_world_does_not_move(self):
        camp = _camp()
        threads.save(camp / "threads.json", [Thread("s", "a storm nears", kind="clock", status="ripening", clock=2)])
        cfg = dict(config.DEFAULTS); cfg["depth"] = 0.0
        r = sleep.advance(cfg, camp / "world", camp / "threads.json")
        self.assertEqual(r["beats"], 0)
        self.assertEqual(r["due"], [])
        self.assertEqual(r["recap"], "")
        self.assertEqual(r["threads"][0].clock, 2)          # the clock did NOT tick — world paused

    def test_clock_fires_and_recaps(self):
        camp = _camp()
        canon.write_node(camp / "world", "Harbor", "a fishing harbor on a cold coast", {"kind": "lore"})
        threads.save(camp / "threads.json", [Thread("storm", "a storm is coming in off the sea",
                                                    kind="clock", status="ripening", clock=2)])
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0; cfg["sleep_beats"] = 4
        orig = llm.complete
        llm.complete = lambda *a, **k: '{"recap":"The storm made landfall; the boats were hauled up the shingle.","resolved":[]}'
        try:
            r = sleep.advance(cfg, camp / "world", camp / "threads.json")
        finally:
            llm.complete = orig
        self.assertIn("storm", r["due"])                    # the clock came due while away
        self.assertIn("landfall", r["recap"])

    def test_ripe_question_thread_is_not_surfaced(self):
        # a player-facing beat that happens to be ripe must NOT be spent by sleep
        camp = _camp()
        threads.save(camp / "threads.json", [Thread("q", "will she confront her brother?",
                                                    kind="question", status="ready", readiness=0.9)])
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0
        r = sleep.advance(cfg, camp / "world", camp / "threads.json")
        self.assertEqual(r["due"], [])                      # only clocks move the world in sleep
        self.assertEqual(r["recap"], "")

    def test_offline_failure_is_soft(self):
        camp = _camp()
        threads.save(camp / "threads.json", [Thread("storm", "a storm", kind="clock", status="ready", clock=0)])
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0
        orig = llm.complete
        def boom(*a, **k):
            raise RuntimeError("server down")
        llm.complete = boom
        try:
            r = sleep.advance(cfg, camp / "world", camp / "threads.json")
        finally:
            llm.complete = orig
        self.assertEqual(r["recap"], "")                    # fail-soft: no recap, no crash


class ApplyTest(unittest.TestCase):
    def test_bless_resolves_clock_and_stashes_recap(self):
        camp = _camp()
        th = [Thread("storm", "a storm", kind="clock", status="ready", clock=0)]
        report = {"beats": 4, "due": ["storm"], "recap": "The storm hit.", "resolved": [], "threads": th}
        sleep.apply(report, camp / "threads.json", camp / "state.json", approve=lambda *a: True)
        self.assertEqual(threads.load(camp / "threads.json")[0].status, "resolved")
        self.assertEqual(state.load(camp / "state.json")["_recap"], "The storm hit.")

    def test_decline_writes_nothing(self):
        camp = _camp()
        th = [Thread("storm", "a storm", kind="clock", status="ready", clock=0)]
        report = {"beats": 4, "due": ["storm"], "recap": "The storm hit.", "resolved": [], "threads": th}
        sleep.apply(report, camp / "threads.json", camp / "state.json", approve=lambda *a: False)
        self.assertIsNone(state.load(camp / "state.json").get("_recap"))
        self.assertFalse((camp / "threads.json").exists())  # nothing persisted — the world un-moved

    def test_empty_recap_is_a_noop(self):
        camp = _camp()
        report = {"beats": 4, "due": ["storm"], "recap": "", "resolved": [], "threads": []}
        out = sleep.apply(report, camp / "threads.json", camp / "state.json", approve=lambda *a: True)
        self.assertEqual(out["recap"], "")


class NarrateRecapTest(unittest.TestCase):
    def test_recap_greets_once_then_clears(self):
        camp = _camp()
        canon.write_node(camp / "world", "Room", "a plain room")
        state.save(camp / "state.json", {"_recap": "The storm passed in the night."})
        cfg = dict(config.DEFAULTS)
        cap = {}
        orig = llm.chat
        llm.chat = lambda m, c, **k: (cap.__setitem__("sys", m[0]["content"]), "You wake.")[1]
        try:
            narrate.turn("I wake.", cfg, camp / "transcript.jsonl", camp / "world", camp / "state.json")
        finally:
            llm.chat = orig
        self.assertIn("storm passed", cap["sys"])                        # the recap reached the narrator
        self.assertIsNone(state.load(camp / "state.json").get("_recap"))  # and cleared after one turn


if __name__ == "__main__":
    unittest.main()
