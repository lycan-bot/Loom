"""The timeline spine (storyteller-memory Phase 6): consolidation records events; each is queryable
on two clocks (real-turn range + in-fiction story time). Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import episodic, consolidate, narrate, canon, transcript, llm, config


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class EpisodicTest(unittest.TestCase):
    def test_record_query_two_clocks(self):
        camp = _camp(); sp = camp / "state.json"
        episodic.record(sp, [{"what": "the player met Professor Finch in the Grand Library", "when": "the first evening"}],
                        turn_start=0, turn_end=8)
        episodic.record(sp, [{"what": "Wren taught the wards ritual"}], turn_start=8, turn_end=16)
        self.assertEqual(len(episodic.entries(sp)), 2)
        hits = episodic.query(sp, "when did we meet the professor")
        self.assertTrue(hits and "Finch" in hits[0]["what"])
        self.assertEqual(hits[0]["when"], "the first evening")     # in-fiction clock
        self.assertEqual(hits[0]["turn_start"], 0)                 # real-turn clock

    def test_dedup_on_reconsolidation(self):
        camp = _camp(); sp = camp / "state.json"
        ev = [{"what": "the gate opened"}]
        episodic.record(sp, ev, turn_start=0, turn_end=8)
        episodic.record(sp, ev, turn_start=0, turn_end=8)         # same window + what → deduped
        self.assertEqual(len(episodic.entries(sp)), 1)

    def test_consolidate_apply_records_events(self):
        camp = _camp()
        prop = {"nodes": [], "state": {}, "threads_new": [], "threads_resolved": [], "character_updates": [],
                "reputation": [], "events": [{"what": "a bargain was struck at the docks", "when": "dusk"}]}
        consolidate.apply(prop, camp / "world", camp / "state.json", lambda *a: True, deed_window=(4, 12))
        evs = episodic.entries(camp / "state.json")
        self.assertEqual(len(evs), 1)
        self.assertEqual((evs[0]["turn_start"], evs[0]["turn_end"]), (4, 12))   # stamped with the window
        self.assertEqual(evs[0]["when"], "dusk")

    def test_narrate_injects_timeline_on_when_question(self):
        camp = _camp(); t = camp / "t.jsonl"; sp = camp / "state.json"
        canon.write_node(camp / "world", "Room", "a room")
        episodic.record(sp, [{"what": "the player swore the oath to Wren", "when": "midwinter"}],
                        turn_start=2, turn_end=6)
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
