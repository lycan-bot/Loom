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


if __name__ == "__main__":
    unittest.main()
