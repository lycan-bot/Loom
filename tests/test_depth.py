"""The realness dial's proactive half: as depth rises, the narrator is told to embody a
world that resists (and at depth 0 nothing changes). Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import depth as depthmod, narrate, canon, llm, config


class DispositionClauseTest(unittest.TestCase):
    def test_empty_at_zero(self):
        self.assertEqual(depthmod.disposition_clause(0), "")

    def test_intensifies_with_depth(self):
        light = depthmod.disposition_clause(0.3)
        full = depthmod.disposition_clause(0.9)
        self.assertTrue(light)
        self.assertGreater(len(full), len(light))        # more clauses turn on as depth rises
        self.assertIn("resist", full.lower())


class NarrateInjectionTest(unittest.TestCase):
    def _system_at(self, d):
        camp = Path(tempfile.mkdtemp())
        (camp / "world").mkdir()
        canon.write_node(camp / "world", "Room", "a plain room")
        cfg = dict(config.DEFAULTS)
        cfg["depth"] = d
        cap = {}
        orig_chat, orig_complete = llm.chat, llm.complete
        llm.chat = lambda m, c, **k: (cap.__setitem__("sys", m[0]["content"]), "ok.")[1]
        llm.complete = lambda *a, **k: '{"verdict":"ok"}'      # keep the referee's judge offline
        try:
            narrate.turn("I look around.", cfg, camp / "transcript.jsonl", camp / "world", camp / "state.json")
        finally:
            llm.chat, llm.complete = orig_chat, orig_complete
        return cap["sys"]

    def test_mirror_adds_no_disposition(self):
        self.assertNotIn("THE WORLD RESISTS", self._system_at(0.0))

    def test_other_adds_disposition(self):
        self.assertIn("THE WORLD RESISTS", self._system_at(0.9))


if __name__ == "__main__":
    unittest.main()
