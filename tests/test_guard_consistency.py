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

    def test_operator_blessed_arc_is_not_self_contradiction(self):
        # red-team LOW: blessing a betrayal then a reconciliation (an authored arc) must NOT fire the
        # 'archivist contradicting itself' detector — a blessed flip is authorised, not self-contradiction
        from loom import consolidate, canon
        camp = _camp()
        canon.write_node(camp / "world", "Mara", "a fisher", {"kind": "character", "disposition": "warm"})
        sp = camp / "state.json"
        consolidate.queue_reversal(sp, [{"name": "Mara", "field": "disposition", "old": "warm", "new": "hostile"}])
        consolidate.apply_reversal(camp / "world", sp, "Mara", "disposition")     # bless → hostile
        consolidate.queue_reversal(sp, [{"name": "Mara", "field": "disposition", "old": "hostile", "new": "warm"}])
        consolidate.apply_reversal(camp / "world", sp, "Mara", "disposition")     # bless → warm
        t = camp / "t.jsonl"; transcript.append(t, "player", "x")
        self.assertFalse(any(f.kind == "disposition-reversal" for f in self._check(camp, t)))

    def test_single_reversal_not_flagged(self):
        # a lone reversal is a legitimate arc (a betrayal) — it must stay quiet (low-noise guarantee)
        camp = _camp()
        sp = camp / "state.json"
        provenance.log(sp, [{"name": "Mara", "field": "disposition", "old": "warm", "new": "hostile", "reversal": True}])
        t = camp / "t.jsonl"
        transcript.append(t, "player", "x")
        self.assertFalse(any(f.kind == "disposition-reversal" for f in self._check(camp, t)))

    def test_world_terminal_then_acts_in_a_later_beat(self):
        # world marks the canon character Varro (canon-silent on death) slain @2; he acts in a LATER beat @5 → med
        from loom import world, episodic
        camp = _camp(); sp = camp / "state.json"
        canon.write_node(camp / "world", "Varro", "a knight", {"kind": "character"})   # canon still has him active
        world.set_fact(sp, "Varro", "state", "slain", since=2)
        episodic.record(sp, [{"what": "Varro cuts down the guard", "who": ["Varro"]}], entry_start=5, source="play")
        t = camp / "t.jsonl"; transcript.append(t, "player", "x")
        self.assertTrue(any(f.kind == "world-dead-but-active" and "Varro" in f.message and f.severity == "med"
                            for f in self._check(camp, t)))

    def test_world_terminal_acting_before_death_not_flagged(self):
        # he acted BEFORE being marked slain (turn 2 < turn 5) — no contradiction, must stay quiet
        from loom import world, episodic
        camp = _camp(); sp = camp / "state.json"
        canon.write_node(camp / "world", "Varro", "a knight", {"kind": "character"})
        world.set_fact(sp, "Varro", "state", "slain", since=5)
        episodic.record(sp, [{"what": "Varro cuts down the guard", "who": ["Varro"]}], entry_start=2, source="play")
        t = camp / "t.jsonl"; transcript.append(t, "player", "x")
        self.assertFalse(any(f.kind == "world-dead-but-active" for f in self._check(camp, t)))

    def test_namesake_object_does_not_collide_with_a_person(self):
        # red-team: a destroyed SHIP 'the Wren' must NOT flag the living cadet 'Wren' who acts later
        from loom import world, episodic
        camp = _camp(); sp = camp / "state.json"
        canon.write_node(camp / "world", "Wren", "a sharp cadet", {"kind": "character"})   # the person
        world.set_fact(sp, "the Wren", "state", "sunk", since=2)                            # the ship (no canon node)
        episodic.record(sp, [{"what": "Wren reloads the ballista", "who": ["Wren"]}], entry_start=5, source="play")
        t = camp / "t.jsonl"; transcript.append(t, "player", "x")
        self.assertFalse(any(f.kind == "world-dead-but-active" for f in self._check(camp, t)))

    def test_two_terminal_facts_are_order_independent(self):
        # red-team: slain@2 + destroyed@9 on one character; a beat @5 must flag via the EARLIER fact, not last-loaded
        from loom import world, episodic
        camp = _camp(); sp = camp / "state.json"
        canon.write_node(camp / "world", "Varro", "a knight", {"kind": "character"})
        world.set_fact(sp, "Varro", "state", "slain", since=2)
        world.set_fact(sp, "Varro", "fate", "destroyed", since=9)      # a later terminal fact on a DIFFERENT attribute
        episodic.record(sp, [{"what": "Varro strikes", "who": ["Varro"]}], entry_start=5, source="play")
        t = camp / "t.jsonl"; transcript.append(t, "player", "x")
        self.assertTrue(any(f.kind == "world-dead-but-active" and f.severity == "med" for f in self._check(camp, t)))

    def test_canon_dead_is_not_double_reported(self):
        # red-team: a character dead in BOTH canon AND the world store fires dead_but_active ONLY (no double-report)
        from loom import world
        camp = _camp(); sp = camp / "state.json"
        canon.write_node(camp / "world", "Mara", "a mage", {"kind": "character", "status": "dead"})
        world.set_fact(sp, "Mara", "state", "slain", since=2)
        t = camp / "t.jsonl"; transcript.append(t, "player", "x")
        transcript.append(t, "narrator", "Mara steps from the shadows and casts a spell.")
        kinds = [f.kind for f in self._check(camp, t)]
        self.assertIn("dead-but-active", kinds)                        # canon's detector covers it…
        self.assertNotIn("world-dead-but-active", kinds)               # …and the world detector stays silent (no dup)

    def test_world_terminal_character_mentioned_recently_low(self):
        # world marks the canon character Varro (canon-silent) slain, still named in a recent turn → low
        from loom import world
        camp = _camp(); sp = camp / "state.json"
        canon.write_node(camp / "world", "Varro", "a knight", {"kind": "character"})
        world.set_fact(sp, "Varro", "state", "slain", since=2)
        t = camp / "t.jsonl"; transcript.append(t, "player", "x")
        transcript.append(t, "narrator", "Varro raises his sword and charges.")
        self.assertTrue(any(f.kind == "world-dead-but-active" and f.severity == "low" for f in self._check(camp, t)))

    def test_destroyed_object_is_clean(self):
        # a burned ledger (not a canon character) never resolves → never fires, even if named
        from loom import world
        camp = _camp(); sp = camp / "state.json"
        world.set_fact(sp, "the old ledger", "condition", "burned", since=2)
        t = camp / "t.jsonl"; transcript.append(t, "player", "x")
        transcript.append(t, "narrator", "You glance at the old ledger's ashes and move on.")
        self.assertFalse(any(f.kind == "world-dead-but-active" for f in self._check(camp, t)))

    def test_world_terminal_no_timestamp_skips_the_temporal_signal(self):
        # an operator-set fact carries no `since` → the temporal (acts-later) signal can't order it → no med flag
        from loom import world, episodic
        camp = _camp(); sp = camp / "state.json"
        canon.write_node(camp / "world", "Varro", "a knight", {"kind": "character"})
        world.set_fact(sp, "Varro", "state", "slain")               # since=None
        episodic.record(sp, [{"what": "Varro cuts down the guard", "who": ["Varro"]}], entry_start=5, source="play")
        t = camp / "t.jsonl"; transcript.append(t, "player", "x")
        self.assertFalse(any(f.kind == "world-dead-but-active" and f.severity == "med" for f in self._check(camp, t)))

    def test_structural_detectors_run_without_a_transcript(self):
        # backward compat: check() with no tpath still runs the structural detectors and nothing crashes
        camp = _camp()
        canon.write_node(camp / "world", "A", "links to [[Ghost]] which does not exist")
        fs = guard.check(camp / "world", camp / "threads.json")
        self.assertTrue(any(f.kind == "dangling-link" for f in fs))


if __name__ == "__main__":
    unittest.main()
