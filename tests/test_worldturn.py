"""The world round: major NPCs grouped by location take turns advancing their agendas —
co-located NPCs couple into an interaction, the rest act solo. Propose-only. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import worldturn, canon, npc, llm, config, threads


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

    def test_non_list_model_output_does_not_crash(self):
        # the (x or []) idiom would pass a scalar into a `for` — a non-list turns/who must fail soft
        w = _world()
        canon.write_node(w, "Rook", "a rogue", {"kind": "character", "wants": "gold"})
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0
        orig = llm.complete
        try:
            for payload in ('{"turns": 5}', '{"turns": true}', '{"turns":[{"who":5,"beat":"x"}]}'):
                llm.complete = lambda *a, **k: payload
                self.assertIsInstance(worldturn.run(cfg, w)["turns"], list)     # no TypeError
            llm.complete = lambda *a, **k: '{"turns":[{"who":"Rook","beat":"y"}]}'
            self.assertEqual(worldturn.run(cfg, w)["turns"][0]["who"], [])      # string who dropped, not 'R,o,o,k'
        finally:
            llm.complete = orig

    def test_corrupt_canon_file_does_not_crash_a_round(self):
        w = _world()
        canon.write_node(w, "Rook", "a rogue", {"kind": "character", "wants": "gold"})
        (w / "corrupt.md").write_bytes(b"---\ntitle: X\n---\n\n\xff\xfe bad bytes")
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0
        orig = llm.complete
        llm.complete = lambda *a, **k: '{"turns":[]}'
        try:
            worldturn.run(cfg, w)                          # canon.load_all must not choke on bad bytes
        finally:
            llm.complete = orig

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


class HorizonUneaseTest(unittest.TestCase):
    """Brick C: the world's people feel an escalating, unnamed dread as the blessed horizon clock nears —
    a pure clock read, gated on cfg.horizon, that never names the hidden threat."""

    def _clock(self, clock, span=10, scope="horizon", status="ripening", hidden=True):
        return threads.Thread(id="h", question="the sleeping god wakes", kind="clock", status=status,
                              clock=clock, span=span, scope=scope, hidden=hidden)

    def test_off_and_no_clock_are_byte_identical(self):
        self.assertEqual(worldturn._horizon_unease(dict(config.DEFAULTS), [self._clock(1)]), "")   # toggle off
        on = dict(config.DEFAULTS); on["horizon"] = True
        self.assertEqual(worldturn._horizon_unease(on, [self._clock(1, scope="local")]), "")       # local clock ignored
        self.assertEqual(worldturn._horizon_unease(on, [self._clock(1, hidden=False)]), "")        # KNOWN horizon: no unnamed dread
        self.assertEqual(worldturn._horizon_unease(on, []), "")                                     # no clock → ''

    def test_escalates_and_never_names_the_threat(self):
        on = dict(config.DEFAULTS); on["horizon"] = True
        far = worldturn._horizon_unease(on, [self._clock(10, span=10)])     # near 0 → faint
        near = worldturn._horizon_unease(on, [self._clock(1, span=10)])     # near 0.9 → oppressive
        self.assertTrue(far and near and far != near)                       # non-empty and escalating
        self.assertNotIn("god wakes", far + near)                           # the hidden threat is never named

    def test_unease_reaches_the_round_prompt(self):
        w = _world()
        canon.write_node(w, "Rook", "a rogue", {"kind": "character", "wants": "gold"})
        threads.save(w.parent / "threads.json", [self._clock(1, span=10)])
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0; cfg["horizon"] = True
        cap = {}
        orig = llm.complete
        llm.complete = lambda prompt, c, **k: (cap.__setitem__("p", prompt), '{"turns":[]}')[1]
        try:
            worldturn.run(cfg, w, tpath=w.parent / "transcript.jsonl", spath=w.parent / "state.json")
        finally:
            llm.complete = orig
        self.assertIn("dread", cap["p"].lower())          # the world feels the coming horizon…
        self.assertNotIn("god wakes", cap["p"])           # …but the specific threat is never stated


if __name__ == "__main__":
    unittest.main()
