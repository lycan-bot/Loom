"""Rolling a fresh world + cast: the model invents a world card and character cards; both are
sanitized and written into canon as a lore node + character nodes. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import generate, canon, config, llm


def _world():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d / "world"


_CFG = dict(config.DEFAULTS)


class WorldRollTest(unittest.TestCase):
    def test_world_card_parsed_to_known_keys(self):
        payload = ('{"name":"Emberfall","premise":"a dying sun","age":"late bronze","tech":"bronze + oracles",'
                   '"magic":"ember-reading","peoples":"humans and ashfolk","tone":"elegiac",'
                   '"body":"The sun cools; cities crowd the last warm valleys.","junk":123}')
        orig = llm.complete
        llm.complete = lambda *a, **k: payload
        try:
            wc = generate.world(_CFG)
        finally:
            llm.complete = orig
        self.assertEqual(wc["name"], "Emberfall")
        self.assertEqual(wc["peoples"], "humans and ashfolk")
        self.assertEqual(set(wc.keys()), set(generate._WORLD_KEYS))   # only the known keys, no 'junk'

    def test_non_string_values_are_dropped_to_empty(self):
        orig = llm.complete
        llm.complete = lambda *a, **k: '{"name":["x"],"premise":5,"body":"ok"}'
        try:
            wc = generate.world(_CFG)
        finally:
            llm.complete = orig
        self.assertEqual(wc["name"], "")                             # bad type → '', never a crash
        self.assertEqual(wc["body"], "ok")


class CastRollTest(unittest.TestCase):
    def test_cast_is_one_per_call_with_dedup(self):
        # each character is its own small call (reliable JSON); a repeated name is dropped
        payloads = iter(['{"name":"Sera","role":"ember-reader"}',
                         '{"name":"Sera","role":"a duplicate"}',
                         '{"name":"Kade","role":"a sailor"}'])
        orig = llm.complete
        llm.complete = lambda *a, **k: next(payloads)
        try:
            cs = generate.cast(_CFG, {"name": "Emberfall"}, 3)
        finally:
            llm.complete = orig
        self.assertEqual([c["name"] for c in cs], ["Sera", "Kade"])   # the second 'Sera' deduped out
        self.assertEqual(cs[0]["role"], "ember-reader")

    def test_nameless_character_is_skipped(self):
        orig = llm.complete
        llm.complete = lambda *a, **k: '{"role":"a nameless one"}'    # no name → not a character
        try:
            cs = generate.cast(_CFG, {}, 2)
        finally:
            llm.complete = orig
        self.assertEqual(cs, [])

    def test_malformed_json_fails_soft(self):
        # the live wild model emits slightly-broken JSON (a missing comma) despite response_format —
        # it must degrade to empty, never crash (this is the bug the live Mag-Mell run surfaced)
        orig = llm.complete
        llm.complete = lambda *a, **k: '{"name":"A" "role":"x"}'   # missing comma (single-char call)
        try:
            self.assertEqual(generate.cast(_CFG, {}, 2), [])
            llm.complete = lambda *a, **k: '{"name":"X" "premise":"y"}'              # missing comma
            self.assertEqual(generate.world(_CFG)["name"], "")
        finally:
            llm.complete = orig


class WriteWorldTest(unittest.TestCase):
    def test_writes_lore_node_and_character_nodes(self):
        w = _world()
        wc = {"name": "Emberfall", "premise": "a dying sun", "body": "cities crowd the valleys",
              "age": "bronze", "tech": "oracles", "magic": "ember-reading", "peoples": "humans", "tone": "elegiac"}
        cast = [{"name": "Sera", "role": "reader", "description": "a young oracle", "voice": "clipped",
                 "wants": "to save her city", "bound": "a vow", "location": "The Last Valley"}]
        generate.write_world(w, wc, cast)
        wnode = canon.read_node(w, "Emberfall")
        self.assertEqual(wnode["frontmatter"].get("kind"), "lore")
        self.assertEqual(wnode["frontmatter"].get("peoples"), "humans")     # world attributes carried
        self.assertIn("dying sun", wnode["body"])
        cnode = canon.read_node(w, "Sera")
        self.assertEqual(cnode["frontmatter"].get("kind"), "character")
        self.assertEqual(cnode["frontmatter"].get("wants"), "to save her city")
        self.assertEqual(cnode["frontmatter"].get("location"), "The Last Valley")   # ready for the world round

    def test_empty_world_still_writes_a_node(self):
        w = _world()
        generate.write_world(w, {"name": "", "premise": "", "body": ""}, [])
        self.assertIsNotNone(canon.read_node(w, "The World"))               # falls back to a named node


if __name__ == "__main__":
    unittest.main()
