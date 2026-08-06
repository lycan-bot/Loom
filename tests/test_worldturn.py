"""The world round: major NPCs grouped by location take turns advancing their agendas —
co-located NPCs couple into an interaction, the rest act solo. Propose-only. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import worldturn, canon, npc, llm, config


def _world():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d / "world"


class MajorsTest(unittest.TestCase):
    def test_only_characters_with_a_want(self):
        w = _world()
        canon.write_node(w, "Mara", "a fisher", {"kind": "character", "wants": "to leave", "location": "Harbor"})
        canon.write_node(w, "Silent", "a mute", {"kind": "character"})         # no want → not major
        canon.write_node(w, "Harbor", "a dock", {"kind": "place"})             # place → not a character
        ms = worldturn.majors(w)
        self.assertEqual([n["name"] for n, _m, _l in ms], ["Mara"])
        self.assertEqual(ms[0][2], "Harbor")                                   # explicit location

    def test_location_bootstraps_from_a_place_link(self):
        w = _world()
        canon.write_node(w, "Harbor", "a dock", {"kind": "place"})
        canon.write_node(w, "Jonah", "a sailor who haunts the [[Harbor]]",
                         {"kind": "character", "wants": "a berth"})            # no location field
        self.assertEqual(worldturn.majors(w)[0][2], "Harbor")                  # seeded from the link

    def test_unknown_location_when_nothing_says_where(self):
        w = _world()
        canon.write_node(w, "Wanderer", "no fixed abode", {"kind": "character", "wants": "to find home"})
        self.assertEqual(worldturn.majors(w)[0][2], "")


class GroupsTest(unittest.TestCase):
    def _maj(self, name, loc, want="something", bound=""):
        node = {"name": name, "frontmatter": {"kind": "character", "wants": want}, "body": "", "links": []}
        return (node, npc.moral_read(want, bound), loc)

    def test_shared_location_couples_others_solo(self):
        gs = worldturn.groups([self._maj("A", "Tavern"), self._maj("B", "Tavern"), self._maj("C", "Docks")])
        self.assertEqual(sorted(len(g) for g in gs), [1, 2])
        self.assertEqual(len(gs[0]), 2)                                        # interaction ordered first
        self.assertEqual({n["name"] for n, _m, _l in gs[0]}, {"A", "B"})

    def test_unknown_locations_do_not_couple(self):
        gs = worldturn.groups([self._maj("A", ""), self._maj("B", "")])       # 'unknown' is not a place
        self.assertEqual([len(g) for g in gs], [1, 1])                         # both act solo


class RunTest(unittest.TestCase):
    def test_turns_parsed_and_model_output_sanitized(self):
        w = _world()
        canon.write_node(w, "Tavern", "a tavern", {"kind": "place"})
        canon.write_node(w, "Rook", "a rogue", {"kind": "character", "wants": "the ledger", "location": "Tavern"})
        canon.write_node(w, "Vane", "a guard", {"kind": "character", "wants": "to catch the thief", "location": "Tavern"})
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0
        orig = llm.complete
        llm.complete = lambda *a, **k: ('{"turns":[{"where":"Tavern","who":["Rook","Vane"],'
                                        '"beat":"They eye each other over the bar."},{"beat":123}]}')
        try:
            r = worldturn.run(cfg, w)
        finally:
            llm.complete = orig
        self.assertEqual(len(r["turns"]), 1)                                   # the beat:123 (non-str) dropped
        self.assertEqual(r["turns"][0]["who"], ["Rook", "Vane"])
        self.assertIn("eye each other", r["turns"][0]["beat"])
        self.assertTrue(r["pending"])

    def test_no_majors_is_not_pending(self):
        w = _world()
        canon.write_node(w, "Harbor", "a dock", {"kind": "place"})
        self.assertEqual(worldturn.run(dict(config.DEFAULTS), w), {"turns": [], "pending": False})

    def test_model_failure_is_pending_but_empty(self):
        w = _world()
        canon.write_node(w, "Rook", "a rogue", {"kind": "character", "wants": "gold"})
        orig = llm.complete
        def boom(*a, **k):
            raise RuntimeError("server down")
        llm.complete = boom
        try:
            r = worldturn.run(dict(config.DEFAULTS), w)
        finally:
            llm.complete = orig
        self.assertEqual(r["turns"], [])
        self.assertTrue(r["pending"])                                          # actors existed → retryable


class MaybeRoundTest(unittest.TestCase):
    def _drived(self):
        w = _world()
        canon.write_node(w, "Tavern", "a tavern", {"kind": "place"})
        canon.write_node(w, "Rook", "a rogue", {"kind": "character", "wants": "the ledger", "location": "Tavern"})
        return w

    def test_toggle_off_never_runs(self):
        w = self._drived()
        cfg = dict(config.DEFAULTS); cfg["world_rounds"] = False; cfg["depth"] = 1.0
        self.assertEqual(worldturn.maybe_round(cfg, w, w.parent / "state.json"), [])

    def test_depth_zero_never_runs(self):
        w = self._drived()
        cfg = dict(config.DEFAULTS); cfg["world_rounds"] = True; cfg["depth"] = 0.0
        self.assertEqual(worldturn.maybe_round(cfg, w, w.parent / "state.json"), [])

    def test_fires_only_on_cadence(self):
        w = self._drived()
        cfg = dict(config.DEFAULTS); cfg["world_rounds"] = True; cfg["depth"] = 1.0; cfg["world_cadence"] = 2
        sp = w.parent / "state.json"
        orig = llm.complete
        llm.complete = lambda *a, **k: '{"turns":[{"where":"Tavern","who":["Rook"],"beat":"He pockets a key."}]}'
        try:
            self.assertEqual(worldturn.maybe_round(cfg, w, sp), [])       # turn 1 — not due
            r2 = worldturn.maybe_round(cfg, w, sp)                        # turn 2 — due
        finally:
            llm.complete = orig
        self.assertTrue(r2 and "pockets a key" in r2[0]["beat"])


if __name__ == "__main__":
    unittest.main()
