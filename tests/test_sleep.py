"""The world lives between sessions: sleep advances clocks along the world's OWN pending logic,
proposes a 'while you were away' recap (propose-only, blessable), and that recap greets the
player once on return. Depth-gated — a mirror world doesn't move. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import sleep, threads, canon, state, narrate, llm, config
from loom.threads import Thread


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class AdvanceTest(unittest.TestCase):
    def test_mirror_world_does_not_move(self):
        camp = _camp()
        threads.save(camp / "threads.json", [Thread("s", "a storm nears", kind="clock", status="ripening", clock=2)])
        cfg = dict(config.DEFAULTS); cfg["depth"] = 0.0
        r = sleep.advance(cfg, camp / "world", camp / "threads.json")
        self.assertEqual(r["beats"], 0)
        self.assertEqual(r["due"], [])
        self.assertEqual(r["recap"], "")
        self.assertEqual(r["threads"][0].clock, 2)          # the clock did NOT tick — world paused

    def test_clock_fires_and_recaps(self):
        camp = _camp()
        canon.write_node(camp / "world", "Harbor", "a fishing harbor on a cold coast", {"kind": "lore"})
        threads.save(camp / "threads.json", [Thread("storm", "a storm is coming in off the sea",
                                                    kind="clock", status="ripening", clock=2)])
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0; cfg["sleep_beats"] = 4
        orig = llm.complete
        llm.complete = lambda *a, **k: '{"recap":"The storm made landfall; the boats were hauled up the shingle.","resolved":[]}'
        try:
            r = sleep.advance(cfg, camp / "world", camp / "threads.json")
        finally:
            llm.complete = orig
        self.assertIn("storm", r["due"])                    # the clock came due while away
        self.assertIn("landfall", r["recap"])

    def test_ripe_question_thread_is_not_surfaced(self):
        # a player-facing beat that happens to be ripe must NOT be spent by sleep
        camp = _camp()
        threads.save(camp / "threads.json", [Thread("q", "will she confront her brother?",
                                                    kind="question", status="ready", readiness=0.9)])
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0
        r = sleep.advance(cfg, camp / "world", camp / "threads.json")
        self.assertEqual(r["due"], [])                      # only clocks move the world in sleep
        self.assertEqual(r["recap"], "")

    def test_offline_failure_is_soft(self):
        camp = _camp()
        threads.save(camp / "threads.json", [Thread("storm", "a storm", kind="clock", status="ready", clock=0)])
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0
        orig = llm.complete
        def boom(*a, **k):
            raise RuntimeError("server down")
        llm.complete = boom
        try:
            r = sleep.advance(cfg, camp / "world", camp / "threads.json")
        finally:
            llm.complete = orig
        self.assertEqual(r["recap"], "")                    # fail-soft: no recap, no crash

    def test_hidden_clock_stays_out_of_the_sleep_recap(self):
        # red-team fix: a HIDDEN clock ticks to ready but is director-only — never in `due`, so its question
        # never reaches the player-facing 'while you were away' recap, and it does not silently resolve.
        camp = _camp()
        canon.write_node(camp / "world", "Dockhand", "a weary dockhand", {"kind": "character", "wants": "to leave"})
        threads.save(camp / "threads.json", [Thread("secret", "the sleeping god wakes beneath the harbor",
                                                    kind="clock", status="ripening", clock=1, hidden=True)])
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0; cfg["sleep_moves"] = 2
        cap = {}
        orig = llm.complete
        llm.complete = lambda prompt, c, **k: (cap.__setitem__("p", prompt),
                                               '{"recap":"The dockhand asked after berths.","resolved":[]}')[1]
        try:
            r = sleep.advance(cfg, camp / "world", camp / "threads.json")
        finally:
            llm.complete = orig
        self.assertEqual(r["due"], [])                        # the hidden clock is not due-surfaced…
        self.assertIn("Dockhand", r["moves"])                 # (a visible mover still drives the recap)
        self.assertNotIn("sleeping god", cap["p"])            # …its secret never reaches the recap prompt
        saved = {t.id: t.status for t in r["threads"]}
        self.assertNotEqual(saved["secret"], "resolved")      # and it did NOT resolve — it waits for the reveal


class NpcMovesTest(unittest.TestCase):
    def test_characters_move_and_feed_the_recap(self):
        camp = _camp()
        canon.write_node(camp / "world", "Dockhand", "a weary dockhand",
                         {"kind": "character", "wants": "to leave the harbor", "bound": "a debt he can't pay"})
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0; cfg["sleep_moves"] = 2
        cap = {}
        orig = llm.complete
        llm.complete = lambda prompt, c, **k: (cap.__setitem__("p", prompt),
                                               '{"recap":"The dockhand asked after berths on the next ship out.","resolved":[]}')[1]
        try:
            r = sleep.advance(cfg, camp / "world", camp / "threads.json")
        finally:
            llm.complete = orig
        self.assertIn("Dockhand", r["moves"])            # the character acted
        self.assertTrue(r["pending"])
        self.assertIn("Dockhand", cap["p"])              # the move fed the recap prompt
        self.assertIn("leave the harbor", cap["p"])      # grounded in the stated want
        self.assertIn("berths", r["recap"])

    def test_lead_continues_its_arc_across_sleep(self):
        # R4: a lead's sleep move carries its agenda (goal + BLESSED memory), not a flat amnesiac step
        from loom import episodic
        camp = _camp()
        canon.write_node(camp / "world", "Wren", "a cadet",
                         {"kind": "character", "importance": "main", "wants": "to escape the college"})
        episodic.record(camp / "state.json", [{"what": "Wren copied a warded page", "who": ["Wren"]}],
                        entry_start=1, source="play")
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0; cfg["sleep_moves"] = 2
        cap = {}
        orig = llm.complete
        llm.complete = lambda prompt, c, **k: (cap.__setitem__("p", prompt),
                                               '{"recap":"Wren studied the ward by candlelight.","resolved":[]}')[1]
        try:
            sleep.advance(cfg, camp / "world", camp / "threads.json")
        finally:
            llm.complete = orig
        self.assertIn("Wren wants to escape the college", cap["p"])    # the agenda, not a flat step
        self.assertIn("copied a warded page", cap["p"])                # its blessed history continues the arc

    def test_sleep_moves_zero_disables_npc_moves(self):
        camp = _camp()
        canon.write_node(camp / "world", "Dockhand", "a weary dockhand", {"kind": "character", "wants": "to leave"})
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0; cfg["sleep_moves"] = 0
        r = sleep.advance(cfg, camp / "world", camp / "threads.json")
        self.assertEqual(r["moves"], [])                 # off-switch: no one moves
        self.assertFalse(r["pending"])                   # and with no clocks, the sleep is quiet

    def test_no_characters_no_clocks_is_quiet(self):
        camp = _camp()
        canon.write_node(camp / "world", "Harbor", "a cold harbor", {"kind": "place"})
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0
        r = sleep.advance(cfg, camp / "world", camp / "threads.json")
        self.assertFalse(r["pending"])                   # a place has no want; nothing moves
        self.assertEqual(r["recap"], "")

    def test_move_does_not_spend_the_relational_payoff(self):
        # a character stepping toward their want during sleep must NOT resolve their relational
        # thread — that dramatic payoff is reserved for live play (the diode, in the NPC context)
        camp = _camp()
        canon.write_node(camp / "world", "Dockhand", "a weary dockhand", {"kind": "character", "wants": "to leave"})
        threads.save(camp / "threads.json", [Thread("dockhand-leave", "Will the Dockhand act on their wish to leave?",
                                                    kind="question", status="ready", readiness=0.8)])
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0
        orig = llm.complete
        llm.complete = lambda *a, **k: '{"recap":"The dockhand made a quiet move.","resolved":["dockhand-leave"]}'
        try:
            r = sleep.advance(cfg, camp / "world", camp / "threads.json")
            sleep.apply(r, camp / "threads.json", camp / "state.json", approve=lambda *a: True)
        finally:
            llm.complete = orig
        saved = {t.id: t.status for t in threads.load(camp / "threads.json")}
        self.assertEqual(saved["dockhand-leave"], "ready")   # untouched — payoff stays for play


class ApplyTest(unittest.TestCase):
    def test_bless_resolves_clock_and_stashes_recap(self):
        camp = _camp()
        th = [Thread("storm", "a storm", kind="clock", status="ready", clock=0)]
        report = {"beats": 4, "due": ["storm"], "recap": "The storm hit.", "resolved": [], "threads": th}
        sleep.apply(report, camp / "threads.json", camp / "state.json", approve=lambda *a: True)
        self.assertEqual(threads.load(camp / "threads.json")[0].status, "resolved")
        self.assertEqual(state.load(camp / "state.json")["_recap"], "The storm hit.")

    def test_decline_writes_nothing(self):
        camp = _camp()
        th = [Thread("storm", "a storm", kind="clock", status="ready", clock=0)]
        report = {"beats": 4, "due": ["storm"], "recap": "The storm hit.", "resolved": [], "threads": th}
        sleep.apply(report, camp / "threads.json", camp / "state.json", approve=lambda *a: False)
        self.assertIsNone(state.load(camp / "state.json").get("_recap"))
        self.assertFalse((camp / "threads.json").exists())  # nothing persisted — the world un-moved

    def test_empty_recap_is_a_noop(self):
        camp = _camp()
        report = {"beats": 4, "due": ["storm"], "recap": "", "resolved": [], "threads": []}
        out = sleep.apply(report, camp / "threads.json", camp / "state.json", approve=lambda *a: True)
        self.assertEqual(out["recap"], "")


class NarrateRecapTest(unittest.TestCase):
    def test_recap_greets_once_then_clears(self):
        camp = _camp()
        canon.write_node(camp / "world", "Room", "a plain room")
        state.save(camp / "state.json", {"_recap": "The storm passed in the night."})
        cfg = dict(config.DEFAULTS)
        cap = {}
        orig = llm.chat
        llm.chat = lambda m, c, **k: (cap.__setitem__("sys", m[0]["content"]), "You wake.")[1]
        try:
            narrate.turn("I wake.", cfg, camp / "transcript.jsonl", camp / "world", camp / "state.json")
        finally:
            llm.chat = orig
        self.assertIn("storm passed", cap["sys"])                        # the recap reached the narrator
        self.assertIsNone(state.load(camp / "state.json").get("_recap"))  # and cleared after one turn


if __name__ == "__main__":
    unittest.main()
