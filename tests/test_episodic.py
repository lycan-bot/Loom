"""The timeline spine (storyteller-memory Phase 6): consolidation records events; each is queryable
on two clocks (real transcript-entry range + in-fiction story time); undo reverses timeline events it
appended. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import episodic, consolidate, narrate, canon, transcript, undo, llm, config


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class EpisodicTest(unittest.TestCase):
    def test_record_query_two_clocks(self):
        camp = _camp(); sp = camp / "state.json"
        episodic.record(sp, [{"what": "the player met Professor Finch in the Grand Library", "when": "the first evening"}],
                        entry_start=0, entry_end=8)
        episodic.record(sp, [{"what": "Wren taught the wards ritual"}], entry_start=8, entry_end=16)
        self.assertEqual(len(episodic.entries(sp)), 2)
        hits = episodic.query(sp, "when did we meet the professor")
        self.assertTrue(hits and "Finch" in hits[0]["what"])
        self.assertEqual(hits[0]["when"], "the first evening")     # in-fiction clock
        self.assertEqual(hits[0]["entry_start"], 0)               # real transcript-entry clock

    def test_query_ignores_stopwords(self):
        # BM25 (not raw overlap): a shared stopword like 'the' must not surface an unrelated event
        camp = _camp(); sp = camp / "state.json"
        episodic.record(sp, [{"what": "the dragon burned the northern watchtower"}], entry_start=0, entry_end=8)
        self.assertEqual(episodic.query(sp, "when did the ritual fail"), [])   # no shared distinctive token

    def test_dedup_on_reconsolidation(self):
        camp = _camp(); sp = camp / "state.json"
        ev = [{"what": "the gate opened"}]
        episodic.record(sp, ev, entry_start=0, entry_end=8)
        episodic.record(sp, ev, entry_start=0, entry_end=8)       # same window + what → deduped
        self.assertEqual(len(episodic.entries(sp)), 1)

    def test_consolidate_apply_records_events(self):
        camp = _camp()
        prop = {"nodes": [], "state": {}, "threads_new": [], "threads_resolved": [], "character_updates": [],
                "reputation": [], "events": [{"what": "a bargain was struck at the docks", "when": "dusk"}]}
        consolidate.apply(prop, camp / "world", camp / "state.json", lambda *a: True, deed_window=(4, 12))
        evs = episodic.entries(camp / "state.json")
        self.assertEqual(len(evs), 1)
        self.assertEqual((evs[0]["entry_start"], evs[0]["entry_end"]), (4, 12))   # stamped with the window
        self.assertEqual(evs[0]["when"], "dusk")

    def test_undo_truncates_the_timeline(self):
        # red-team D1: episodic.jsonl is append-only; undo must reverse events a fold appended this turn,
        # or the timeline asserts a beat the story no longer contains
        camp = _camp(); sp = camp / "state.json"; t = camp / "t.jsonl"
        transcript.append(t, "player", "a"); transcript.append(t, "narrator", "b")
        episodic.record(sp, [{"what": "an old, established event"}], entry_start=0, entry_end=2)
        undo.snapshot(t, sp)                                       # captures the timeline length pre-turn
        transcript.append(t, "player", "c"); transcript.append(t, "narrator", "d")
        episodic.record(sp, [{"what": "a beat from the turn we will undo"}], entry_start=2, entry_end=4)
        self.assertEqual(len(episodic.entries(sp)), 2)
        undo.undo(t, sp)
        self.assertEqual([e["what"] for e in episodic.entries(sp)], ["an old, established event"])  # new one reversed

    def test_narrate_injects_timeline_on_when_question(self):
        camp = _camp(); t = camp / "t.jsonl"; sp = camp / "state.json"
        canon.write_node(camp / "world", "Room", "a room")
        episodic.record(sp, [{"what": "the player swore the oath to Wren", "when": "midwinter"}],
                        entry_start=2, entry_end=6)
        transcript.append(t, "player", "a")
        transcript.append(t, "narrator", "b")
        cap = {}
        orig = llm.chat
        llm.chat = lambda m, c, **k: (cap.__setitem__("sys", m[0]["content"]), "ok.")[1]
        try:
            narrate.turn("when did I swear the oath?", dict(config.DEFAULTS), t, camp / "world", sp)
        finally:
            llm.chat = orig
        self.assertIn("TIMELINE", cap["sys"])
        self.assertIn("oath", cap["sys"])
        self.assertIn("midwinter", cap["sys"])                    # the story-time clock reaches the narrator


if __name__ == "__main__":
    unittest.main()
