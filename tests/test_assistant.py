"""Oracle (the OOC assistant): its actions are normalized to a tiny safe vocabulary — create a node /
add a thread / change depth+mechanics only — so a garbled or over-reaching reply can't touch anything
on its own, and it grounds its answers in canon. The player still approves every action. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import assistant, canon, llm, config


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class CleanActionTest(unittest.TestCase):
    def test_create_node_requires_a_name(self):
        self.assertIsNone(assistant._clean_action({"type": "create_node", "name": "  "}))

    def test_create_node_normalizes_kind_and_fields(self):
        a = assistant._clean_action({"type": "create_node", "name": "The Gull", "kind": "pub",
                                     "body": "a tavern", "fields": {"role": "innkeep", "x": ["bad"], "n": 3}})
        self.assertEqual(a["kind"], "lore")                     # unknown kind → lore
        self.assertEqual(a["fields"], {"role": "innkeep", "n": "3"})   # list dropped, number stringified

    def test_add_thread_requires_a_question(self):
        self.assertIsNone(assistant._clean_action({"type": "add_thread", "seed": "x"}))

    def test_set_config_clamps_and_whitelists(self):
        a = assistant._clean_action({"type": "set_config", "depth": 5, "mechanics": 1,
                                     "stream": True, "world_rounds": True, "campaign": "evil"})
        self.assertEqual(a["depth"], 1.0)                       # clamped to range
        self.assertIs(a["mechanics"], True)
        self.assertNotIn("stream", a)                           # only depth + mechanics survive —
        self.assertNotIn("world_rounds", a)                     # the seal/safety knobs are refused
        self.assertNotIn("campaign", a)

    def test_set_config_with_no_allowed_keys_is_dropped(self):
        self.assertIsNone(assistant._clean_action({"type": "set_config", "stream": True}))

    def test_unknown_action_type_is_dropped(self):
        self.assertIsNone(assistant._clean_action({"type": "delete_campaign"}))


class ParseTest(unittest.TestCase):
    def test_parse_valid(self):
        out = assistant._parse('{"reply":"hi","actions":[{"type":"add_thread","question":"Q?"}]}')
        self.assertEqual(out["reply"], "hi")
        self.assertEqual(out["actions"][0]["question"], "Q?")

    def test_parse_non_json_falls_back_to_text(self):
        out = assistant._parse("just some prose, no json here")
        self.assertEqual(out["reply"], "just some prose, no json here")
        self.assertEqual(out["actions"], [])

    def test_parse_drops_malformed_actions(self):
        out = assistant._parse('{"reply":"x","actions":[{"type":"create_node"},{"type":"add_thread","question":"ok"}]}')
        self.assertEqual(len(out["actions"]), 1)               # the nameless create_node is dropped


class AskTest(unittest.TestCase):
    def test_ask_grounds_in_canon_and_returns_parsed(self):
        camp = _camp()
        canon.write_node(camp / "world", "The Gull", "a dockside tavern", {"kind": "place"})
        cap = {}
        orig = llm.chat

        def fake(msgs, cfg, **k):
            cap["sys"] = msgs[0]["content"]
            cap["rf"] = k.get("response_format")
            return '{"reply":"The Gull is a dockside tavern.","actions":[]}'

        llm.chat = fake
        try:
            out = assistant.ask(dict(config.DEFAULTS), camp / "world", camp / "state.json", [], "what is the Gull?")
        finally:
            llm.chat = orig
        self.assertIn("The Gull", cap["sys"])                  # canon grounds the prompt (no invention)
        self.assertEqual(cap["rf"], {"type": "json_object"})   # grammar-constrained JSON
        self.assertEqual(out["reply"], "The Gull is a dockside tavern.")


if __name__ == "__main__":
    unittest.main()
