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

    def test_stale_thread_excludes_hidden(self):
        # red-team fix (Brick B): a director-only (hidden) clock sits 'ready' by design (awaiting a blessed
        # reveal) — it must NOT nag as a forgotten/overdue arc in the operator-facing advisory.
        camp = _campaign()
        threads.save(camp / "threads.json",
                     [Thread("h", "the sleeping god wakes", status="ready", readiness=1.0,
                             ready_beats=20, hidden=True)])
        self.assertFalse(any(f.kind == "stale-thread" for f in guard.check(camp / "world", camp / "threads.json")))

    def test_location_conflict_flags_a_non_place(self):
        camp = _campaign()
        canon.write_node(camp / "world", "Wren", "a cadet", {"kind": "character"})
        canon.write_node(camp / "world", "Faelan", "a mentor", {"kind": "character", "location": "Wren"})  # a person, not a place
        fs = guard.check(camp / "world", camp / "threads.json")
        self.assertTrue(any(f.kind == "location-conflict" and "Faelan" in f.message for f in fs))

    def test_location_at_a_real_place_is_clean(self):
        camp = _campaign()
        canon.write_node(camp / "world", "Library", "a warded library", {"kind": "place"})
        canon.write_node(camp / "world", "Wren", "a cadet", {"kind": "character", "location": "Library"})
        self.assertFalse(any(f.kind == "location-conflict" for f in guard.check(camp / "world", camp / "threads.json")))

    def test_location_at_an_unnoded_place_is_not_flagged(self):
        # an NPC may move to a not-yet-noded place — a location with no canon node is intentional, never flagged
        camp = _campaign()
        canon.write_node(camp / "world", "Wren", "a cadet", {"kind": "character", "location": "The Far Reaches"})
        self.assertFalse(any(f.kind == "location-conflict" for f in guard.check(camp / "world", camp / "threads.json")))

    def test_location_conflict_covers_factions(self):
        # red-team: factions are world-round agents too, so a faction at a non-place is also flagged
        camp = _campaign()
        canon.write_node(camp / "world", "Wren", "a cadet", {"kind": "character"})
        canon.write_node(camp / "world", "The Guild", "a guild", {"kind": "faction", "location": "Wren"})
        self.assertTrue(any(f.kind == "location-conflict" and "Guild" in f.message
                            for f in guard.check(camp / "world", camp / "threads.json")))

    def test_location_conflict_is_case_and_space_insensitive(self):
        # red-team: a mis-cased/whitespace-variant non-place location still mis-routes → still flagged
        camp = _campaign()
        canon.write_node(camp / "world", "Wren", "a cadet", {"kind": "character"})
        canon.write_node(camp / "world", "Faelan", "a mentor", {"kind": "character", "location": "  wren "})
        self.assertTrue(any(f.kind == "location-conflict" for f in guard.check(camp / "world", camp / "threads.json")))

    def test_shared_title_prefers_the_real_place(self):
        # red-team: a genuine place named 'Citadel' must not be masked by a same-titled faction sorting later
        camp = _campaign(); w = camp / "world"
        (w / "a-citadel.md").write_text("---\nkind: place\ntitle: Citadel\n---\n\na fortress\n")
        (w / "z-order.md").write_text("---\nkind: faction\ntitle: Citadel\n---\n\nthe ruling order\n")
        canon.write_node(w, "Wren", "a cadet", {"kind": "character", "location": "Citadel"})
        self.assertFalse(any(f.kind == "location-conflict" for f in guard.check(w, camp / "threads.json")))


if __name__ == "__main__":
    unittest.main()
