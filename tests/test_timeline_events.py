"""Two-clock timeline completion: the timeline is no longer play-only — the world's OWN beats (a
world round, a night of sleep) are recorded too, so 'when did the world move?' resolves. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import sleep, worldturn, episodic, state, transcript, config, canon


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class SleepEventsTest(unittest.TestCase):
    def test_blessed_recap_becomes_a_timeline_beat(self):
        camp = _camp()
        sp = camp / "state.json"
        transcript.append(camp / "transcript.jsonl", "player", "goodnight")
        report = {"threads": [], "recap": "The storm made landfall; the boats were hauled up the shingle.",
                  "due": [], "resolved": []}
        sleep.apply(report, camp / "threads.json", sp, approve=lambda *a: True)
        evs = [e for e in episodic.entries(sp) if e.get("source") == "sleep"]
        self.assertEqual(len(evs), 1)
        self.assertIn("landfall", evs[0]["what"])
        self.assertEqual(evs[0].get("when"), "while you were away")

    def test_unblessed_sleep_records_nothing(self):
        camp = _camp()
        sp = camp / "state.json"
        report = {"threads": [], "recap": "something", "due": [], "resolved": []}
        sleep.apply(report, camp / "threads.json", sp, approve=lambda *a: False)   # gate says no
        self.assertEqual(episodic.entries(sp), [])                                  # nothing blessed → nothing logged


class WorldRoundEventsTest(unittest.TestCase):
    def test_world_round_beats_recorded(self):
        camp = _camp()
        sp = camp / "state.json"
        transcript.append(camp / "transcript.jsonl", "player", "hi")
        cfg = dict(config.DEFAULTS); cfg["world_rounds"] = True; cfg["depth"] = 1.0; cfg["world_cadence"] = 1
        orig = worldturn.run
        worldturn.run = lambda *a, **k: {"turns": [{"where": "The Docks", "who": "Wren",
                                                    "beat": "checks the moorings against the tide"}], "pending": True}
        try:
            worldturn.maybe_round(cfg, camp / "world", sp)
        finally:
            worldturn.run = orig
        evs = [e for e in episodic.entries(sp) if e.get("source") == "world"]
        self.assertEqual(len(evs), 1)
        self.assertIn("moorings", evs[0]["what"])
        self.assertIn("Wren", evs[0]["what"])                     # the actor is named in the beat

    def test_world_round_off_records_nothing(self):
        camp = _camp()
        sp = camp / "state.json"
        cfg = dict(config.DEFAULTS); cfg["world_rounds"] = False
        worldturn.maybe_round(cfg, camp / "world", sp)
        self.assertEqual(episodic.entries(sp), [])


if __name__ == "__main__":
    unittest.main()
