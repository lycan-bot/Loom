"""The plan above canon: threads ripen with proximity + time, activate only when the
player is near their subject, and clocks tick down. Pure, offline."""
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


if __name__ == "__main__":
    unittest.main()
