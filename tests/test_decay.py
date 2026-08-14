"""Forgetting: a salience × recency re-ranker over retrieval. The live scene surfaces over stale
canon, but a genuine match is never buried (the boost floors), nothing is written (undo-transparent),
and with the flag off it is byte-identical to pure relevance. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import decay, retrieve, canon, transcript, threads, state, config
from loom.threads import Thread


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class RecencyTest(unittest.TestCase):
    def test_recent_mention_outweighs_old_and_unseen(self):
        camp = _camp()
        tp = camp / "transcript.jsonl"
        transcript.append(tp, "narrator", "The Tower loomed over the marsh.")     # old
        for _ in range(20):
            transcript.append(tp, "narrator", "nothing of note happens here")     # push the Tower back
        transcript.append(tp, "player", "I greet Wren warmly.")                   # recent
        rec = decay._recency(tp, ["Wren", "Tower", "Grimwald"])
        self.assertGreater(rec["Wren"], rec["Tower"])          # named more recently → hotter
        self.assertEqual(rec["Grimwald"], decay._UNSEEN)       # never named → the dormant floor
        self.assertLessEqual(rec["Wren"], 1.0)

    def test_word_boundary_not_substring(self):
        camp = _camp()
        tp = camp / "transcript.jsonl"
        transcript.append(tp, "narrator", "the winterfell banners flew")          # contains 'win' but not 'Win'
        self.assertEqual(decay._recency(tp, ["Win"])["Win"], decay._UNSEEN)       # 'Win' isn't a whole word here


class BoostRerankTest(unittest.TestCase):
    def test_boost_floors_and_caps(self):
        self.assertEqual(decay.boost(0.0), decay.DECAY_FLOOR)   # coldest → floor, never zero
        self.assertEqual(decay.boost(1.0), 1.0)                 # hottest → full relevance
        self.assertEqual(decay.boost(5.0), 1.0)                 # clamped

    def test_rerank_lifts_the_hot_node_on_a_tie(self):
        prom = {"Cold": 0.0, "Hot": 1.0}
        out = decay.rerank([("Cold", 4.0), ("Hot", 4.0)], prom)
        self.assertEqual(out[0][0], "Hot")                      # equal relevance → the alive one wins
        self.assertEqual(dict(out)["Cold"], 4.0)                # scores pass through unchanged (relevance flag)

    def test_rerank_never_buries_a_strong_match(self):
        prom = {"Cold": 0.0, "Hot": 1.0}
        # a much stronger lexical hit on a COLD node still outranks a weak hot one (floor protects recall)
        out = decay.rerank([("Cold", 10.0), ("Hot", 4.0)], prom)
        self.assertEqual(out[0][0], "Cold")                     # 10*0.5=5.0 > 4*1.0=4.0


class RetrieveIntegrationTest(unittest.TestCase):
    def _world(self):
        camp = _camp()
        canon.write_node(camp / "world", "Harbor", "a cold fishing harbor on the coast", {"kind": "place"})
        canon.write_node(camp / "world", "Beacon", "a signal beacon on the cliff", {"kind": "place"})
        return camp

    def test_off_is_byte_identical(self):
        camp = self._world()
        tp, sp = camp / "transcript.jsonl", camp / "state.json"
        transcript.append(tp, "narrator", "the Harbor is busy")
        cfg = dict(config.DEFAULTS)                              # salience_decay False
        a = retrieve.retrieve("harbor beacon", camp / "world", cfg, tpath=tp, spath=sp)
        b = retrieve.retrieve("harbor beacon", camp / "world", cfg)   # no paths
        self.assertEqual([d["name"] for d in a], [d["name"] for d in b])

    def test_direct_recall_of_a_cold_node_survives(self):
        camp = self._world()
        tp, sp = camp / "transcript.jsonl", camp / "state.json"
        for _ in range(10):
            transcript.append(tp, "narrator", "the Harbor churns, the Harbor waits")   # Harbor hot, Beacon cold
        cfg = dict(config.DEFAULTS); cfg["salience_decay"] = True
        out = retrieve.retrieve("beacon", camp / "world", cfg, tpath=tp, spath=sp)
        top = [d["name"] for d in out if d.get("score", 0) > 0]
        self.assertEqual(top[0], "Beacon")                      # a strong lexical hit on a cold node still leads

    def test_ungrounded_fallback_is_prominence_ordered(self):
        camp = self._world()
        tp, sp = camp / "transcript.jsonl", camp / "state.json"
        for _ in range(4):
            transcript.append(tp, "narrator", "the Beacon flares over the water")      # Beacon hot
        cfg = dict(config.DEFAULTS); cfg["salience_decay"] = True
        out = retrieve.retrieve("zzz nothing matches", camp / "world", cfg, tpath=tp, spath=sp)
        self.assertTrue(all(d["score"] == 0.0 for d in out))    # nothing relevant → fallback
        self.assertEqual(out[0]["name"], "Beacon")              # but grounded on the LIVE node, not alphabetical

    def test_salience_lifts_a_thread_bound_node(self):
        camp = self._world()
        tp, sp = camp / "transcript.jsonl", camp / "state.json"
        threads.save(camp / "threads.json", [Thread("q", "what of the beacon?", entities=["Beacon"])])
        prom = decay.prominence(camp / "world", tp, sp)
        self.assertGreater(prom["Beacon"], prom["Harbor"])      # thread membership raises salience


if __name__ == "__main__":
    unittest.main()
