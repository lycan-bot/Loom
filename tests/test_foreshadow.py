"""The narrator's horizon foreshadow (Brick D): a live HIDDEN horizon thread's authored SEED surfaces as
escalating SUBTEXT — gated + byte-identical-off, and NEVER the raw secret. Offline, deterministic."""
import tempfile
import unittest
from pathlib import Path
from loom import narrate, threads, config


def _sp():
    return Path(tempfile.mkdtemp()) / "state.json"


def _seed_clock(sp, clock, span=10, seed="the ground hums faintly", hidden=True, scope="horizon"):
    threads.save(sp.parent / "threads.json",
                 [threads.Thread(id="c", question="the sleeping god wakes", kind="clock", status="ripening",
                                 clock=clock, span=span, hidden=hidden, scope=scope, seed=seed)])


_NODES = [{"name": "Well", "body": "an old well", "score": 1.0, "frontmatter": {"kind": "place"}}]


class ForeshadowTest(unittest.TestCase):
    def test_off_is_byte_identical(self):
        sp = _sp(); _seed_clock(sp, 1)
        self.assertEqual(narrate._foreshadow_clause(_NODES, sp, "I look", dict(config.DEFAULTS)), "")   # toggle off

    def test_silent_without_a_hidden_horizon_clock(self):
        sp = _sp()
        cfg = dict(config.DEFAULTS); cfg["horizon"] = True
        self.assertEqual(narrate._foreshadow_clause(_NODES, sp, "hi", cfg), "")     # nothing seeded
        _seed_clock(sp, 1, hidden=False)                                            # a KNOWN horizon clock
        self.assertEqual(narrate._foreshadow_clause(_NODES, sp, "hi", cfg), "")     # → no unnamed foreshadow

    def test_surfaces_the_seed_escalates_never_the_secret(self):
        sp = _sp()
        cfg = dict(config.DEFAULTS); cfg["horizon"] = True
        _seed_clock(sp, 9, span=10)                                                 # far → faint
        far = narrate._foreshadow_clause(_NODES, sp, "I look", cfg)
        _seed_clock(sp, 1, span=10)                                                 # near → imminent
        near = narrate._foreshadow_clause(_NODES, sp, "I look", cfg)
        self.assertIn("the ground hums faintly", far)          # the authored SEED is surfaced…
        self.assertNotIn("sleeping god", far)                  # …never the raw secret (the thread's question)
        self.assertIn("ON THE HORIZON", near)
        self.assertNotEqual(far, near)                         # the foreshadow escalates as the clock nears
        self.assertIn('source="horizon"', near)                # the datum is fenced as untrusted story data

    def test_seedless_horizon_clock_is_silent(self):
        sp = _sp()
        cfg = dict(config.DEFAULTS); cfg["horizon"] = True
        _seed_clock(sp, 1, seed="")                            # a hidden horizon clock with no authored hint
        self.assertEqual(narrate._foreshadow_clause(_NODES, sp, "hi", cfg), "")     # nothing to plant → silent


if __name__ == "__main__":
    unittest.main()
