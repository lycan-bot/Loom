"""Per-character voice + disposition injected when a character is in the scene. Offline."""
import unittest
from loom import character


def _node(name, kind="character", **fm):
    return {"name": name, "frontmatter": {"kind": kind, **fm}, "body": "", "links": []}


class CharacterTest(unittest.TestCase):
    def test_voice_clause_includes_scene_characters(self):
        nodes = [_node("Mara", voice="in clipped, wary sentences", disposition="guarded"),
                 _node("Harbor", kind="place")]
        c = character.voice_clause(nodes)
        self.assertIn("Mara", c)
        self.assertIn("clipped, wary", c)
        self.assertIn("guarded", c)
        self.assertNotIn("Harbor", c)                 # places aren't voiced

    def test_empty_when_no_voiced_characters(self):
        self.assertEqual(character.voice_clause([_node("Sil", kind="character")]), "")

    def test_card_fields(self):
        node = {"name": "Mara", "body": "A weathered fisher.", "links": [],
                "frontmatter": {"kind": "character", "role": "a fisher", "met": "on the docks",
                                "wants": "to leave"}}
        c = character.card(node)
        self.assertEqual(c["role"], "a fisher")
        self.assertEqual(c["met"], "on the docks")
        self.assertEqual(c["want"], "to leave")
        self.assertEqual(c["description"], "A weathered fisher.")


if __name__ == "__main__":
    unittest.main()
