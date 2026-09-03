"""NPC↔NPC standing (npc_standing.py): a symmetric standing per pair, folded through the consolidation
diode like reputation, grounding the world round + narration + the mind panel. Default-OFF. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import npc_standing, consolidate, config, canon, state, character


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class StoreTest(unittest.TestCase):
    def test_pair_key_symmetric_and_rejects_same(self):
        self.assertEqual(npc_standing.pair_key("Wren", "Faelan"), npc_standing.pair_key("Faelan", "Wren"))
        self.assertIsNone(npc_standing.pair_key("Wren", "Wren"))              # a standing needs two people
        self.assertIsNone(npc_standing.pair_key("Wren", ""))
        self.assertIsNone(npc_standing.pair_key("the Wren", "Wren"))          # norm-collide → same entity → None

    def test_apply_delta_clamps_and_reads_symmetric(self):
        store = {}
        npc_standing.apply_delta(store, "Wren", "Faelan", -2, "they clashed over the ward")
        self.assertEqual(npc_standing.between(store, "Faelan", "Wren"), -2)   # symmetric read
        npc_standing.apply_delta(store, "Faelan", "Wren", -2, "and again")    # clamps at -CLAMP
        self.assertEqual(npc_standing.between(store, "Wren", "Faelan"), -3)
        self.assertEqual(npc_standing.label(-3), "enemies")

    def test_invalid_delta_is_a_noop(self):
        store = {}
        npc_standing.apply_delta(store, "Wren", "Wren", 2, "self")            # same entity
        npc_standing.apply_delta(store, "Wren", "Faelan", "x", "bad delta")   # non-int delta
        self.assertEqual(store, {})

    def test_of_lists_relationships_worst_first(self):
        store = {}
        npc_standing.apply_delta(store, "Wren", "Faelan", -2, "a rivalry")
        npc_standing.apply_delta(store, "Wren", "Kess", 3, "sworn allies")
        rels = npc_standing.of(store, "Wren")
        self.assertEqual([r["other"] for r in rels], ["Faelan", "Kess"])      # worst first
        self.assertEqual(rels[0]["standing"], -2)

    def test_clause_only_among_present_nonneutral(self):
        store = {}
        npc_standing.apply_delta(store, "Wren", "Faelan", -2, "clashed")
        cl = npc_standing.clause(store, ["Wren", "Faelan", "Kess"])
        self.assertIn("hostile", cl)
        self.assertIn("Wren", cl); self.assertIn("Faelan", cl)
        self.assertEqual(npc_standing.clause(store, ["Wren", "Kess"]), "")    # Faelan absent → no pair present


class DiodeTest(unittest.TestCase):
    def _apply(self, proposals, on=True, dw=(0, 2)):
        camp = _camp(); sp = camp / "state.json"
        consolidate.apply(proposals, camp / "world", sp, lambda *a: True, deed_window=dw, npc_standing_on=on)
        return sp

    def test_folds_when_on(self):
        sp = self._apply({"npc_standing": [{"a": "Wren", "b": "Faelan", "delta": -2, "because": "clashed"}]})
        self.assertEqual(npc_standing.between(npc_standing.load(state.load(sp)), "Wren", "Faelan"), -2)

    def test_gated_off_writes_nothing(self):
        sp = self._apply({"npc_standing": [{"a": "Wren", "b": "Faelan", "delta": -2, "because": "x"}]}, on=False)
        self.assertEqual(npc_standing.load(state.load(sp)), {})               # byte-identical-off

    def test_normalize_drops_same_zero_and_template(self):
        n = consolidate._normalize({"npc_standing": [
            {"a": "Wren", "b": "Wren", "delta": 2},        # same entity
            {"a": "A", "b": "B", "delta": 0},              # no-op delta
            {"a": "<x>", "b": "B", "delta": 1},            # template echo
            {"a": "A", "b": "B", "delta": 1, "because": "y"}]})
        self.assertEqual([(s["a"], s["b"]) for s in n["npc_standing"]], [("A", "B")])

    def test_refold_of_a_window_is_idempotent(self):
        camp = _camp(); sp = camp / "state.json"
        props = {"npc_standing": [{"a": "Wren", "b": "Faelan", "delta": -2, "because": "clashed"}]}
        consolidate.apply(props, camp / "world", sp, lambda *a: True, deed_window=(0, 2), npc_standing_on=True)
        consolidate.apply(props, camp / "world", sp, lambda *a: True, deed_window=(0, 2), npc_standing_on=True)
        self.assertEqual(npc_standing.between(npc_standing.load(state.load(sp)), "Wren", "Faelan"), -2)   # not -4


class GroundingTest(unittest.TestCase):
    def test_interior_includes_standings(self):
        camp = _camp()
        canon.write_node(camp / "world", "Wren", "a cadet", {"kind": "character"})
        canon.write_node(camp / "world", "Faelan", "a mentor", {"kind": "character"})
        sp, tp = camp / "state.json", camp / "t.jsonl"
        store = {}
        npc_standing.apply_delta(store, "Wren", "Faelan", -2, "clashed over the ward")
        state.save(sp, {"_npc_standing": store})
        node = canon.read_node(camp / "world", "Wren")
        interior = character.interior(camp / "world", tp, sp, dict(config.DEFAULTS), node)
        self.assertTrue(any(s["other"] == "Faelan" and s["standing"] == -2 for s in interior["standings"]))


if __name__ == "__main__":
    unittest.main()
