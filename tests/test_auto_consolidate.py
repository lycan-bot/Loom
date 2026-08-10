"""Incremental consolidation (only the turns since a watermark, so the prompt stays bounded) +
automated consolidation on a turn cadence — diode-gated: canon nodes stay queued unless opted in.
Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import consolidate, narrate, canon, state, transcript, llm, config, inbox, reputation


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class IncrementalTest(unittest.TestCase):
    def test_watermark_slices_to_new_turns_only(self):
        camp = _camp()
        transcript.append(camp / "t.jsonl", "player", "a")
        transcript.append(camp / "t.jsonl", "narrator", "b")
        new, total = consolidate.unconsolidated(camp / "t.jsonl", camp / "state.json")
        self.assertEqual([e["text"] for e in new], ["a", "b"])
        self.assertEqual(total, 2)
        consolidate.mark_consolidated(camp / "state.json", 2)
        transcript.append(camp / "t.jsonl", "player", "c")
        transcript.append(camp / "t.jsonl", "narrator", "d")
        new2, total2 = consolidate.unconsolidated(camp / "t.jsonl", camp / "state.json")
        self.assertEqual([e["text"] for e in new2], ["c", "d"])       # only the un-consolidated turns
        self.assertEqual(total2, 4)


class AutoTest(unittest.TestCase):
    def _proposal(self):
        return ('{"nodes":[{"name":"A New Place","kind":"place","body":"x"}],"state":{"mood":"warm"},'
                '"threads_new":[],"threads_resolved":[],'
                '"character_updates":[{"name":"Wren","disposition":"warmer"}],"reputation":[]}')

    def test_auto_gates_canon_but_applies_structured(self):
        camp = _camp()
        canon.write_node(camp / "world", "Wren", "a cadet", {"kind": "character"})
        transcript.append(camp / "t.jsonl", "player", "I talk to Wren")
        transcript.append(camp / "t.jsonl", "narrator", "Wren warms to you")
        orig = llm.complete
        llm.complete = lambda *a, **k: self._proposal()
        try:
            rep = consolidate.auto(dict(config.DEFAULTS), camp / "t.jsonl", camp / "world", camp / "state.json",
                                   apply_canon=False)
        finally:
            llm.complete = orig
        self.assertIsNone(canon.read_node(camp / "world", "A New Place"))   # canon node GATED (queued)
        self.assertIn("A New Place", rep["pending_nodes"])
        self.assertEqual([n["name"] for n in consolidate.pending(camp / "state.json")], ["A New Place"])  # PARKED, not dropped
        self.assertEqual(state.load(camp / "state.json").get("mood"), "warm")   # structured fact applied
        self.assertEqual(canon.read_node(camp / "world", "Wren")["frontmatter"].get("disposition"), "warmer")
        self.assertEqual(state.load(camp / "state.json").get("_consolidated"), 2)   # watermark advanced

    def test_auto_parks_canon_then_bless_lands_it(self):
        # the regression: auto advances the watermark PAST the turns that proposed canon, so a
        # dropped canon node is lost forever. Parking it in the pen lets a later bless still land it.
        camp = _camp()
        transcript.append(camp / "t.jsonl", "player", "x")
        transcript.append(camp / "t.jsonl", "narrator", "y")
        orig = llm.complete
        llm.complete = lambda *a, **k: '{"nodes":[{"name":"The Vault","kind":"place","body":"deep"}],"state":{},"threads_new":[],"threads_resolved":[],"character_updates":[],"reputation":[]}'
        try:
            consolidate.auto(dict(config.DEFAULTS), camp / "t.jsonl", camp / "world", camp / "state.json",
                             apply_canon=False)
        finally:
            llm.complete = orig
        self.assertIsNone(canon.read_node(camp / "world", "The Vault"))          # gated (not auto-written)
        self.assertEqual(state.load(camp / "state.json").get("_consolidated"), 2)  # watermark moved PAST it
        self.assertEqual([n["name"] for n in consolidate.pending(camp / "state.json")], ["The Vault"])  # but parked
        consolidate.apply_pending(camp / "world", camp / "state.json")           # bless later
        self.assertIsNotNone(canon.read_node(camp / "world", "The Vault"))       # lands despite the watermark
        self.assertEqual(consolidate.pending(camp / "state.json"), [])           # pen emptied

    def test_pending_dedupes_and_declined_bless_drops_it(self):
        camp = _camp()
        consolidate.queue_pending(camp / "state.json", [{"name": "Wren", "body": "v1", "kind": "character", "fields": {}}])
        consolidate.queue_pending(camp / "state.json", [{"name": "Wren", "body": "v2", "kind": "character", "fields": {}}])
        self.assertEqual(len(consolidate.pending(camp / "state.json")), 1)       # dedup by name, latest wins
        self.assertEqual(consolidate.pending(camp / "state.json")[0]["body"], "v2")
        consolidate.apply_pending(camp / "world", camp / "state.json", approve=lambda *a: False)  # decline
        self.assertIsNone(canon.read_node(camp / "world", "Wren"))               # not written
        self.assertEqual(consolidate.pending(camp / "state.json"), [])           # a review pass is final — pen emptied

    def test_placeholder_state_key_is_dropped(self):
        # the schema's {"key":"value"} example, echoed verbatim, must not become a real fact
        p = consolidate._normalize({"state": {"key": "value", "mood": "warm", "<x>": "y", "fact name": "z"}})
        self.assertEqual(p["state"], {"mood": "warm"})

    def test_auto_writes_canon_when_opted_in(self):
        camp = _camp()
        transcript.append(camp / "t.jsonl", "player", "x")
        transcript.append(camp / "t.jsonl", "narrator", "y")
        orig = llm.complete
        llm.complete = lambda *a, **k: '{"nodes":[{"name":"A New Place","kind":"place","body":"x"}],"state":{},"threads_new":[],"threads_resolved":[],"character_updates":[],"reputation":[]}'
        try:
            consolidate.auto(dict(config.DEFAULTS), camp / "t.jsonl", camp / "world", camp / "state.json",
                             apply_canon=True)
        finally:
            llm.complete = orig
        self.assertIsNotNone(canon.read_node(camp / "world", "A New Place"))   # written when opted in

    def test_narrate_auto_consolidates_via_inbox(self):
        # the daemon only PROPOSES (parks in the inbox); the NEXT turn's _prepare drain applies it —
        # single-writer discipline, so the fold never races the turn's own state commit.
        camp = _camp()
        canon.write_node(camp / "world", "Room", "a room")
        state.save(camp / "state.json", {})
        cfg = dict(config.DEFAULTS)
        cfg.update(auto_consolidate=True, consolidate_every=2, scene_memory=False)
        calls = []
        oc, ocmp = llm.chat, llm.complete
        llm.chat = lambda *a, **k: "A beat."
        llm.complete = lambda *a, **k: (calls.append(1), '{"nodes":[],"state":{"x":"y"},"threads_new":[],"threads_resolved":[],"character_updates":[],"reputation":[]}')[1]
        try:
            narrate.turn("t1", cfg, camp / "t.jsonl", camp / "world", camp / "state.json")   # _cturn → 1
            self.assertEqual(len(calls), 0)
            narrate.turn("t2", cfg, camp / "t.jsonl", camp / "world", camp / "state.json")   # → 2 → daemon proposes
            if narrate._auto_thread:
                narrate._auto_thread.join(timeout=10)
            self.assertEqual(len(calls), 1)                                     # model called once (proposal)
            self.assertIsNone(state.load(camp / "state.json").get("x"))         # PARKED, not yet applied to state
            narrate.turn("t3", cfg, camp / "t.jsonl", camp / "world", camp / "state.json")   # _prepare drains → applies
            self.assertEqual(state.load(camp / "state.json").get("x"), "y")     # now folded in, on the turn thread
        finally:
            llm.chat, llm.complete = oc, ocmp


    def test_backlog_folds_in_capped_windows(self):
        # a big backlog (e.g. after an undo reset the watermark) must fold in bounded chunks, not one
        # giant timeout-prone call — the daemon's window is capped at wm + consolidate_window
        camp = _camp()
        canon.write_node(camp / "world", "Room", "a room")
        for i in range(15):
            transcript.append(camp / "t.jsonl", "player", f"p{i}")
            transcript.append(camp / "t.jsonl", "narrator", f"n{i}")   # 30 entries, watermark 0 → big backlog
        state.save(camp / "state.json", {"_consolidated": 0, "_cturn": 1})   # one more turn hits the cadence
        cfg = dict(config.DEFAULTS)
        cfg.update(auto_consolidate=True, consolidate_every=2, consolidate_window=16, scene_memory=False)
        oc, ocmp = llm.chat, llm.complete
        llm.chat = lambda *a, **k: "beat."
        llm.complete = lambda *a, **k: '{"nodes":[],"state":{"x":"y"},"threads_new":[],"threads_resolved":[],"character_updates":[],"reputation":[]}'
        try:
            narrate.turn("go", cfg, camp / "t.jsonl", camp / "world", camp / "state.json")   # _cturn 0→1 → fires
            if narrate._auto_thread:
                narrate._auto_thread.join(timeout=10)
        finally:
            llm.chat, llm.complete = oc, ocmp
        jobs = inbox.take(camp / "state.json")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["start"], 0)
        self.assertEqual(jobs[0]["end"], 16)                            # capped at wm+16, NOT the full backlog


class DeedKeyTest(unittest.TestCase):
    def test_deed_key_prevents_reputation_double_apply(self):
        # additive apply_delta must run at most once per (who, window); a re-fold of the SAME window
        # (undo/crash/manual re-run) is idempotent.
        camp = _camp()
        prop = {"nodes": [], "state": {}, "threads_new": [], "threads_resolved": [],
                "character_updates": [], "reputation": [{"who": "The Order", "delta": 2, "because": "a deed"}]}
        consolidate.apply(prop, camp / "world", camp / "state.json", lambda *a: True, deed_window=(0, 8), watermark=8)
        rep = reputation.load(state.load(camp / "state.json"))
        self.assertEqual(rep["The Order"]["standing"], 2)
        consolidate.apply(prop, camp / "world", camp / "state.json", lambda *a: True, deed_window=(0, 8), watermark=8)
        rep = reputation.load(state.load(camp / "state.json"))
        self.assertEqual(rep["The Order"]["standing"], 2)                       # NOT 4 — the re-fold no-op'd
        self.assertEqual(len(rep["The Order"]["log"]), 1)                       # and the deed logged once

    def test_no_deed_window_keeps_legacy_additive_behaviour(self):
        camp = _camp()
        prop = {"nodes": [], "state": {}, "threads_new": [], "threads_resolved": [],
                "character_updates": [], "reputation": [{"who": "X", "delta": 1, "because": "d"}]}
        consolidate.apply(prop, camp / "world", camp / "state.json", lambda *a: True)   # no deed_window
        consolidate.apply(prop, camp / "world", camp / "state.json", lambda *a: True)
        rep = reputation.load(state.load(camp / "state.json"))
        self.assertEqual(rep["X"]["standing"], 2)                               # legacy path still additive

    def test_watermark_is_monotonic_against_stale_apply(self):
        # a stale manual apply (dialog opened before a later fold advanced the watermark) must NOT
        # regress _consolidated — else the turns between re-fold under a fresh deed-key and double-apply
        camp = _camp()
        state.set_fact(camp / "state.json", "_consolidated", 20)          # a later fold already reached 20
        prop = {"nodes": [], "state": {"m": "v"}, "threads_new": [], "threads_resolved": [],
                "character_updates": [], "reputation": []}
        consolidate.apply(prop, camp / "world", camp / "state.json", lambda *a: True,
                          deed_window=(0, 10), watermark=10)              # stale apply for the OLD window
        self.assertEqual(state.load(camp / "state.json").get("_consolidated"), 20)  # NOT rolled back to 10

    def test_combined_watermark_saves_with_rep(self):
        camp = _camp()
        prop = {"nodes": [], "state": {"m": "v"}, "threads_new": [], "threads_resolved": [],
                "character_updates": [], "reputation": []}
        consolidate.apply(prop, camp / "world", camp / "state.json", lambda *a: True, deed_window=(0, 4), watermark=4)
        st = state.load(camp / "state.json")
        self.assertEqual(st.get("m"), "v")
        self.assertEqual(st.get("_consolidated"), 4)                           # advanced in the SAME save


class DrainTest(unittest.TestCase):
    def _job(self, start, end, state_kv):
        return {"start": start, "end": end, "apply_canon": False, "proposals": {
            "nodes": [], "state": state_kv, "threads_new": [], "threads_resolved": [],
            "character_updates": [], "reputation": []}}

    def test_drain_applies_contiguous_and_advances_watermark(self):
        camp = _camp()
        for _ in range(4):
            transcript.append(camp / "t.jsonl", "player", "p")
        inbox.append(camp / "state.json", self._job(0, 4, {"a": "1"}))
        consolidate.drain_inbox({}, camp / "t.jsonl", camp / "world", camp / "state.json")
        st = state.load(camp / "state.json")
        self.assertEqual(st.get("a"), "1")
        self.assertEqual(st.get("_consolidated"), 4)
        self.assertEqual(inbox.take(camp / "state.json"), [])                   # inbox emptied

    def test_drain_discards_orphan_beyond_transcript(self):
        # an undo took the turns back → the job's window exceeds the transcript → discard, don't apply
        camp = _camp()
        transcript.append(camp / "t.jsonl", "player", "p")                     # only 1 entry
        inbox.append(camp / "state.json", self._job(0, 8, {"a": "1"}))         # job wants [0,8)
        consolidate.drain_inbox({}, camp / "t.jsonl", camp / "world", camp / "state.json")
        self.assertIsNone(state.load(camp / "state.json").get("a"))            # NOT applied
        self.assertEqual(inbox.take(camp / "state.json"), [])                   # and dropped, not re-queued

    def test_drain_requeues_non_contiguous_job(self):
        # a later window arrives before its predecessor folded → keep it for a later drain, don't drop
        camp = _camp()
        for _ in range(16):
            transcript.append(camp / "t.jsonl", "player", "p")
        inbox.append(camp / "state.json", self._job(8, 16, {"b": "2"}))        # starts past the watermark (0)
        consolidate.drain_inbox({}, camp / "t.jsonl", camp / "world", camp / "state.json")
        self.assertIsNone(state.load(camp / "state.json").get("b"))            # not applied yet
        requeued = inbox.take(camp / "state.json")
        self.assertEqual([(j["start"], j["end"]) for j in requeued], [(8, 16)])  # re-queued intact

    def test_drain_orders_out_of_order_completion(self):
        # daemon for [8,16) finished before [0,8) — drain must sort and apply both contiguously
        camp = _camp()
        for _ in range(16):
            transcript.append(camp / "t.jsonl", "player", "p")
        inbox.append(camp / "state.json", self._job(8, 16, {"b": "2"}))        # appended first (out of order)
        inbox.append(camp / "state.json", self._job(0, 8, {"a": "1"}))
        consolidate.drain_inbox({}, camp / "t.jsonl", camp / "world", camp / "state.json")
        st = state.load(camp / "state.json")
        self.assertEqual((st.get("a"), st.get("b")), ("1", "2"))              # both applied, in order
        self.assertEqual(st.get("_consolidated"), 16)

    def test_drain_drops_regrown_window_by_fingerprint(self):
        # the length-only orphan guard can't tell an undone-THEN-REGROWN window (same length, different
        # play) from the original; the content fingerprint must drop the stale fold so it never applies
        # over different turns and the watermark never skips the real new play.
        camp = _camp()
        transcript.append(camp / "t.jsonl", "player", "original-A")
        transcript.append(camp / "t.jsonl", "narrator", "original-B")
        old_fp = consolidate.window_fingerprint(transcript.read_all(camp / "t.jsonl")[0:2])
        # the player undid + replayed: SAME length, DIFFERENT content
        transcript.rewrite(camp / "t.jsonl", [{"role": "player", "text": "replayed-X"},
                                              {"role": "narrator", "text": "replayed-Y"}])
        job = {"start": 0, "end": 2, "apply_canon": False, "fp": old_fp,
               "proposals": {"nodes": [], "state": {"stale": "1"}, "threads_new": [],
                             "threads_resolved": [], "character_updates": [], "reputation": []}}
        inbox.append(camp / "state.json", job)
        consolidate.drain_inbox({}, camp / "t.jsonl", camp / "world", camp / "state.json")
        self.assertIsNone(state.load(camp / "state.json").get("stale"))       # stale fold dropped
        self.assertIn(state.load(camp / "state.json").get("_consolidated"), (None, 0))  # watermark did NOT skip real turns
        self.assertEqual(inbox.take(camp / "state.json"), [])                 # and not re-queued


class WebLockTest(unittest.TestCase):
    def test_write_lock_covers_mutating_posts(self):
        # the single-writer invariant is enforced server-side: mutating POSTs take the write lock,
        # pure propose/preview POSTs are exempt (so a slow model call doesn't stall a turn)
        from loom import web
        self.assertTrue(hasattr(web, "_WRITE_LOCK"))
        for p in ("/api/turn", "/api/turn/stream", "/api/consolidate/apply", "/api/pending/apply",
                  "/api/sleep", "/api/undo", "/api/retry", "/api/config"):
            self.assertNotIn(p, web._READONLY_POSTS, f"{p} must be write-locked")
        for p in ("/api/consolidate", "/api/imagine", "/api/assist", "/api/generate"):
            self.assertIn(p, web._READONLY_POSTS, f"{p} is pure-propose, should be lock-exempt")


if __name__ == "__main__":
    unittest.main()
