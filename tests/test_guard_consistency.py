"""Consistency detectors (storyteller-memory Phase 4): the guard catches the story CONTRADICTING its
own canon — a dead character who acts — and surfaces Phase 3's confabulation signal. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import guard, canon, transcript, provenance


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class ConsistencyTest(unittest.TestCase):
    def _check(self, camp, t):
        return guard.check(camp / "world", camp / "threads.json", tpath=t, spath=camp / "state.json")

    def test_dead_but_active_from_body_marker(self):
        camp = _camp()
        canon.write_node(camp / "world", "Varro", "a knight, (deceased), who fell at the bridge",
                         {"kind": "character"})               # explicit marker, not incidental prose
        t = camp / "t.jsonl"
        transcript.append(t, "player", "x")
        transcript.append(t, "narrator", "Varro raises his sword and charges into the fray.")
        self.assertIn("dead-but-active", [f.kind for f in self._check(camp, t)])

    def test_explicit_alive_status_overrides_body_prose(self):
        # red-team D1: a living character whose BACKSTORY mentions violence/death must not be flagged
        camp = _camp()
        canon.write_node(camp / "world", "Amara", "In her nightmares she was slain a hundred times, yet she woke.",
                         {"kind": "character", "status": "alive"})
        t = camp / "t.jsonl"
        transcript.append(t, "player", "x")
        transcript.append(t, "narrator", "Amara steps forward, very much alive.")
        self.assertFalse(any(f.kind == "dead-but-active" for f in self._check(camp, t)))

    def test_incidental_death_prose_not_flagged(self):
        # red-team D1: prose about ANOTHER character's death (no marker, no status) must not fire
        camp = _camp()
        canon.write_node(camp / "world", "Bran", "His sister died at the siege; he alone survived, grieving.",
                         {"kind": "character"})
        t = camp / "t.jsonl"
        transcript.append(t, "player", "x")
        transcript.append(t, "narrator", "Bran draws his blade and stands ready.")
        self.assertFalse(any(f.kind == "dead-but-active" for f in self._check(camp, t)))

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

    def test_disposition_oscillation_flagged(self):
        # a flip-flop (warm→hostile→warm) is the archivist contradicting itself — flag it
        camp = _camp()
        sp = camp / "state.json"
        provenance.log(sp, [{"name": "Mara", "field": "disposition", "old": "warm", "new": "hostile", "reversal": True}])
        provenance.log(sp, [{"name": "Mara", "field": "disposition", "old": "hostile", "new": "warm", "reversal": True}])
        t = camp / "t.jsonl"
        transcript.append(t, "player", "x")
        fs = self._check(camp, t)
        self.assertTrue(any(f.kind == "disposition-reversal" and "Mara" in f.message for f in fs))

    def test_single_reversal_not_flagged(self):
        # a lone reversal is a legitimate arc (a betrayal) — it must stay quiet (low-noise guarantee)
        camp = _camp()
        sp = camp / "state.json"
        provenance.log(sp, [{"name": "Mara", "field": "disposition", "old": "warm", "new": "hostile", "reversal": True}])
        t = camp / "t.jsonl"
        transcript.append(t, "player", "x")
        self.assertFalse(any(f.kind == "disposition-reversal" for f in self._check(camp, t)))

    def test_structural_detectors_run_without_a_transcript(self):
        # backward compat: check() with no tpath still runs the structural detectors and nothing crashes
        camp = _camp()
        canon.write_node(camp / "world", "A", "links to [[Ghost]] which does not exist")
        fs = guard.check(camp / "world", camp / "threads.json")
        self.assertTrue(any(f.kind == "dangling-link" for f in fs))


if __name__ == "__main__":
    unittest.main()
