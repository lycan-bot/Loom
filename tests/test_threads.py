"""The plan above canon: threads ripen with proximity + time, activate only when the
player is near their subject, and clocks tick down. Pure, offline."""
import json
import tempfile
import unittest
from pathlib import Path
from loom import threads
from loom.threads import Thread


class ThreadsTest(unittest.TestCase):
    def test_dormant_activates_only_when_near(self):
        t = Thread("x", "q", entities=["The Lighthouse"])
        newly = threads.advance([t], ["The Tavern"])          # far → stays dormant
        self.assertEqual(t.status, "dormant")
        self.assertEqual(newly, [])
        newly = threads.advance([t], ["The Lighthouse"])      # near → seeded + reported
        self.assertEqual(t.status, "seeded")
        self.assertIn(t, newly)

    def test_proximity_ripens_to_ready(self):
        t = Thread("x", "q", status="seeded", readiness=0.3, entities=["Harbor"])
        for _ in range(3):
            threads.advance([t], ["Harbor"])
        self.assertEqual(t.status, "ready")
        self.assertGreaterEqual(t.readiness, 0.7)

    def test_ambient_drift_is_slow(self):
        t = Thread("x", "q", status="seeded", readiness=0.3, entities=["Harbor"])
        threads.advance([t], ["Elsewhere"])                   # not near → slow drift only
        self.assertAlmostEqual(t.readiness, 0.35, places=6)
        self.assertEqual(t.status, "ripening")

    def test_ready_beats_accrues_while_ready_and_resets_below(self):
        # staleness: count consecutive beats spent 'ready'; a not-ready beat resets it to 0
        t = Thread("x", "q", status="ripening", readiness=0.65, entities=["Harbor"])
        threads.advance([t], ["Harbor"])                      # 0.65 + 0.30 = 0.95 → ready → 1 beat
        self.assertEqual((t.status, t.ready_beats), ("ready", 1))
        threads.advance([t], [])                              # still ready (drift keeps it ≥0.7) → 2
        self.assertEqual(t.ready_beats, 2)
        t.status, t.readiness = "ripening", 0.4              # dropped below ready (e.g. after an author edit)
        threads.advance([t], [])                              # ripening → counter resets
        self.assertEqual(t.ready_beats, 0)

    def test_clock_ticks_down_to_ready(self):
        t = Thread("s", "a storm", kind="clock", status="ripening", clock=2, entities=["World"])
        threads.advance([t], [])
        self.assertEqual(t.clock, 1)
        self.assertNotEqual(t.status, "ready")
        threads.advance([t], [])
        self.assertEqual(t.status, "ready")

    def test_load_is_robust_to_junk(self):
        d = Path(tempfile.mkdtemp()) / "threads.json"
        d.write_text('[{"id":"a","question":"q","bogus_key":1},{"no_id":true},"garbage"]')
        back = threads.load(d)                                 # extra key tolerated, junk dropped
        self.assertEqual([t.id for t in back], ["a"])

    def test_save_load_roundtrip(self):
        d = Path(tempfile.mkdtemp()) / "threads.json"
        threads.save(d, [Thread("a", "q1", entities=["N"]), Thread("b", "q2", kind="clock", clock=3)])
        back = threads.load(d)
        self.assertEqual([t.id for t in back], ["a", "b"])
        self.assertEqual(back[1].clock, 3)

    def test_stages_roundtrip(self):
        d = Path(tempfile.mkdtemp()) / "threads.json"
        threads.save(d, [Thread("a", "q", stages=["one", "two"], stage=1)])
        back = threads.load(d)
        self.assertEqual(back[0].stages, ["one", "two"])
        self.assertEqual(back[0].stage, 1)

    def test_hidden_defaults_false_on_legacy(self):
        # a legacy threads.json (no 'hidden' key) loads with hidden False and advance() doesn't crash
        d = Path(tempfile.mkdtemp()) / "threads.json"
        d.write_text('[{"id":"a","question":"q","entities":["N"]}]')
        back = threads.load(d)
        self.assertEqual(back[0].hidden, False)
        threads.advance(back, ["N"])                          # no crash

    def test_hidden_coerces_fail_soft(self):
        # a hand-edited non-bool hidden coerces to bool without crashing load()/advance()
        d = Path(tempfile.mkdtemp()) / "threads.json"
        d.write_text('[{"id":"a","question":"q","hidden":"yes"},{"id":"b","question":"q2","hidden":1}]')
        back = threads.load(d)
        self.assertEqual([t.hidden for t in back], [True, True])
        threads.advance(back, [])                             # no crash

    def test_hidden_roundtrips_and_is_the_known_ondisk_delta(self):
        # hidden survives save→load; and asdict now emits 'hidden' for EVERY thread (the reviewed on-disk delta)
        d = Path(tempfile.mkdtemp()) / "threads.json"
        threads.save(d, [Thread("a", "q", hidden=True), Thread("b", "q2")])
        back = threads.load(d)
        self.assertEqual([t.hidden for t in back], [True, False])
        raw = json.loads(d.read_text())
        self.assertEqual(raw[0]["hidden"], True)
        self.assertEqual(raw[1]["hidden"], False)             # additive delta: every thread now serializes 'hidden'


if __name__ == "__main__":
    unittest.main()
