"""Offline proof of the wall + the narrate-from-canon invariant. No model needed."""
import tempfile
import unittest
from pathlib import Path

from loom import config, canon, state, transcript, consolidate, narrate, seal, llm


def _campaign() -> Path:
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class SealTest(unittest.TestCase):
    def test_guard_path_blocks_escape(self):
        camp = _campaign()
        seal.guard_path(camp / "world" / "a.md", camp)          # inside → ok
        with self.assertRaises(seal.SealBreach):
            seal.guard_path(Path("/etc/passwd"), camp)           # escape → raise

    def test_leak_scan_flags_real_world(self):
        camp = _campaign()
        canon.write_node(camp / "world", "Leaky",
                         "the tome lies at /home/Fenrir/secret and mentions primarch")
        problems = seal.check_campaign(camp / "world", camp / "state.json")
        self.assertTrue(problems, "leak scan should flag real-world paths")

    def test_clean_campaign_is_sealed(self):
        camp = _campaign()
        canon.write_node(camp / "world", "Harbor",
                         "A grey port where the [[Ash War]] began.", {"kind": "place"})
        self.assertEqual(seal.check_campaign(camp / "world", camp / "state.json"), [])

    def test_windows_path_leak_is_caught(self):
        self.assertTrue(seal.leaks_in(r"D:\Models\gemma.gguf"))   # single-backslash regex fix

    def test_leak_scan_flags_a_thread_leak(self):
        from loom import threads as _threads
        from loom.threads import Thread
        camp = _campaign()
        _threads.save(camp / "threads.json", [Thread("t", "who hides the ledger at /home/Fenrir/secret?")])
        problems = seal.check_campaign(camp / "world", camp / "state.json")
        self.assertTrue(any("thread" in p for p in problems))


class DiodeTest(unittest.TestCase):
    def test_consolidate_writes_nothing_without_approval(self):
        camp = _campaign()
        proposals = {"nodes": [{"name": "King", "body": "dead", "kind": "character"}],
                     "state": {"king_dead": True}, "summary": "x"}
        written = consolidate.apply(proposals, camp / "world", camp / "state.json",
                                    approve=lambda *a: False)
        self.assertEqual(written["nodes"], [])
        self.assertEqual(list((camp / "world").glob("*.md")), [])
        self.assertEqual(state.load(camp / "state.json"), {})

    def test_consolidate_writes_on_approval(self):
        camp = _campaign()
        proposals = {"nodes": [{"name": "King", "body": "The old king, now dead.", "kind": "character"}],
                     "state": {"king_dead": True}, "summary": "x"}
        written = consolidate.apply(proposals, camp / "world", camp / "state.json",
                                    approve=lambda *a: True)
        self.assertEqual(written["nodes"], ["King"])
        self.assertIs(state.load(camp / "state.json")["king_dead"], True)


class NarrateTest(unittest.TestCase):
    def test_turn_grounds_on_canon_not_raw_log(self):
        camp = _campaign()
        canon.write_node(camp / "world", "Harbor",
                         "A grey port named Saltmarrow.", {"kind": "place"})
        cfg = dict(config.DEFAULTS)
        captured = {}

        def fake_chat(messages, c, **kw):
            captured["system"] = messages[0]["content"]
            return "You arrive at the harbor."

        orig = llm.chat
        llm.chat = fake_chat
        try:
            out = narrate.turn("I walk to the harbor.", cfg,
                               camp / "transcript.jsonl", camp / "world", camp / "state.json")
        finally:
            llm.chat = orig

        self.assertIn("Saltmarrow", captured["system"])           # canon reached the prompt
        self.assertEqual(out, "You arrive at the harbor.")
        log = transcript.read_all(camp / "transcript.jsonl")
        self.assertEqual([e["role"] for e in log], ["player", "narrator"])

    def test_failed_model_call_does_not_advance_the_plan(self):
        from loom import threads as _threads
        from loom.threads import Thread
        camp = _campaign()
        canon.write_node(camp / "world", "Harbor", "A grey port.", {"kind": "place"})
        _threads.save(camp / "threads.json",
                      [Thread("t", "q", status="ready", readiness=0.9, entities=["Harbor"])])
        before = (camp / "threads.json").read_text()
        orig = llm.chat

        def boom(*a, **k):
            raise llm.LLMError("server down")

        llm.chat = boom
        try:
            with self.assertRaises(llm.LLMError):
                narrate.turn("I look around.", dict(config.DEFAULTS), camp / "transcript.jsonl",
                             camp / "world", camp / "state.json")
        finally:
            llm.chat = orig
        self.assertEqual((camp / "threads.json").read_text(), before)   # plan left untouched


if __name__ == "__main__":
    unittest.main()
