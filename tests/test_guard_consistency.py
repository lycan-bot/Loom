"""Consistency detectors (storyteller-memory Phase 4): the guard catches the story CONTRADICTING its
own canon — a dead character who acts — and surfaces Phase 3's confabulation signal. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import guard, canon, transcript


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class ConsistencyTest(unittest.TestCase):
    def _check(self, camp, t):
        return guard.check(camp / "world", camp / "threads.json", tpath=t, spath=camp / "state.json")

    def test_dead_but_active_from_body_phrase(self):
        camp = _camp()
        canon.write_node(camp / "world", "Varro", "a knight who was slain at the bridge last winter",
                         {"kind": "character"})
        t = camp / "t.jsonl"
        transcript.append(t, "player", "x")
        transcript.append(t, "narrator", "Varro raises his sword and charges into the fray.")
        self.assertIn("dead-but-active", [f.kind for f in self._check(camp, t)])

    def test_dead_but_active_from_status_field(self):
        camp = _camp()
        canon.write_node(camp / "world", "Mara", "a mage", {"kind": "character", "status": "dead"})
        t = camp / "t.jsonl"
        transcript.append(t, "player", "x")
        transcript.append(t, "narrator", "Mara steps from the shadows and casts a spell.")
        fs = self._check(camp, t)
        self.assertTrue(any(f.kind == "dead-but-active" and "Mara" in f.message for f in fs))

    def test_living_character_not_flagged_dead(self):
        camp = _camp()
        canon.write_node(camp / "world", "Wren", "a living cadet, sharp and warm", {"kind": "character"})
        t = camp / "t.jsonl"
        transcript.append(t, "player", "x")
        transcript.append(t, "narrator", "Wren smiles and turns the page.")
        self.assertFalse(any(f.kind == "dead-but-active" for f in self._check(camp, t)))

    def test_confabulated_entity_surfaced_as_finding(self):
        camp = _camp()
        canon.write_node(camp / "world", "Wren", "a cadet", {"kind": "character"})
        t = camp / "t.jsonl"
        transcript.append(t, "player", "x")
        transcript.append(t, "narrator", "In the hall the sly Duke Varro schemes against the crown.")
        transcript.append(t, "player", "y")
        transcript.append(t, "narrator", "Once more Duke Varro plots his slow ascent.")
        fs = self._check(camp, t)
        self.assertTrue(any(f.kind == "confabulated-entity" and "Varro" in f.message for f in fs))

    def test_structural_detectors_run_without_a_transcript(self):
        # backward compat: check() with no tpath still runs the structural detectors and nothing crashes
        camp = _camp()
        canon.write_node(camp / "world", "A", "links to [[Ghost]] which does not exist")
        fs = guard.check(camp / "world", camp / "threads.json")
        self.assertTrue(any(f.kind == "dangling-link" for f in fs))


if __name__ == "__main__":
    unittest.main()
