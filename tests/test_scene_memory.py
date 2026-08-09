"""Scene memory (working memory): an advisory 'story so far' regenerated on cadence, injected into
narration, capped, and NEVER canon. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import scene_memory, narrate, canon, state, transcript, llm, config


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class ModuleTest(unittest.TestCase):
    def test_update_builds_capped_facts_plus_recap(self):
        camp = _camp()
        transcript.append(camp / "t.jsonl", "player", "I reveal I am Furor.")
        transcript.append(camp / "t.jsonl", "narrator", "Wren gasps.")
        cfg = dict(config.DEFAULTS)
        orig = llm.complete
        many = ",".join(f'"fact {i}"' for i in range(12))                     # 12 → capped to 10
        llm.complete = lambda *a, **k: '{"facts":[' + many + '],"recap":"Wren learns the truth."}'
        try:
            block = scene_memory.update(cfg, camp / "t.jsonl", camp / "state.json")
        finally:
            llm.complete = orig
        self.assertEqual(len([l for l in block.split("\n") if l.startswith("- ")]), 10)   # capped
        self.assertIn("So far: Wren learns the truth.", block)
        st = state.load(camp / "state.json")
        self.assertEqual(st["_memory"], block)
        self.assertEqual(st["_mturn"], 0)                                     # counter reset

    def test_read_and_clause(self):
        self.assertEqual(scene_memory.read({"_memory": "m"}), "m")
        self.assertEqual(scene_memory.read({}), "")
        self.assertEqual(scene_memory.clause(""), "")
        c = scene_memory.clause("- a fact")
        self.assertIn("story memory", c)
        self.assertIn("a fact", c)

    def test_update_is_failsoft(self):
        camp = _camp()
        transcript.append(camp / "t.jsonl", "player", "hi")
        state.save(camp / "state.json", {"_memory": "- prior fact"})
        orig = llm.complete
        def boom(*a, **k):
            raise llm.LLMError("model down")
        llm.complete = boom
        try:
            block = scene_memory.update(dict(config.DEFAULTS), camp / "t.jsonl", camp / "state.json")
        finally:
            llm.complete = orig
        self.assertEqual(block, "- prior fact")                              # kept, not blanked
        self.assertEqual(state.load(camp / "state.json")["_memory"], "- prior fact")


class NarrateTest(unittest.TestCase):
    def _turn(self, cfg, camp, cap):
        orig = llm.chat
        llm.chat = lambda m, c, **k: (cap.__setitem__("sys", m[0]["content"]), "ok.")[1]
        try:
            narrate.turn("I look.", cfg, camp / "t.jsonl", camp / "world", camp / "state.json")
        finally:
            llm.chat = orig

    def test_memory_injected_when_on(self):
        camp = _camp(); canon.write_node(camp / "world", "Room", "a room")
        state.save(camp / "state.json", {"_memory": "- Fáelán is Furor"})
        cfg = dict(config.DEFAULTS); cfg["scene_memory"] = True
        cap = {}
        self._turn(cfg, camp, cap)
        self.assertIn("story memory", cap["sys"])
        self.assertIn("Fáelán is Furor", cap["sys"])

    def test_memory_absent_when_off(self):
        camp = _camp(); canon.write_node(camp / "world", "Room", "a room")
        state.save(camp / "state.json", {"_memory": "- Fáelán is Furor"})
        cfg = dict(config.DEFAULTS); cfg["scene_memory"] = False
        cap = {}
        self._turn(cfg, camp, cap)
        self.assertNotIn("story memory", cap["sys"])

    def test_cadence_fires_update_every_n_turns(self):
        camp = _camp(); canon.write_node(camp / "world", "Room", "a room")
        state.save(camp / "state.json", {})
        cfg = dict(config.DEFAULTS); cfg["scene_memory"] = True; cfg["memory_every"] = 2
        calls = []
        oc, ocmp = llm.chat, llm.complete
        llm.chat = lambda *a, **k: "A beat."
        llm.complete = lambda *a, **k: (calls.append(1), '{"facts":["a fact"],"recap":"r"}')[1]
        try:
            narrate.turn("t1", cfg, camp / "t.jsonl", camp / "world", camp / "state.json")   # _mturn → 1
            self.assertEqual(len(calls), 0)
            narrate.turn("t2", cfg, camp / "t.jsonl", camp / "world", camp / "state.json")   # → 2 == every → update
            self.assertEqual(len(calls), 1)
        finally:
            llm.chat, llm.complete = oc, ocmp
        st = state.load(camp / "state.json")
        self.assertIn("a fact", st.get("_memory", ""))
        self.assertEqual(st.get("_mturn"), 0)


if __name__ == "__main__":
    unittest.main()
