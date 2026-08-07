"""The tone scalar: genre + location tone + the tension homeostat → a clamped control-vector scale,
and narrate sends it only when tone_steer is on. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import tone, canon, narrate, llm, config


def _world():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d / "world"


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class ToneScaleTest(unittest.TestCase):
    def test_horror_genre_leans_dread(self):
        w = _world()
        canon.write_node(w, "W", "x", {"kind": "lore", "setting": "true", "genre": "cosmic horror"})
        self.assertGreater(tone.scale(w, 0.15), 0)

    def test_cozy_genre_leans_warm(self):
        w = _world()
        canon.write_node(w, "W", "x", {"kind": "lore", "setting": "true", "genre": "cozy slice-of-life"})
        self.assertLess(tone.scale(w, 0.1), 0)

    def test_rising_tension_pushes_grimmer(self):
        w = _world()
        canon.write_node(w, "W", "x", {"kind": "lore", "setting": "true", "genre": "cozy"})
        self.assertGreater(tone.scale(w, 0.45), tone.scale(w, 0.1))

    def test_location_tone_overrides_the_baseline(self):
        w = _world()
        canon.write_node(w, "W", "x", {"kind": "lore", "setting": "true", "genre": "cosmic horror"})
        nodes = [{"name": "Hearth", "frontmatter": {"kind": "place", "tone": "cozy, warm"}, "body": "", "links": []}]
        self.assertLess(tone.scale(w, 0.15, nodes), tone.scale(w, 0.15))   # a cozy room in a horror world reads warmer

    def test_clamped_to_the_coherent_band(self):
        w = _world()
        canon.write_node(w, "Grim", "x", {"kind": "lore", "setting": "true", "genre": "grim dark horror"})
        self.assertLessEqual(tone.scale(w, 0.95), tone.CEIL)               # never past the shatter ceiling
        canon.write_node(w, "Grim", "x", {"kind": "lore", "setting": "true", "genre": "cozy warm gentle"})
        self.assertGreaterEqual(tone.scale(w, 0.0), tone.FLOOR)


class ToneInNarrateTest(unittest.TestCase):
    def _cap_scale(self, cfg):
        camp = _camp()
        canon.write_node(camp / "world", "W", "x", {"kind": "lore", "setting": "true", "genre": "cosmic horror"})
        cap = {"cvs": "unset"}
        orig = llm.chat
        llm.chat = lambda m, c, control_vector_scale=None, **k: (cap.__setitem__("cvs", control_vector_scale), "ok.")[1]
        try:
            narrate.turn("I look.", cfg, camp / "t.jsonl", camp / "world", camp / "state.json")
        finally:
            llm.chat = orig
        return cap["cvs"]

    def test_scale_sent_when_steer_on(self):
        cfg = dict(config.DEFAULTS); cfg["tone_steer"] = True
        self.assertIsNotNone(self._cap_scale(cfg))

    def test_no_scale_when_steer_off(self):
        cfg = dict(config.DEFAULTS)                                        # tone_steer False by default
        self.assertIsNone(self._cap_scale(cfg))


if __name__ == "__main__":
    unittest.main()
