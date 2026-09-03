"""NPC agenda (NPC-agency P2): a goal in motion as a READ-VIEW — goal=canon want, status=relational
thread ripening, remembers=BLESSED-only memory. No writable goal store, so no self-propagation
surface. Offline, deterministic."""
import tempfile
import unittest
from pathlib import Path
from loom import agenda, npc, threads, episodic


def _camp():
    return Path(tempfile.mkdtemp())


def _rel_thread(name, want, readiness=0.0, status="dormant"):
    return threads.Thread(id=threads.make_id(f"{name} {want}"), question=f"Will {name}?",
                          entities=[name], readiness=readiness, status=status)


class PursuitTest(unittest.TestCase):
    def test_empty_without_want_or_rung(self):
        sp = _camp() / "state.json"
        self.assertEqual(agenda.pursuit("Wren", npc.moral_read("", ""), [], sp, 1.0), {})   # no want
        self.assertEqual(agenda.pursuit("Wren", npc.moral_read("to leave", ""), [], sp, 0.0), {})  # rung 0 walk-on

    def test_composes_goal_and_opposition(self):
        sp = _camp() / "state.json"
        m = npc.moral_read("to escape the college", "a vow to her mentor")
        p = agenda.pursuit("Wren", m, [], sp, 1.0)
        self.assertEqual(p["goal"], "to escape the college")
        self.assertIn("vow", p["opposes"])
        self.assertIn("private wish", p["status"])                       # no thread yet → latent wish

    def test_status_tracks_thread_ripening(self):
        sp = _camp() / "state.json"
        m = npc.moral_read("to escape the college", "")
        ripe = _rel_thread("Wren", "to escape the college", readiness=0.8, status="ready")
        p = agenda.pursuit("Wren", m, [ripe], sp, 1.0)
        self.assertIn("at a head", p["status"])                          # readiness>=READY → ready to move
        self.assertEqual(p["readiness"], 0.8)

    def test_remembers_blessed_beats_only(self):
        # the anti-collapse core: a goal read sees only what actually happened, never the NPC's own improv
        camp = _camp(); sp = camp / "state.json"
        episodic.record(sp, [{"what": "Wren copied a warded page", "who": "Wren"}], entry_start=1, source="play")
        episodic.record(sp, [{"what": "Wren imagined slipping out a back door", "who": "Wren"}], entry_start=2, source="world")
        m = npc.moral_read("to escape the college", "")
        p = agenda.pursuit("Wren", m, [], sp, 1.0)
        self.assertEqual(p["remembers"], ["Wren copied a warded page"])   # world improv excluded

    def test_rung_sizes_memory(self):
        camp = _camp(); sp = camp / "state.json"
        for i in range(6):
            episodic.record(sp, [{"what": f"Wren act {i}", "who": "Wren"}], entry_start=i, source="play")
        m = npc.moral_read("to escape", "")
        # a side-tier NPC (rung 0.5 → recall_k 2) remembers fewer beats than a main (rung 1.0 → 4)
        side = agenda.pursuit("Wren", m, [], sp, 0.5)
        main = agenda.pursuit("Wren", m, [], sp, 1.0)
        self.assertEqual(len(side["remembers"]), 2)
        self.assertEqual(len(main["remembers"]), 4)

    def test_pursuit_reads_the_current_stage(self):
        sp = _camp() / "state.json"
        m = npc.moral_read("to escape the college", "")
        th = threads.Thread(id=threads.make_id("Wren to escape the college"), question="q",
                            entities=["Wren"], readiness=0.5, status="ripening",
                            stages=["forge a pass", "bribe the gatekeeper", "slip out at dawn"], stage=1)
        p = agenda.pursuit("Wren", m, [th], sp, 1.0)
        self.assertEqual(p["step"], "bribe the gatekeeper")              # the CURRENT step of the arc
        ln = agenda.line_of(p)
        self.assertIn("wants to escape the college", ln)                # the overall goal…
        self.assertIn("bribe the gatekeeper", ln)                       # …and the step in front

    def test_step_not_read_off_a_borrowed_thread(self):
        # red-team: a co-star's staged thread must NOT graft its concrete step onto an unrelated NPC's goal
        sp = _camp() / "state.json"
        wren = threads.Thread(id=threads.make_id("Wren to escape the college"), question="q",
                              entities=["Wren", "Kael"], readiness=0.5, status="ripening",
                              stages=["forge a pass", "bribe the gatekeeper"], stage=1)
        p = agenda.pursuit("Kael", npc.moral_read("to avenge his brother", ""), [wren], sp, 1.0)   # own_only False
        self.assertEqual(p["step"], "")                                # borrows Wren's thread for status, never her step
        self.assertNotIn("bribe the gatekeeper", agenda.line_of(p))

    def test_pursuit_step_empty_without_stages_or_past_the_end(self):
        sp = _camp() / "state.json"
        m = npc.moral_read("to escape", "")
        plain = agenda.pursuit("Wren", m, [_rel_thread("Wren", "to escape", 0.5, "ripening")], sp, 1.0)
        self.assertEqual(plain["step"], "")                             # no stages → no step
        done = threads.Thread(id=threads.make_id("Wren to escape"), question="q", entities=["Wren"],
                              readiness=0.8, status="ready", stages=["a", "b"], stage=2)   # arc complete
        self.assertEqual(agenda.pursuit("Wren", m, [done], sp, 1.0)["step"], "")


class LineTest(unittest.TestCase):
    def test_line_reads_as_a_pursuit(self):
        camp = _camp(); sp = camp / "state.json"
        episodic.record(sp, [{"what": "Wren copied a warded page", "who": "Wren"}], entry_start=1, source="play")
        m = npc.moral_read("to escape the college", "a vow to her mentor")
        ln = agenda.line("Wren", m, [_rel_thread("Wren", "to escape the college", 0.5, "ripening")], sp, 1.0)
        self.assertIn("Wren wants to escape the college", ln)
        self.assertIn("vow", ln)
        self.assertIn("pressing", ln)                                    # ripening thread
        self.assertIn("copied a warded page", ln)                        # its blessed pursuit history

    def test_line_empty_for_a_walk_on(self):
        sp = _camp() / "state.json"
        self.assertEqual(agenda.line("Extra", npc.moral_read("to loiter", ""), [], sp, 0.0), "")


if __name__ == "__main__":
    unittest.main()
