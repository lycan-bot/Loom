"""Steer weight engine (Phase 0): the register EASES toward its target over turns (a reactive curve),
snaps harder on a big scene-shift, and persists to state _steer. compose() collapses to the one scalar
the server takes. Off via tone_steer → nothing written. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import steer, tone, narrate, canon, state, llm, config


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class EngineTest(unittest.TestCase):
    def test_read_and_compose(self):
        self.assertEqual(steer.read({"_steer": {"tone": 2.0}}), {"tone": 2.0})
        self.assertEqual(steer.read({}), {})
        self.assertEqual(steer.compose({"tone": 2.0}), 2.0)
        self.assertIsNone(steer.compose({}))

    def test_step_eases_toward_target_over_turns(self):
        camp = _camp()
        canon.write_node(camp / "world", "World", "grim cosmic horror",
                         {"kind": "lore", "setting": "true", "genre": "grim cosmic horror", "tone": "bleak dread"})
        w = camp / "world"
        baseline, target = tone.scale(w, 0.2), tone.scale(w, 0.45)
        w1 = steer.step(w, {}, 0.45)                                   # first grim turn
        self.assertGreater(w1["tone"], baseline)                      # moved toward the grim target
        self.assertLess(w1["tone"], target)                           # but eased, not snapped
        w2 = steer.step(w, {"_steer": w1}, 0.45)                      # sustained grim
        self.assertGreater(w2["tone"], w1["tone"])                    # keeps ramping toward target
        self.assertLessEqual(w2["tone"], target)

    def test_step_snaps_on_a_big_scene_shift(self):
        camp = _camp()
        canon.write_node(camp / "world", "World", "grim horror",
                         {"kind": "lore", "setting": "true", "genre": "grim horror"})
        was_warm = {"_steer": {"tone": -3.0}}
        w = steer.step(camp / "world", was_warm, 0.45)                # a big warm→grim jump snaps harder
        self.assertGreater(w["tone"], 0.0)                            # crossed well into grim in one turn


class NarrateTest(unittest.TestCase):
    def test_persists_smoothed_steer_when_on(self):
        camp = _camp()
        canon.write_node(camp / "world", "World", "grim horror",
                         {"kind": "lore", "setting": "true", "genre": "grim horror"})
        state.save(camp / "state.json", {"_tension": 0.45})
        cfg = dict(config.DEFAULTS); cfg["tone_steer"] = True
        cap = {}
        orig = llm.chat
        llm.chat = lambda m, c, **k: (cap.__setitem__("scale", k.get("control_vector_scale")), "A grim beat.")[1]
        try:
            narrate.turn("I enter.", cfg, camp / "t.jsonl", camp / "world", camp / "state.json")
        finally:
            llm.chat = orig
        self.assertIn("tone", state.load(camp / "state.json").get("_steer", {}))   # weight persisted
        self.assertIsNotNone(cap["scale"])                                         # a scale reached the model

    def test_nothing_when_off(self):
        camp = _camp()
        canon.write_node(camp / "world", "World", "x", {"kind": "lore"})
        state.save(camp / "state.json", {})
        cfg = dict(config.DEFAULTS); cfg["tone_steer"] = False
        cap = {}
        orig = llm.chat
        llm.chat = lambda m, c, **k: (cap.__setitem__("scale", k.get("control_vector_scale")), "ok.")[1]
        try:
            narrate.turn("hi", cfg, camp / "t.jsonl", camp / "world", camp / "state.json")
        finally:
            llm.chat = orig
        self.assertNotIn("_steer", state.load(camp / "state.json"))                # nothing written
        self.assertIsNone(cap["scale"])                                            # no scale sent


class ShatterTest(unittest.TestCase):
    def test_shattered_detects_degeneration_and_spares_prose(self):
        self.assertTrue(steer.shattered("1 1 1 1 1 1 1 1 1 1 1 1 1 1"))               # the '1 1 1' attractor
        self.assertTrue(steer.shattered("cold cold cold cold cold cold cold cold dark dark dark dark"))  # tiny vocab
        self.assertFalse(steer.shattered("The lantern gutters as Wren steps into the vault, blade drawn."))
        self.assertFalse(steer.shattered("too short to be judged"))                  # under the min length

    def test_declamp_eases_toward_neutral(self):
        self.assertEqual(steer.declamp(4.0), 2.0)
        self.assertEqual(steer.declamp(-3.0), -1.5)
        self.assertIsNone(steer.declamp(None))

    def test_runtime_clamp_rerolls_a_shattered_generation(self):
        camp = _camp()
        canon.write_node(camp / "world", "World", "grim horror",
                         {"kind": "lore", "setting": "true", "genre": "grim horror"})
        state.save(camp / "state.json", {"_tension": 0.9})
        cfg = dict(config.DEFAULTS); cfg["tone_steer"] = True; cfg["depth"] = 0   # depth 0 → no referee model call
        scales = []
        outs = iter(["1 1 1 1 1 1 1 1 1 1 1 1 1", "A steady, grim beat unfolds in the hall."])
        orig = llm.chat

        def fake(m, c, **k):
            scales.append(k.get("control_vector_scale"))
            return next(outs)

        llm.chat = fake
        try:
            final = narrate.turn("I enter.", cfg, camp / "t.jsonl", camp / "world", camp / "state.json")
        finally:
            llm.chat = orig
        self.assertIn("grim beat", final)              # the clean re-roll reached the player, not the shatter
        self.assertEqual(len(scales), 2)               # exactly one clamp re-roll
        self.assertEqual(scales[1], steer.declamp(scales[0]))   # re-rolled at a scale eased toward neutral

    def test_dramatic_repetition_is_not_shatter(self):
        # red-team: legitimate dramatic repetition keeps a rich vocabulary → the run alone must not fire
        self.assertFalse(steer.shattered(
            "Knock. Knock. Knock. Knock. Knock. The sound came from behind the sealed cellar door, patient and cold."))
        self.assertFalse(steer.shattered(
            "No, no, no, no, no, she whispered, backing away from the shape rising in the doorway."))
        self.assertTrue(steer.shattered(                                   # a run + a collapsing vocabulary → still caught
            "alpha beta gamma delta one one one one one one one one"))

    def test_score_zero_fallback_place_does_not_flip_the_register(self):
        # red-team: a score-0 retrieval fallback (a cozy place the player isn't at) must not flip the tone vector
        from loom import retrieve
        camp = _camp()
        canon.write_node(camp / "world", "World", "grim horror",
                         {"kind": "lore", "setting": "true", "genre": "grim horror"})
        canon.write_node(camp / "world", "Cottage", "a cozy cottage", {"kind": "place", "tone": "cozy"})
        state.save(camp / "state.json", {"_tension": 0.15})
        cfg = dict(config.DEFAULTS); cfg["tone_steer"] = True; cfg["depth"] = 0
        cozy = canon.read_node(camp / "world", "Cottage"); cozy["score"] = 0.0     # a fallback, not near
        worldn = canon.read_node(camp / "world", "World"); worldn["score"] = 0.0
        cap = {}
        orig_r, orig_c = retrieve.retrieve, llm.chat
        retrieve.retrieve = lambda *a, **k: [cozy, worldn]
        llm.chat = lambda m, c, **k: (cap.__setitem__("scale", k.get("control_vector_scale")), "A grim beat.")[1]
        try:
            narrate.turn("hmm ok well", cfg, camp / "t.jsonl", camp / "world", camp / "state.json")
        finally:
            retrieve.retrieve = orig_r; llm.chat = orig_c
        self.assertGreater(cap["scale"], 0)          # grim-world baseline (positive), not the cozy override (negative)

    def test_no_reroll_when_steering_off(self):
        # byte-identical when off: a shattered-looking output is NOT re-rolled if steering isn't active
        cfg = dict(config.DEFAULTS); cfg["tone_steer"] = False
        calls = []
        orig = llm.chat
        llm.chat = lambda m, c, **k: (calls.append(1), "x")[1]
        try:
            out = narrate._declamp_if_shattered("1 1 1 1 1 1 1 1 1 1 1 1", ["m"], None, cfg)
        finally:
            llm.chat = orig
        self.assertEqual(out, "1 1 1 1 1 1 1 1 1 1 1 1")
        self.assertEqual(calls, [])                     # no model call


if __name__ == "__main__":
    unittest.main()
