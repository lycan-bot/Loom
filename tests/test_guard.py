"""The continuity guard: read-only structural checks over canon + the plan. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import guard, canon, threads
from loom.threads import Thread


def _campaign():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class GuardTest(unittest.TestCase):
    def test_dangling_link_flagged(self):
        camp = _campaign()
        canon.write_node(camp / "world", "A", "a node that links to [[Nowhere]]")
        fs = guard.check(camp / "world", camp / "threads.json")
        self.assertTrue(any(f.kind == "dangling-link" for f in fs))

    def test_thread_unknown_entity_flagged(self):
        camp = _campaign()
        canon.write_node(camp / "world", "A", "a node")
        threads.save(camp / "threads.json", [Thread("t", "q", entities=["Ghost"])])
        fs = guard.check(camp / "world", camp / "threads.json")
        self.assertTrue(any(f.kind == "unknown-entity" for f in fs))

    def test_resolved_thread_entity_ignored(self):
        camp = _campaign()
        canon.write_node(camp / "world", "A", "a node")
        threads.save(camp / "threads.json", [Thread("t", "q", entities=["Ghost"], status="resolved")])
        self.assertFalse(any(f.kind == "unknown-entity"
                             for f in guard.check(camp / "world", camp / "threads.json")))

    def test_orphan_flagged_but_linked_pair_clean(self):
        camp = _campaign()
        canon.write_node(camp / "world", "Lonely", "an island unto itself")
        canon.write_node(camp / "world", "A", "links [[B]]")
        canon.write_node(camp / "world", "B", "links [[A]]")
        orphans = [f for f in guard.check(camp / "world", camp / "threads.json") if f.kind == "orphan"]
        self.assertEqual(len(orphans), 1)
        self.assertIn("Lonely", orphans[0].message)

    def test_clean_campaign(self):
        camp = _campaign()
        canon.write_node(camp / "world", "A", "links [[B]]")
        canon.write_node(camp / "world", "B", "links [[A]]")
        self.assertEqual(guard.check(camp / "world", camp / "threads.json"), [])

    def test_stale_thread_flagged(self):
        # a thread READY for many turns without paying off → a forgotten/overdue arc (low)
        camp = _campaign()
        threads.save(camp / "threads.json",
                     [Thread("q", "Will the vault ever open?", status="ready", readiness=1.0, ready_beats=9)])
        fs = guard.check(camp / "world", camp / "threads.json")
        self.assertTrue(any(f.kind == "stale-thread" and "vault" in f.message for f in fs))

    def test_briefly_ready_thread_not_flagged(self):
        # a thread only just ready (a few turns) is fine — the low-noise guarantee
        camp = _campaign()
        threads.save(camp / "threads.json",
                     [Thread("q", "Will the vault open?", status="ready", readiness=1.0, ready_beats=3)])
        self.assertFalse(any(f.kind == "stale-thread" for f in guard.check(camp / "world", camp / "threads.json")))

    def test_resolved_stale_thread_not_flagged(self):
        # a resolved thread never counts, however high its stale counter climbed before it paid off
        camp = _campaign()
        threads.save(camp / "threads.json",
                     [Thread("q", "Will the vault open?", status="resolved", ready_beats=20)])
        self.assertFalse(any(f.kind == "stale-thread" for f in guard.check(camp / "world", camp / "threads.json")))


if __name__ == "__main__":
    unittest.main()
