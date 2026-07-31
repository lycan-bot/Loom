"""The imagination organ: dream candidate threads from canon, gate them (grounded +
novel), seal as 'imagined', bless into the plan. Offline (mocked model)."""
import json
import random
import tempfile
import unittest
from pathlib import Path
from loom import imagine, canon, threads, llm


def _world():
    d = Path(tempfile.mkdtemp()) / "world"
    d.mkdir(parents=True)
    return d


class GateTest(unittest.TestCase):
    def test_too_similar_rejects_near_duplicate(self):
        self.assertTrue(imagine._too_similar("what haunts the mill", ["what haunts the mill house"]))
        self.assertFalse(imagine._too_similar("who lit the beacon", ["what haunts the mill"]))

    def test_pick_pair_prefers_unlinked(self):
        w = _world()
        canon.write_node(w, "A", "links [[B]]")
        canon.write_node(w, "B", "plain")
        canon.write_node(w, "C", "plain")
        pair = imagine._pick_pair(canon.load_all(w), random.Random(1))   # A–B linked → pair must include C
        self.assertIn("C", [p["name"] for p in pair])


class ImagineOneTest(unittest.TestCase):
    def _setup(self):
        w = _world()
        canon.write_node(w, "Ash War", "a war", {"kind": "event"})
        canon.write_node(w, "The Lighthouse", "a tower", {"kind": "place"})
        return w

    def test_passes_gate_and_seals_imagined(self):
        w = self._setup()
        orig = llm.complete
        llm.complete = lambda *a, **k: json.dumps(
            {"question": "Did the Ash War's fire ever reach the lighthouse keeper?",
             "entities": ["Ash War", "The Lighthouse"], "seed": "scorch marks", "payoff": "a burned ledger"})
        try:
            c = imagine.imagine_one(w, {}, [], random.Random(1))
        finally:
            llm.complete = orig
        self.assertIsNotNone(c)
        self.assertEqual(c.status, "imagined")
        self.assertEqual(sorted(c.entities), ["Ash War", "The Lighthouse"])

    def test_rejects_ungrounded_candidate(self):
        w = self._setup()
        orig = llm.complete
        llm.complete = lambda *a, **k: json.dumps(
            {"question": "a question", "entities": ["Ghost Town", "Nowhere"], "seed": "x", "payoff": "y"})
        try:
            c = imagine.imagine_one(w, {}, [], random.Random(1))
        finally:
            llm.complete = orig
        self.assertIsNone(c)                     # <2 real canon entities → gated out


class BlessTest(unittest.TestCase):
    def test_bless_writes_dormant_and_dedups(self):
        w = _world()
        thp = w.parent / "threads.json"
        cand = threads.Thread(id="c1", question="a dream q", status="imagined", entities=["A", "B"])
        self.assertEqual(imagine.bless(thp, [cand], approve=lambda *a: True), ["a dream q"])
        self.assertEqual(threads.load(thp)[0].status, "dormant")            # seal shed
        self.assertEqual(imagine.bless(thp, [cand], approve=lambda *a: True), [])  # dedup


if __name__ == "__main__":
    unittest.main()
