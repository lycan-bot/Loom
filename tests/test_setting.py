"""The world card: an authored genre/tone/age/… on the world's lore node, injected so the
narrator writes in that register. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import setting, canon, narrate, llm, config


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class SettingCardTest(unittest.TestCase):
    def test_flagged_world_card_is_the_setting(self):
        camp = _camp()
        canon.write_node(camp / "world", "Emberfall", "a dying-sun world",
                         {"kind": "lore", "setting": "true", "genre": "mythic tragedy", "tone": "elegiac"})
        c = setting.card(camp / "world")
        self.assertEqual(c["genre"], "mythic tragedy")
        self.assertIn("mythic tragedy", setting.clause(camp / "world"))

    def test_richest_lore_node_when_none_flagged(self):
        camp = _camp()
        canon.write_node(camp / "world", "Bare", "x", {"kind": "lore"})
        canon.write_node(camp / "world", "Rich", "y", {"kind": "lore", "genre": "noir", "age": "modern"})
        self.assertEqual(setting.get(camp / "world")["name"], "Rich")

    def test_unthemed_world_has_no_clause(self):
        camp = _camp()
        canon.write_node(camp / "world", "Plain", "just a place", {"kind": "lore"})
        self.assertEqual(setting.clause(camp / "world"), "")


class SettingInNarrateTest(unittest.TestCase):
    def test_narrator_is_pinned_to_the_genre(self):
        camp = _camp()
        canon.write_node(camp / "world", "Saltmarrow", "a fogbound coast",
                         {"kind": "lore", "setting": "true", "genre": "Lovecraftian coastal horror"})
        cfg = dict(config.DEFAULTS)
        cap = {}
        orig = llm.chat
        llm.chat = lambda m, c, **k: (cap.__setitem__("sys", m[0]["content"]), "ok.")[1]
        try:
            narrate.turn("I look around.", cfg, camp / "t.jsonl", camp / "world", camp / "state.json")
        finally:
            llm.chat = orig
        self.assertIn("SETTING", cap["sys"])
        self.assertIn("Lovecraftian coastal horror", cap["sys"])


if __name__ == "__main__":
    unittest.main()
