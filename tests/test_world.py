"""The symbolic-object layer (world.py): facts as (subject, attribute, value) keyed by norm(subject,
attribute), superseded with provenance, grounded into narration gated + byte-identical-off, and folded
through the consolidation diode. Offline, deterministic (unittest)."""
import tempfile
import unittest
from pathlib import Path
from loom import world, state, provenance, consolidate, narrate, config, llm


def _sp():
    return Path(tempfile.mkdtemp()) / "state.json"


class StoreTest(unittest.TestCase):
    def test_first_assertion_then_noop_then_supersede(self):
        sp = _sp()
        d1 = world.set_fact(sp, "the north gate", "state", "locked", since=3)
        self.assertTrue(d1["applied"]); self.assertIsNone(d1["old"])
        d2 = world.set_fact(sp, "the north gate", "state", "locked")     # unchanged
        self.assertFalse(d2["applied"])
        d3 = world.set_fact(sp, "The North Gate", "State", "unlocked")   # norm-keyed → same slot, a CHANGE
        self.assertTrue(d3["applied"]); self.assertEqual(d3["old"], "locked"); self.assertTrue(d3["reversal"])
        facts = world.load(sp)
        self.assertEqual(len(facts), 1)                                 # superseded, not duplicated
        self.assertEqual(facts[0]["value"], "unlocked")

    def test_provenance_logged_on_change_not_on_first(self):
        sp = _sp()
        world.set_fact(sp, "ledger", "condition", "intact")             # first assertion → no ledger row
        self.assertEqual(provenance.entries(sp), [])
        world.set_fact(sp, "ledger", "condition", "burned")             # a CHANGE → old->new row
        rows = provenance.entries(sp)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["kind"], rows[0]["old"], rows[0]["new"]), ("world", "intact", "burned"))

    def test_empty_fields_and_malformed_rejected(self):
        sp = _sp()
        self.assertFalse(world.set_fact(sp, "", "state", "x")["applied"])
        self.assertFalse(world.set_fact(sp, "door", "", "x")["applied"])
        self.assertFalse(world.set_fact(sp, "door", "state", "")["applied"])
        # a hand-corrupted store row is dropped on load, never crashes
        state.save(sp, {"_world": [{"subject": "door", "attribute": "state", "value": "open"}, "junk", {"bad": 1}]})
        self.assertEqual([f["value"] for f in world.load(sp)], ["open"])

    def test_get_and_describe(self):
        sp = _sp()
        world.set_fact(sp, "the sealed key", "holder", "Wren")
        world.set_fact(sp, "the sealed key", "condition", "warm to the touch")
        facts = world.load(sp)
        self.assertEqual(world.get(facts, "the sealed key", "holder"), "Wren")
        self.assertIsNone(world.get(facts, "the sealed key", "owner"))
        self.assertEqual(len(world.get(facts, "sealed key")), 2)        # all attributes of a subject
        self.assertEqual(world.describe({"subject": "the sealed key", "attribute": "holder", "value": "Wren"}),
                         "the sealed key is held by Wren")
        self.assertIn("north gate — mood: uneasy",                      # generic phrasing for an odd attribute
                      world.describe({"subject": "north gate", "attribute": "mood", "value": "uneasy"}))

    def test_remove_retracts_and_logs(self):
        sp = _sp()
        world.set_fact(sp, "gate", "state", "locked")
        self.assertTrue(world.remove(sp, "GATE", "State"))              # norm-keyed retract
        self.assertEqual(world.load(sp), [])
        self.assertFalse(world.remove(sp, "gate", "state"))             # already gone
        self.assertTrue(any(r["new"] == "(retracted)" for r in provenance.entries(sp)))

    def test_empty_norm_subjects_are_unkeyable(self):
        # red-team: a punctuation-only or 'the'-only field norms to '' and would collide on one key slot
        self.assertFalse(world.keyable("...", "state"))
        self.assertFalse(world.keyable("the gate", "!!!"))     # punctuation-only attribute
        self.assertTrue(world.keyable("the gate", "state"))
        sp = _sp()
        self.assertFalse(world.set_fact(sp, "...", "state", "A")["applied"])   # rejected, not stored
        self.assertFalse(world.set_fact(sp, "(!)", "state", "B")["applied"])   # a DISTINCT unkeyable subject
        self.assertEqual(world.load(sp), [])                                   # neither stored → no collision
        # and the diode normalizer drops them too (they aren't just <...> template echoes)
        norm = consolidate._normalize({"world": [{"subject": "...", "attribute": "state", "value": "x"},
                                                 {"subject": "the gate", "attribute": "???", "value": "y"}]})
        self.assertEqual(norm["world"], [])

    def test_retraction_of_sentinel_value_still_records(self):
        # red-team: a fact literally valued '(retracted)' must still log its retraction (marker must differ)
        sp = _sp()
        world.set_fact(sp, "seal", "ward", "(retracted)")
        self.assertTrue(world.remove(sp, "seal", "ward"))
        self.assertTrue(any("retract" in r["new"].lower() for r in provenance.history(sp, name="seal")))

    def test_upsert_is_pure(self):
        facts = [{"subject": "door", "attribute": "state", "value": "open"}]
        out, delta = world.upsert(facts, "door", "state", "closed")
        self.assertTrue(delta["applied"]); self.assertEqual(delta["old"], "open")
        self.assertEqual(facts[0]["value"], "open")                     # input list untouched (pure)
        self.assertEqual([f["value"] for f in out], ["closed"])

    def test_set_bounded(self):
        sp = _sp()
        for i in range(world._MAX_FACTS + 25):
            world.set_fact(sp, f"thing {i}", "state", "here")
        self.assertLessEqual(len(world.load(sp)), world._MAX_FACTS)

    def test_clause_filters_and_caps(self):
        sp = _sp()
        world.set_fact(sp, "the north gate", "state", "locked")
        world.set_fact(sp, "the vault", "state", "sealed")
        facts = world.load(sp)
        self.assertIn("the north gate is locked", world.clause(facts))
        only = world.clause(facts, subjects=["North Gate"])            # norm-matched filter
        self.assertIn("north gate", only)
        self.assertNotIn("vault", only)
        self.assertEqual(world.clause([]), "")

    def test_hidden_fact_excluded_from_visible_clause(self):
        # Brick A: a director-only (hidden) fact is redacted from the character-facing read, kept for the director
        sp = _sp()
        world.set_fact(sp, "the north gate", "state", "locked")                      # visible
        world.set_fact(sp, "the vault", "state", "warded by a sleeping god", hidden=True)  # director-only
        facts = world.load(sp)
        vis = world.clause_visible(facts)
        self.assertIn("north gate", vis)
        self.assertNotIn("vault", vis)                                               # hidden never in the visible read
        hid = world.clause_hidden(facts)
        self.assertIn("vault", hid)                                                  # …but present in the director read
        self.assertNotIn("north gate", hid)

    def test_existing_fact_loads_visible_byte_identical(self):
        # a legacy fact (no 'hidden' key) round-trips through _clean with no key added → stays visible/known
        cleaned = world._clean({"subject": "door", "attribute": "state", "value": "open"})
        self.assertNotIn("hidden", cleaned)                                          # omitted-when-absent
        self.assertIn("door", world.clause_visible([cleaned]))

    def test_hidden_only_when_truthy(self):
        # the load-bearing byte-identical guarantee: the key is written ONLY when truthy
        self.assertNotIn("hidden", world._clean({"subject": "d", "attribute": "s", "value": "x", "hidden": False}))
        self.assertNotIn("hidden", world._clean({"subject": "d", "attribute": "s", "value": "x"}))
        self.assertIs(world._clean({"subject": "d", "attribute": "s", "value": "x", "hidden": True})["hidden"], True)

    def test_upsert_supersede_shares_slot(self):
        # Brick E reveal precondition: a hidden fact and its (value-changing) reveal share ONE slot, not forked
        facts, _ = world.upsert([], "the vault", "state", "sealed", hidden=True)
        self.assertIs(facts[0].get("hidden"), True)
        facts, delta = world.upsert(facts, "The Vault", "State", "open")             # norm-keyed same slot, a change
        self.assertTrue(delta["applied"]); self.assertEqual(delta["old"], "sealed")
        self.assertEqual(len(facts), 1)                                              # superseded in-slot, not forked
        self.assertNotIn("hidden", facts[0])                                         # a value-change supersede clears it


class DiodeTest(unittest.TestCase):
    """world facts fold through the same propose->apply diode as state/reputation, with provenance."""

    def _apply(self, proposals, approve=None, world_dir=None, deed_window=(0, 2), world_state=True):
        camp = Path(tempfile.mkdtemp())
        (camp / "world").mkdir()
        sp = camp / "state.json"
        consolidate.apply(proposals, world_dir or (camp / "world"), sp,
                          approve or (lambda *a: True), deed_window=deed_window, world_state=world_state)
        return sp

    def test_apply_write_is_gated_on_the_toggle(self):
        # off-parity (red-team): apply() must NOT write _world when world_state is off, even if a proposal
        # carries a world array (a fold proposed while ON then drained OFF, or a non-compliant model)
        props = {"world": [{"subject": "gate", "attribute": "state", "value": "locked"}]}
        self.assertEqual(world.load(self._apply(props, world_state=False)), [])          # off → nothing written
        self.assertEqual(world.get(world.load(self._apply(props, world_state=True)), "gate", "state"), "locked")

    def test_world_facts_land_via_apply(self):
        sp = self._apply({"world": [{"subject": "the door", "attribute": "state", "value": "barred"},
                                    {"subject": "the map", "attribute": "holder", "value": "Kess"}]})
        facts = {(f["subject"], f["attribute"]): f["value"] for f in world.load(sp)}
        self.assertEqual(facts[("the door", "state")], "barred")
        self.assertEqual(facts[("the map", "holder")], "Kess")

    def test_change_is_reconciled_not_clobbered(self):
        camp = Path(tempfile.mkdtemp()); (camp / "world").mkdir(); sp = camp / "state.json"
        consolidate.apply({"world": [{"subject": "door", "attribute": "state", "value": "open"}]},
                          camp / "world", sp, lambda *a: True, deed_window=(0, 2), world_state=True)
        consolidate.apply({"world": [{"subject": "door", "attribute": "state", "value": "shattered"}]},
                          camp / "world", sp, lambda *a: True, deed_window=(2, 4), world_state=True)
        self.assertEqual(world.get(world.load(sp), "door", "state"), "shattered")
        rows = provenance.history(sp, name="door")
        self.assertEqual((rows[0]["old"], rows[0]["new"]), ("open", "shattered"))   # logged old->new

    def test_gate_refuses_a_fact(self):
        # the diode: approve("world", ...) returning False drops the fact (nothing written)
        sp = self._apply({"world": [{"subject": "vault", "attribute": "state", "value": "open"}]},
                         approve=lambda kind, *a: kind != "world")
        self.assertEqual(world.load(sp), [])

    def test_object_named_key_is_not_a_placeholder(self):
        # a world subject literally 'key' must survive (unlike a state fact-name — _real_key blocklists it)
        norm = consolidate._normalize({"world": [{"subject": "the key", "attribute": "holder", "value": "Wren"},
                                                 {"subject": "<a thing>", "attribute": "state", "value": "x"}]})
        subs = [w["subject"] for w in norm["world"]]
        self.assertIn("the key", subs)                                  # real object kept
        self.assertNotIn("<a thing>", subs)                            # template echo dropped

    def test_propose_gates_world_on_the_toggle(self):
        # byte-identical-off: the world section reaches the archivist prompt + grammar ONLY when world_state on
        cap = {}
        orig = llm.complete

        def fake(prompt, cfg, **kw):
            cap["prompt"] = prompt
            cap["schema"] = kw.get("response_format", {}).get("json_schema", {}).get("schema", {})
            return '{"summary": "x"}'

        llm.complete = fake
        try:
            consolidate.propose(dict(config.DEFAULTS), [{"role": "player", "text": "hi"}], [], world=None)
            self.assertNotIn('"world"', cap["prompt"])                  # off → no world section…
            self.assertNotIn("[[WORLD", cap["prompt"])                  # …and no leftover token
            self.assertNotIn("world", cap["schema"].get("properties", {}))
            on = dict(config.DEFAULTS); on["world_state"] = True
            consolidate.propose(on, [{"role": "player", "text": "hi"}], [], world=None)
            self.assertIn('"world"', cap["prompt"])                     # on → the world section is present
            self.assertIn("world", cap["schema"].get("properties", {}))
        finally:
            llm.complete = orig


class GroundingTest(unittest.TestCase):
    """narrate._world_clause: gated (byte-identical off), scene-filtered, fenced."""

    def _nodes(self):
        return [{"name": "North Gate", "body": "a heavy iron gate", "score": 1.0,
                 "frontmatter": {"kind": "place"}}]

    def test_off_is_byte_identical(self):
        sp = _sp(); world.set_fact(sp, "the north gate", "state", "locked")
        cfg = dict(config.DEFAULTS)  # world_state defaults False
        self.assertEqual(narrate._world_clause(self._nodes(), sp, "I approach", cfg), "")

    def test_on_grounds_in_scene_facts(self):
        sp = _sp(); world.set_fact(sp, "the north gate", "state", "locked")
        cfg = dict(config.DEFAULTS); cfg["world_state"] = True
        cl = narrate._world_clause(self._nodes(), sp, "I approach the gate", cfg)
        self.assertIn("WORLD STATE", cl)
        self.assertIn("the north gate is locked", cl)

    def test_out_of_scene_fact_excluded(self):
        sp = _sp()
        world.set_fact(sp, "the north gate", "state", "locked")
        world.set_fact(sp, "the sunken vault", "state", "flooded")      # nothing in scene names it
        cfg = dict(config.DEFAULTS); cfg["world_state"] = True
        cl = narrate._world_clause(self._nodes(), sp, "I approach the gate", cfg)
        self.assertIn("north gate", cl)
        self.assertNotIn("vault", cl)

    def test_subject_matches_on_word_boundary(self):
        sp = _sp(); world.set_fact(sp, "key", "holder", "Wren")
        cfg = dict(config.DEFAULTS); cfg["world_state"] = True
        nodes = [{"name": "Room", "body": "a room", "score": 1.0, "frontmatter": {"kind": "place"}}]
        self.assertEqual(narrate._world_clause(nodes, sp, "I pet the monkey", cfg), "")     # 'key' ⊄ 'monkey'
        self.assertIn("key is held by Wren", narrate._world_clause(nodes, sp, "I grab the key", cfg))

    def test_empty_store_is_silent(self):
        sp = _sp()
        cfg = dict(config.DEFAULTS); cfg["world_state"] = True
        self.assertEqual(narrate._world_clause(self._nodes(), sp, "hello", cfg), "")

    def test_hidden_fact_never_reaches_the_world_state_block(self):
        # the diode leak test: with world_state ON, a HIDDEN fact must NOT reach the character-facing block
        sp = _sp()
        world.set_fact(sp, "the north gate", "state", "locked")                              # visible, in scene
        world.set_fact(sp, "north gate", "true nature", "a sealed god's tomb", hidden=True)  # director-only
        cfg = dict(config.DEFAULTS); cfg["world_state"] = True
        cl = narrate._world_clause(self._nodes(), sp, "I approach the gate", cfg)
        self.assertIn("the north gate is locked", cl)                                        # visible fact grounds
        self.assertNotIn("tomb", cl)                                                         # hidden fact never leaks


if __name__ == "__main__":
    unittest.main()
