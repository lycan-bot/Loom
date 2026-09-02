"""NPC-agency integration (P4): the world round becomes tier-aware and goal-continuous — a walk-on
doesn't take a turn, a character with the personhood budget gets its agenda (goal + blessed memory)
injected, and a high-rung focal character DELIBERATES before acting. Offline (model stubbed)."""
import tempfile
import unittest
from pathlib import Path
from loom import worldturn, canon, episodic, config, llm, narrate, threads


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


def _world(camp):
    w = camp / "world"
    canon.write_node(w, "Library", "a vast warded library", {"kind": "place"})
    canon.write_node(w, "Wren", "a sharp cadet", {"kind": "character", "importance": "main",
                                                  "wants": "to escape the college", "bound": "a vow to her mentor",
                                                  "location": "Library"})
    canon.write_node(w, "Extra", "a nameless porter", {"kind": "character", "importance": "passing",
                                                       "wants": "to loiter", "location": "Library"})
    return w


class AgencyIntegrationTest(unittest.TestCase):
    def _run(self, camp, cfg):
        tp, sp = camp / "transcript.jsonl", camp / "state.json"
        calls = []
        orig = llm.complete

        def fake(prompt, c, **kw):
            calls.append(prompt)
            if kw.get("response_format"):                     # the batched beat call
                return '{"turns":[{"where":"Library","who":["Wren"],"beat":"Wren pockets a warded page."}]}'
            return "I will slip into the archive tonight and copy the ward."   # the deliberation call

        llm.complete = fake
        try:
            out = worldturn.run(cfg, camp / "world", tpath=tp, spath=sp)
        finally:
            llm.complete = orig
        return out, calls

    def test_walkon_is_not_cast_but_main_is(self):
        camp = _camp(); _world(camp)
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0
        _out, calls = self._run(camp, cfg)
        beat_prompt = next(p for p in calls if "THIS ROUND" in p)
        actors = beat_prompt.split("THIS ROUND")[1].split("CANON")[0]   # the cast block, not canon grounding
        self.assertIn("Wren", actors)                         # a main character acts…
        self.assertNotIn("Extra", actors)                     # …a passing walk-on (rung 0) does not

    def test_agenda_injected_into_the_round(self):
        camp = _camp(); _world(camp)
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0
        _out, calls = self._run(camp, cfg)
        beat_prompt = next(p for p in calls if "THIS ROUND" in p)
        self.assertIn("Wren wants to escape the college", beat_prompt)     # the goal, not just a name
        self.assertIn("vow to her mentor", beat_prompt)                    # what holds them back

    def test_focal_character_deliberates(self):
        camp = _camp(); _world(camp)
        sp = camp / "state.json"
        episodic.record(sp, [{"what": "Wren copied a warded page", "who": "Wren"}], entry_start=1, source="play")
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0
        _out, calls = self._run(camp, cfg)
        delib = [p for p in calls if "state your INTENT" in p]
        self.assertEqual(len(delib), 1)                       # exactly one think-pass for the focal main
        self.assertIn("You are Wren", delib[0])
        self.assertIn("to escape the college", delib[0])
        self.assertIn("copied a warded page", delib[0])       # deliberates from its BLESSED memory
        beat_prompt = next(p for p in calls if "THIS ROUND" in p)
        self.assertIn("intent this round", beat_prompt)       # the intent is fed into the beat

    def test_mood_colors_the_world_round_line(self):
        # R3: a disposition'd lead's mood is composed into its world-round actor line
        camp = _camp()
        canon.write_node(camp / "world", "Library", "a library", {"kind": "place"})
        canon.write_node(camp / "world", "Wren", "a cadet", {"kind": "character", "importance": "main",
                                                             "wants": "to escape", "location": "Library",
                                                             "disposition": "warm and fond of the player"})
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0
        _out, calls = self._run(camp, cfg)
        actors = next(p for p in calls if "THIS ROUND" in p).split("THIS ROUND")[1].split("CANON")[0]
        self.assertIn("Wren feels", actors)
        self.assertIn("warm toward you", actors)

    def test_no_deliberation_at_low_depth(self):
        # at depth 0.5 Wren is main → rung 0.5: has an agenda, but below the deliberation threshold (0.75)
        camp = _camp(); _world(camp)
        cfg = dict(config.DEFAULTS); cfg["depth"] = 0.5
        _out, calls = self._run(camp, cfg)
        self.assertEqual([p for p in calls if "state your INTENT" in p], [])   # no extra think-call
        beat_prompt = next(p for p in calls if "THIS ROUND" in p)
        self.assertIn("Wren wants to escape", beat_prompt)    # still agenda-injected (rung 0.5 >= 0.5)

    def test_cast_cap_keeps_the_lead_not_the_biggest_group(self):
        # red-team HIGH: at a tight cast cap, the highest-rung actor must survive — not the largest group
        camp = _camp()
        w = camp / "world"
        canon.write_node(w, "Peak", "a lonely peak", {"kind": "place"})
        canon.write_node(w, "Inn", "a crowded inn", {"kind": "place"})
        canon.write_node(w, "Hero", "the lead", {"kind": "character", "importance": "main",
                                                 "wants": "to reach the summit", "location": "Peak"})
        canon.write_node(w, "S1", "an extra", {"kind": "character", "importance": "side",
                                               "wants": "to gossip", "location": "Inn"})
        canon.write_node(w, "S2", "an extra", {"kind": "character", "importance": "side",
                                               "wants": "to gossip", "location": "Inn"})
        cfg = dict(config.DEFAULTS); cfg["depth"] = 0.1        # cap = round(1 + 0.4) = 1 group
        _out, calls = self._run(camp, cfg)
        actors = next(p for p in calls if "THIS ROUND" in p).split("THIS ROUND")[1].split("CANON")[0]
        self.assertIn("Hero", actors)                         # the lead survives the cap…
        self.assertNotIn("S1", actors)                        # …not the larger, lower-tier group

    def test_legacy_path_has_no_agency_layer(self):
        # run() without paths (the legacy/test entrypoint) keeps the old flat behavior — no agenda, no deliberation
        camp = _camp(); _world(camp)
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0
        calls = []
        orig = llm.complete
        llm.complete = lambda prompt, c, **kw: (calls.append(prompt),
                                                '{"turns":[]}' if kw.get("response_format") else "x")[1]
        try:
            worldturn.run(cfg, camp / "world")                # no tpath/spath
        finally:
            llm.complete = orig
        self.assertEqual([p for p in calls if "state your INTENT" in p], [])   # no deliberation
        beat_prompt = next(p for p in calls if "THIS ROUND" in p)
        self.assertNotIn("Their pursuit is", beat_prompt)     # the agenda layer is the agency marker, absent here


class RemembersYouTest(unittest.TestCase):
    """R2: an in-scene NPC's BLESSED memory of the player is surfaced to the narrator, rung-gated."""

    def _scene(self, camp):
        w = camp / "world"
        canon.write_node(w, "Kess", "the player", {"kind": "character", "player": "true"})
        canon.write_node(w, "Wren", "a cadet", {"kind": "character", "importance": "main"})
        sp, tp = camp / "state.json", camp / "transcript.jsonl"
        episodic.record(sp, [{"what": "Wren gave Kess the sealed key", "who": ["Wren", "Kess"]}], entry_start=1, source="play")
        wren = canon.read_node(w, "Wren"); wren["score"] = 1.0     # as retrieve returns an in-scene match
        kess = canon.read_node(w, "Kess"); kess["score"] = 1.0
        return w, tp, sp, [wren, kess]

    def test_in_scene_npc_remembers_the_player(self):
        camp = _camp(); w, tp, sp, nodes = self._scene(camp)
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0
        cl = narrate._remembers_you_clause(nodes, w, tp, sp, cfg)
        self.assertIn("Wren remembers of you", cl)
        self.assertIn("gave Kess the sealed key", cl)

    def test_silent_at_depth_zero(self):
        camp = _camp(); w, tp, sp, nodes = self._scene(camp)
        cfg = dict(config.DEFAULTS); cfg["depth"] = 0.0
        self.assertEqual(narrate._remembers_you_clause(nodes, w, tp, sp, cfg), "")   # off → byte-identical


class PursuesThroughYouTest(unittest.TestCase):
    """Goals-pursued-through-you: an in-scene NPC with a LIVE agenda (a ripened relational thread) works
    toward its goal THROUGH the player, sized by rung; a dormant wish and a walk-on stay inert."""

    def _scene(self, camp, importance="main", want="to escape the college", bound="a vow to her mentor", ripe=True):
        w = camp / "world"
        canon.write_node(w, "Kess", "the player", {"kind": "character", "player": "true"})
        fm = {"kind": "character", "importance": importance, "wants": want}
        if bound:
            fm["bound"] = bound
        canon.write_node(w, "Wren", "a cadet", fm)
        sp, tp = camp / "state.json", camp / "transcript.jsonl"
        episodic.record(sp, [{"what": "Wren copied a warded page", "who": "Wren"}], entry_start=1, source="play")
        if ripe:                                     # a director-ripened relational thread → the pursuit is LIVE
            th = threads.Thread(id=threads.make_id(f"Wren {want}"), question="Will Wren escape?",
                                entities=["Wren"], readiness=0.5, status="ripening")
            threads.save(sp.parent / "threads.json", [th])
        wren = canon.read_node(w, "Wren"); wren["score"] = 1.0
        kess = canon.read_node(w, "Kess"); kess["score"] = 1.0
        return w, tp, sp, [wren, kess]

    def test_live_agenda_pursued_through_you(self):
        camp = _camp(); w, tp, sp, nodes = self._scene(camp)
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0
        cl = narrate._pursues_clause(nodes, w, tp, sp, cfg)
        self.assertIn("Wren wants to escape the college", cl)     # the live goal, not just a name
        self.assertIn("In this scene Wren", cl)                   # pursued IN THE SCENE with the player
        self.assertIn("actively works toward it", cl)             # rung 1.0 → the deliberation tier maneuvers
        self.assertIn("copied a warded page", cl)                 # grounded in its BLESSED pursuit history
        self.assertIn("never have them baldly announce", cl)      # the hidden-goal discipline is in the framing

    def test_silent_at_depth_zero(self):
        camp = _camp(); w, tp, sp, nodes = self._scene(camp)
        cfg = dict(config.DEFAULTS); cfg["depth"] = 0.0
        self.assertEqual(narrate._pursues_clause(nodes, w, tp, sp, cfg), "")   # off → byte-identical

    def test_walkon_carries_no_agenda(self):
        camp = _camp()
        w = camp / "world"
        canon.write_node(w, "Kess", "the player", {"kind": "character", "player": "true"})
        canon.write_node(w, "Extra", "a porter", {"kind": "character", "importance": "passing", "wants": "to loiter"})
        sp, tp = camp / "state.json", camp / "transcript.jsonl"
        extra = canon.read_node(w, "Extra"); extra["score"] = 1.0
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0
        self.assertEqual(narrate._pursues_clause([extra], w, tp, sp, cfg), "")   # rung 0 → no will in the scene

    def test_dormant_wish_is_not_pursued(self):
        # a main with a want but NO ripened thread — a private wish, not yet in motion → left inert
        camp = _camp(); w, tp, sp, nodes = self._scene(camp, ripe=False)
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0
        self.assertEqual(narrate._pursues_clause(nodes, w, tp, sp, cfg), "")

    def test_mid_rung_leans_high_rung_maneuvers(self):
        # a side character at full depth is rung 0.5 — has an agenda, but below the deliberation tier (0.75)
        camp = _camp(); w, tp, sp, nodes = self._scene(camp, importance="side")
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0
        cl = narrate._pursues_clause(nodes, w, tp, sp, cfg)
        self.assertIn("leans toward it", cl)
        self.assertNotIn("actively works toward it", cl)


if __name__ == "__main__":
    unittest.main()
