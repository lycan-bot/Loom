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

    def test_player_mention_outheats_narrator_prose(self):
        # red-team #7 (anti-collapse): recency anchors to the PLAYER; narrator prose is capped, so the
        # ranking can't self-amplify off the model's own output
        camp = _camp()
        tp = camp / "transcript.jsonl"
        for _ in range(3):
            transcript.append(tp, "narrator", "Ghost drifts through the hall, Ghost watching")
        transcript.append(tp, "player", "I thank Ally")
        rec = decay._recency(tp, ["Ghost", "Ally"])
        self.assertGreater(rec["Ally"], rec["Ghost"])                # the human's word outheats model prose
        self.assertLessEqual(rec["Ghost"], decay._NARRATOR_DISCOUNT)  # narrator-only can't reach full heat

    def test_matcher_handles_punctuation_edge_names(self):
        # red-team #5: a name whose edge is punctuation ('c++') still matches (no dead substring fallback)
        camp = _camp()
        tp = camp / "transcript.jsonl"
        transcript.append(tp, "player", "I compile the c++ program")
        self.assertGreater(decay._recency(tp, ["c++"])["c++"], decay._UNSEEN)

    def test_matcher_no_false_substring_on_punctuation_edge(self):
        # re-verify residual: a punctuation-edged name must NOT match glued inside a bigger token
        camp = _camp()
        tp = camp / "transcript.jsonl"
        transcript.append(tp, "player", "I run c++plus and asp.net today")
        self.assertEqual(decay._recency(tp, ["c++"])["c++"], decay._UNSEEN)     # not inside 'c++plus'
        self.assertEqual(decay._recency(tp, [".net"])[".net"], decay._UNSEEN)   # not inside 'asp.net'


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
        # the STRONGEST raw match leads regardless of aliveness (pinned) — never buried
        out = decay.rerank([("Cold", 10.0), ("Hot", 4.0)], prom)
        self.assertEqual(out[0][0], "Cold")

    def test_rerank_keeps_relevant_above_irrelevant(self):
        # red-team #4: a hot IRRELEVANT node (score 0, RRF-fused) must never outrank a genuine match
        prom = {"HotNoise": 1.0, "RealMatch": 0.0}
        out = decay.rerank([("HotNoise", 0.03), ("RealMatch", 0.02)], prom, relevant={"RealMatch"})
        self.assertEqual(out[0][0], "RealMatch")                # relevance partitions above aliveness

    def test_tied_strongest_matches_both_survive(self):
        # re-verify residual: TWO co-strongest matches (exact raw tie) must BOTH lead, not just one — else
        # a genuine co-best hit is evicted past the top-k by hotter but weaker nodes
        prom = {"Aaa": 1.0, "Bbb": 0.0, "Hot0": 1.0, "Hot1": 1.0}
        out = [n for n, _ in decay.rerank(
            [("Aaa", 0.35), ("Bbb", 0.35), ("Hot0", 0.30), ("Hot1", 0.30)],
            prom, relevant={"Aaa", "Bbb", "Hot0", "Hot1"})]
        self.assertEqual(out[:2], ["Aaa", "Bbb"])               # both co-strongest pinned ahead of the tail


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

    def test_strongest_match_survives_a_crowded_topk(self):
        # red-team #1/#3: the strongest genuine match is COLD, k HOT near-ties crowd the query — it must
        # NOT be cut past the top-k (the burial the pairwise floor missed)
        camp = _camp()
        w = camp / "world"
        canon.write_node(w, "TrueBeacon", "beacon beacon beacon watchtower", {"kind": "place"})
        for i in range(10):
            canon.write_node(w, f"Ridge{i}", "beacon watchtower", {"kind": "place"})
        tp, sp = camp / "transcript.jsonl", camp / "state.json"
        for i in range(10):
            transcript.append(tp, "player", f"I climb Ridge{i} again")     # the Ridges are HOT, TrueBeacon COLD
        cfg = dict(config.DEFAULTS); cfg["salience_decay"] = True
        out = [d["name"] for d in retrieve.retrieve("beacon watchtower", w, cfg, k=8, tpath=tp, spath=sp)]
        self.assertIn("TrueBeacon", out)                        # not buried past the cut…
        self.assertEqual(out[0], "TrueBeacon")                  # …in fact the strongest match leads

    def test_salience_lifts_a_thread_bound_node(self):
        camp = self._world()
        tp, sp = camp / "transcript.jsonl", camp / "state.json"
        threads.save(camp / "threads.json", [Thread("q", "what of the beacon?", entities=["Beacon"])])
        prom = decay.prominence(camp / "world", tp, sp)
        self.assertGreater(prom["Beacon"], prom["Harbor"])      # thread membership raises salience


if __name__ == "__main__":
    unittest.main()
