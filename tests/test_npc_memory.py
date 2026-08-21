"""Per-NPC memory (NPC-agency P1): a READ-VIEW over the blessed episodic timeline. The load-bearing
invariant is anti-collapse — a goal-affecting recall sees ONLY blessed beats (play/sleep), never an
NPC's own world-round improv, so it can't reinforce a goal off its own imagined output. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import episodic, npc_memory, consolidate


def _camp():
    return Path(tempfile.mkdtemp())


class WhoTagTest(unittest.TestCase):
    def test_who_recorded_and_normalized(self):
        camp = _camp(); sp = camp / "state.json"
        episodic.record(sp, [{"what": "Wren studies wards", "who": "Wren"}], entry_start=1, source="world")
        episodic.record(sp, [{"what": "Vael and Orrin confer", "who": ["Vael", "Orrin"]}], entry_start=2, source="world")
        rows = episodic.entries(sp)
        self.assertEqual(rows[0]["who"], ["Wren"])                 # string → one-element list
        self.assertEqual(rows[1]["who"], ["Vael", "Orrin"])       # list preserved

    def test_who_does_not_break_dedup(self):
        camp = _camp(); sp = camp / "state.json"
        episodic.record(sp, [{"what": "Wren studies wards", "who": "Wren"}], entry_start=1, source="world")
        n = episodic.record(sp, [{"what": "Wren studies wards", "who": ["Wren"]}], entry_start=1, source="world")
        self.assertEqual(n, 0)                                     # same (entry_start, what) → deduped despite who
        self.assertEqual(len(episodic.entries(sp)), 1)


class RecallTest(unittest.TestCase):
    def _seed(self, sp):
        episodic.record(sp, [{"what": "Wren slips into the archive at night", "who": "Wren"}], entry_start=1, source="world")
        episodic.record(sp, [{"what": "Wren copies a warded page", "who": "Wren"}], entry_start=2, source="world")
        episodic.record(sp, [{"what": "Wren confessed the theft to the player", "who": "Wren"}], entry_start=3, source="play")
        episodic.record(sp, [{"what": "Orrin locks the gates", "who": "Orrin"}], entry_start=4, source="world")

    def test_blessed_only_excludes_improv(self):
        # THE anti-collapse invariant: a goal-affecting recall sees only what actually happened (play/sleep),
        # never the NPC's own world-round improv
        camp = _camp(); sp = camp / "state.json"; self._seed(sp)
        blessed = npc_memory.recall(sp, "Wren", k=10, blessed_only=True)
        self.assertEqual([e["what"] for e in blessed], ["Wren confessed the theft to the player"])
        allrows = npc_memory.recall(sp, "Wren", k=10, blessed_only=False)
        self.assertEqual(len(allrows), 3)                         # prose-continuity read sees the improv too

    def test_recall_scoped_to_the_npc(self):
        camp = _camp(); sp = camp / "state.json"; self._seed(sp)
        self.assertEqual(npc_memory.recall(sp, "Nobody", k=10, blessed_only=False), [])
        orrin = npc_memory.recall(sp, "Orrin", k=10, blessed_only=False)
        self.assertEqual([e["what"] for e in orrin], ["Orrin locks the gates"])

    def test_legacy_row_without_who_falls_back_to_text(self):
        camp = _camp(); sp = camp / "state.json"
        episodic.record(sp, [{"what": "Wren lingered by the ley-scar"}], entry_start=1, source="play")  # no who tag
        self.assertEqual(len(npc_memory.recall(sp, "Wren", k=5, blessed_only=True)), 1)
        self.assertEqual(npc_memory.recall(sp, "Vael", k=5, blessed_only=True), [])   # not named → not recalled

    def test_q_ranks_within_the_npcs_slice(self):
        camp = _camp(); sp = camp / "state.json"; self._seed(sp)
        got = npc_memory.recall(sp, "Wren", q="archive at night", k=1, blessed_only=False)
        self.assertIn("archive", got[0]["what"])

    def test_k_zero_returns_nothing(self):
        camp = _camp(); sp = camp / "state.json"; self._seed(sp)
        self.assertEqual(npc_memory.recall(sp, "Wren", k=0), [])   # a passing NPC (rung→0) recalls nothing


class PlayedBeatWhoTest(unittest.TestCase):
    def test_consolidate_records_played_events_with_who(self):
        # R1 keystone: a PLAYED beat (through the diode) now carries its actor, so npc_memory recalls it
        # by STRUCTURE (source='play' = blessed) instead of a fragile text match
        camp = _camp(); (camp / "world").mkdir()
        sp = camp / "state.json"
        consolidate.apply({"events": [{"what": "Wren struck the bargain with the player", "who": ["Wren"]}]},
                          camp / "world", sp, approve=lambda *a: True, deed_window=(3, 4))
        rows = episodic.entries(sp)
        self.assertEqual(rows[0].get("who"), ["Wren"])
        got = npc_memory.recall(sp, "Wren", k=5, blessed_only=True)   # blessed → the played beat is remembered
        self.assertEqual([e["what"] for e in got], ["Wren struck the bargain with the player"])

    def test_played_event_without_who_still_records(self):
        camp = _camp(); (camp / "world").mkdir()
        sp = camp / "state.json"
        consolidate.apply({"events": [{"what": "a storm broke over the coast"}]},
                          camp / "world", sp, approve=lambda *a: True, deed_window=(1, 2))
        self.assertEqual(len(episodic.entries(sp)), 1)               # who is optional; the beat still lands


class SharedTest(unittest.TestCase):
    """R2: an NPC's memory of a specific OTHER (the player) — the beats where BOTH acted."""

    def _seed(self, sp):
        episodic.record(sp, [{"what": "Wren struck a bargain with Kess", "who": ["Wren", "Kess"]}], entry_start=1, source="play")
        episodic.record(sp, [{"what": "Wren slipped away alone", "who": ["Wren"]}], entry_start=2, source="world")
        episodic.record(sp, [{"what": "Wren and Kess argued at the gate", "who": ["Wren", "Kess"]}], entry_start=3, source="play")
        episodic.record(sp, [{"what": "Kess wandered the docks", "who": ["Kess"]}], entry_start=4, source="play")

    def test_only_beats_they_share(self):
        camp = _camp(); sp = camp / "state.json"; self._seed(sp)
        got = npc_memory.shared(sp, "Wren", "Kess", k=10, blessed_only=True)
        self.assertEqual([e["what"] for e in got],
                         ["Wren struck a bargain with Kess", "Wren and Kess argued at the gate"])

    def test_blessed_only_excludes_shared_improv(self):
        camp = _camp(); sp = camp / "state.json"
        episodic.record(sp, [{"what": "Wren imagined meeting Kess", "who": ["Wren", "Kess"]}], entry_start=1, source="world")
        self.assertEqual(npc_memory.shared(sp, "Wren", "Kess", k=5, blessed_only=True), [])

    def test_self_and_stranger_return_nothing(self):
        camp = _camp(); sp = camp / "state.json"; self._seed(sp)
        self.assertEqual(npc_memory.shared(sp, "Wren", "Wren", k=5), [])       # no memory of oneself-as-other
        self.assertEqual(npc_memory.shared(sp, "Wren", "Nobody", k=5), [])     # no shared history


class ClauseTest(unittest.TestCase):
    def test_clause_marks_improv_unconfirmed(self):
        camp = _camp(); sp = camp / "state.json"
        episodic.record(sp, [{"what": "Wren slips into the archive", "who": "Wren"}], entry_start=1, source="world")
        episodic.record(sp, [{"what": "Wren confessed to the player", "who": "Wren"}], entry_start=2, source="play")
        cl = npc_memory.clause(sp, "Wren", k=10, blessed_only=False)
        self.assertIn("(unconfirmed)", cl)                        # the improv beat is flagged
        self.assertIn("confessed", cl)
        blessed = npc_memory.clause(sp, "Wren", k=10, blessed_only=True)
        self.assertNotIn("(unconfirmed)", blessed)                # blessed-only view has nothing to flag

    def test_clause_empty_when_no_memory(self):
        camp = _camp(); sp = camp / "state.json"
        self.assertEqual(npc_memory.clause(sp, "Wren"), "")


if __name__ == "__main__":
    unittest.main()
