"""Retrieval + the proximity/grounding split: a vague, non-matching turn still GROUNDS on
canon (fallback) but must NOT ripen the plan (score-0 nodes aren't 'near'). Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import retrieve, canon, narrate, threads, llm, config
from loom.threads import Thread


def _world():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class RetrieveTest(unittest.TestCase):
    def test_bm25_ranks_the_match_first(self):
        w = _world()
        canon.write_node(w, "Lighthouse", "the dark tower on the mole")
        canon.write_node(w, "Tavern", "a warm inn with ale")
        r = retrieve.retrieve("the dark tower", w, dict(config.DEFAULTS))
        self.assertEqual(r[0]["name"], "Lighthouse")
        self.assertGreater(r[0]["score"], 0)

    def test_nonmatching_query_falls_back_at_zero_score(self):
        w = _world()
        canon.write_node(w, "A", "alpha")
        canon.write_node(w, "B", "beta")
        r = retrieve.retrieve("zzzznomatch", w, dict(config.DEFAULTS))
        self.assertEqual(len(r), 2)
        self.assertTrue(all(n["score"] == 0.0 for n in r))       # fallback grounding, not proximity


class EmbeddingsTest(unittest.TestCase):
    def test_fusion_when_shapes_match(self):
        w = _world()
        canon.write_node(w, "A", "alpha text")
        canon.write_node(w, "B", "beta text")
        cfg = dict(config.DEFAULTS)
        cfg["use_embeddings"] = True
        orig = llm.embed
        llm.embed = lambda texts, c: [[1.0, 0.0], [0.0, 1.0], [0.9, 0.1]]   # q, A, B (B ~ q)
        try:
            r = retrieve.retrieve("query", w, cfg)
        finally:
            llm.embed = orig
        self.assertEqual(len(r), 2)                          # fused, no crash

    def test_wrong_shape_falls_back_not_crashes(self):
        w = _world()
        canon.write_node(w, "A", "alpha")
        canon.write_node(w, "B", "beta")
        cfg = dict(config.DEFAULTS)
        cfg["use_embeddings"] = True
        orig = llm.embed
        llm.embed = lambda texts, c: [[1.0, 0.0]]            # too few → shape guard → lexical
        try:
            r = retrieve.retrieve("zzz", w, cfg)
        finally:
            llm.embed = orig
        self.assertEqual(len(r), 2)                          # no IndexError


class ProximityTest(unittest.TestCase):
    def _turn(self, w, inp):
        camp = w.parent
        orig = llm.chat
        llm.chat = lambda m, c, **k: "ok."
        try:
            narrate.turn(inp, dict(config.DEFAULTS), camp / "transcript.jsonl", w, camp / "state.json")
        finally:
            llm.chat = orig

    def test_vague_input_does_not_ripen_a_thread(self):
        w = _world()
        canon.write_node(w, "Lighthouse", "the dark tower")
        thp = w.parent / "threads.json"
        threads.save(thp, [Thread("t", "q", status="seeded", readiness=0.3, entities=["Lighthouse"])])
        self._turn(w, "hmm")                                     # non-matching → fallback → NOT near
        self.assertAlmostEqual(threads.load(thp)[0].readiness, 0.35, places=6)   # only ambient DRIFT

    def test_matching_input_ripens_the_near_thread(self):
        w = _world()
        canon.write_node(w, "Lighthouse", "the dark tower on the mole")
        thp = w.parent / "threads.json"
        threads.save(thp, [Thread("t", "q", status="seeded", readiness=0.3, entities=["Lighthouse"])])
        self._turn(w, "I look at the dark tower")                # matches → near → ripens NEAR
        self.assertGreaterEqual(threads.load(thp)[0].readiness, 0.6)


if __name__ == "__main__":
    unittest.main()
