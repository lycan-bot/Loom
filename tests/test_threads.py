"""The plan above canon: threads ripen with proximity + time, activate only when the
player is near their subject, and clocks tick down. Pure, offline."""
import json
import tempfile
import unittest
from pathlib import Path
from loom import threads
from loom.threads import Thread


class ThreadsTest(unittest.TestCase):
    def test_dormant_activates_only_when_near(self):
        t = Thread("x", "q", entities=["The Lighthouse"])
        newly = threads.advance([t], ["The Tavern"])          # far → stays dormant
        self.assertEqual(t.status, "dormant")
        self.assertEqual(newly, [])
        newly = threads.advance([t], ["The Lighthouse"])      # near → seeded + reported
        self.assertEqual(t.status, "seeded")
        self.assertIn(t, newly)

    def test_proximity_ripens_to_ready(self):
        t = Thread("x", "q", status="seeded", readiness=0.3, entities=["Harbor"])
        for _ in range(3):
            threads.advance([t], ["Harbor"])
        self.assertEqual(t.status, "ready")
        self.assertGreaterEqual(t.readiness, 0.7)

    def test_ambient_drift_is_slow(self):
        t = Thread("x", "q", status="seeded", readiness=0.3, entities=["Harbor"])
        threads.advance([t], ["Elsewhere"])                   # not near → slow drift only
        self.assertAlmostEqual(t.readiness, 0.35, places=6)
        self.assertEqual(t.status, "ripening")

    def test_ready_beats_accrues_while_ready_and_resets_below(self):
        # staleness: count consecutive beats spent 'ready'; a not-ready beat resets it to 0
        t = Thread("x", "q", status="ripening", readiness=0.65, entities=["Harbor"])
        threads.advance([t], ["Harbor"])                      # 0.65 + 0.30 = 0.95 → ready → 1 beat
        self.assertEqual((t.status, t.ready_beats), ("ready", 1))
        threads.advance([t], [])                              # still ready (drift keeps it ≥0.7) → 2
        self.assertEqual(t.ready_beats, 2)
        t.status, t.readiness = "ripening", 0.4              # dropped below ready (e.g. after an author edit)
        threads.advance([t], [])                              # ripening → counter resets
        self.assertEqual(t.ready_beats, 0)

    def test_clock_ticks_down_to_ready(self):
        t = Thread("s", "a storm", kind="clock", status="ripening", clock=2, entities=["World"])
        threads.advance([t], [])
        self.assertEqual(t.clock, 1)
        self.assertNotEqual(t.status, "ready")
        threads.advance([t], [])
        self.assertEqual(t.status, "ready")

    def test_load_is_robust_to_junk(self):
        d = Path(tempfile.mkdtemp()) / "threads.json"
        d.write_text('[{"id":"a","question":"q","bogus_key":1},{"no_id":true},"garbage"]')
        back = threads.load(d)                                 # extra key tolerated, junk dropped
        self.assertEqual([t.id for t in back], ["a"])

    def test_save_load_roundtrip(self):
        d = Path(tempfile.mkdtemp()) / "threads.json"
        threads.save(d, [Thread("a", "q1", entities=["N"]), Thread("b", "q2", kind="clock", clock=3)])
        back = threads.load(d)
        self.assertEqual([t.id for t in back], ["a", "b"])
        self.assertEqual(back[1].clock, 3)

    def test_stages_roundtrip(self):
        d = Path(tempfile.mkdtemp()) / "threads.json"
        threads.save(d, [Thread("a", "q", stages=["one", "two"], stage=1)])
        back = threads.load(d)
        self.assertEqual(back[0].stages, ["one", "two"])
        self.assertEqual(back[0].stage, 1)

    def test_hidden_defaults_false_on_legacy(self):
        # a legacy threads.json (no 'hidden' key) loads with hidden False and advance() doesn't crash
        d = Path(tempfile.mkdtemp()) / "threads.json"
        d.write_text('[{"id":"a","question":"q","entities":["N"]}]')
        back = threads.load(d)
        self.assertEqual(back[0].hidden, False)
        threads.advance(back, ["N"])                          # no crash

    def test_hidden_coerces_fail_soft(self):
        # a hand-edited non-bool hidden coerces to bool without crashing load()/advance()
        d = Path(tempfile.mkdtemp()) / "threads.json"
        d.write_text('[{"id":"a","question":"q","hidden":"yes"},{"id":"b","question":"q2","hidden":1}]')
        back = threads.load(d)
        self.assertEqual([t.hidden for t in back], [True, True])
        threads.advance(back, [])                             # no crash

    def test_hidden_roundtrips_and_is_the_known_ondisk_delta(self):
        # hidden survives save→load; and asdict now emits 'hidden' for EVERY thread (the reviewed on-disk delta)
        d = Path(tempfile.mkdtemp()) / "threads.json"
        threads.save(d, [Thread("a", "q", hidden=True), Thread("b", "q2")])
        back = threads.load(d)
        self.assertEqual([t.hidden for t in back], [True, False])
        raw = json.loads(d.read_text())
        self.assertEqual(raw[0]["hidden"], True)
        self.assertEqual(raw[1]["hidden"], False)             # additive delta: every thread now serializes 'hidden'

    def test_from_dict_coerces_and_defaults(self):
        # the single seed/coercion site: a raw payload becomes a well-formed Thread; missing id/question → None
        self.assertIsNone(threads.from_dict({"question": "no id"}))
        self.assertIsNone(threads.from_dict({"id": "x"}))
        th = threads.from_dict({"id": "c", "question": "the eclipse", "kind": "clock",
                                "clock": "30", "span": "30", "hidden": 1, "readiness": "0.5", "stage": "2"})
        self.assertEqual((th.clock, th.span, th.hidden, th.stage), (30, 30, True, 2))   # coerced from strings/ints
        self.assertEqual(th.readiness, 0.5)
        empty = threads.from_dict({"id": "e", "question": "q", "kind": "", "status": ""})
        self.assertEqual((empty.kind, empty.status), ("question", "dormant"))           # empty → dataclass defaults

    def test_span_defaults_and_is_stable_across_ticks(self):
        # Brick B: the AUTHORED span is a stable denominator — the clock decrements in place, span does not
        d = Path(tempfile.mkdtemp()) / "threads.json"
        threads.save(d, [threads.from_dict({"id": "c", "question": "the storm", "kind": "clock",
                                            "status": "ripening", "clock": 5, "span": 5})])
        th = threads.load(d)
        threads.advance(th, [])                               # one beat
        self.assertEqual((th[0].clock, th[0].span), (4, 5))   # clock ticks down, span stays the authored length
        threads.save(d, th)
        self.assertEqual(threads.load(d)[0].span, 5)          # span survives the roundtrip, immutable

    def test_seeded_clock_ticks_to_ready(self):
        # the whole point of Brick B: an operator-seeded clock is now a LIVE countdown (was unseedable)
        d = Path(tempfile.mkdtemp()) / "threads.json"
        threads.save(d, [threads.from_dict({"id": "c", "question": "the gate opens", "kind": "clock",
                                            "status": "ripening", "clock": 2, "span": 2})])
        back = threads.load(d)
        self.assertEqual((back[0].clock, back[0].span), (2, 2))    # survives save→load
        threads.advance(back, []); threads.advance(back, [])
        self.assertEqual(back[0].status, "ready")                  # ticked to ready — a live world clock

    def test_ready_clock_stops_ticking(self):
        # red-team fix: a clock stops decrementing once 'ready' — a hidden clock is never settled by Brick A,
        # so without this it would tick into unbounded negative state.
        t = Thread("c", "the god wakes", kind="clock", status="ripening", clock=2, span=2, hidden=True)
        for _ in range(6):
            threads.advance([t], [])
        self.assertEqual((t.status, t.clock), ("ready", 0))        # stopped at 0, not -4

    def test_seed_new_clock_defaults_span(self):
        d = Path(tempfile.mkdtemp()) / "threads.json"
        th, err = threads.seed(d, {"question": "the eclipse comes", "kind": "clock", "clock": 30})
        self.assertIsNone(err)
        self.assertEqual((th.kind, th.clock, th.span), ("clock", 30, 30))   # span defaults to the authored clock
        self.assertEqual(threads.load(d)[0].id, "the-eclipse-comes")

    def test_seed_refuses_no_id_collision_and_preserves_the_clock(self):
        # red-team fix: a NEW question slugging to an existing clock's id must NOT silently clobber it
        d = Path(tempfile.mkdtemp()) / "threads.json"
        threads.seed(d, {"question": "the siege breaks", "kind": "clock", "clock": 12, "hidden": True})
        th, err = threads.seed(d, {"question": "the siege breaks!!!"})      # make_id → same id, no explicit id
        self.assertIsNone(th)
        self.assertIn("already exists", err)
        kept = threads.load(d)                                              # the clock is untouched
        self.assertEqual((kept[0].kind, kept[0].clock, kept[0].hidden), ("clock", 12, True))

    def test_seed_explicit_id_is_an_edit(self):
        d = Path(tempfile.mkdtemp()) / "threads.json"
        threads.seed(d, {"question": "the siege breaks", "kind": "clock", "clock": 12})
        th, err = threads.seed(d, {"id": "the-siege-breaks", "question": "the siege finally breaks",
                                   "kind": "clock", "clock": 5})
        self.assertIsNone(err)                                             # explicit id → update in place
        kept = threads.load(d)
        self.assertEqual(len(kept), 1)
        self.assertEqual((kept[0].question, kept[0].clock), ("the siege finally breaks", 5))

    def test_seed_refuses_zero_or_negative_clock(self):
        d = Path(tempfile.mkdtemp()) / "threads.json"
        self.assertIn(">= 1", threads.seed(d, {"question": "x", "kind": "clock", "clock": 0})[1])
        self.assertIn(">= 1", threads.seed(d, {"question": "y", "kind": "clock", "clock": -3})[1])
        self.assertEqual(threads.load(d), [])                              # nothing seeded

    def test_scope_coerces_and_roundtrips(self):
        # Brick C: a thread is 'local' or 'horizon' (world-round metaplot); anything else → local (fail-soft)
        d = Path(tempfile.mkdtemp()) / "threads.json"
        threads.save(d, [threads.from_dict({"id": "h", "question": "q", "scope": "horizon"}),
                         threads.from_dict({"id": "l", "question": "q2"}),
                         threads.from_dict({"id": "b", "question": "q3", "scope": "bogus"})])
        self.assertEqual({t.id: t.scope for t in threads.load(d)},
                         {"h": "horizon", "l": "local", "b": "local"})

    def test_horizon_intensity(self):
        # Brick D: only a live HIDDEN horizon clock counts; intensity = 1 - clock/span, else None
        T = threads.Thread
        self.assertIsNone(threads.horizon_intensity([T(id="a", question="q")]))                       # not a clock
        self.assertIsNone(threads.horizon_intensity([T(id="c", question="q", kind="clock", scope="local",
                                                       hidden=True, clock=1, span=10)]))              # local scope
        self.assertIsNone(threads.horizon_intensity([T(id="c", question="q", kind="clock", scope="horizon",
                                                       hidden=False, clock=1, span=10)]))             # not hidden
        far = threads.horizon_intensity([T(id="c", question="q", kind="clock", scope="horizon",
                                          hidden=True, clock=10, span=10)])
        near = threads.horizon_intensity([T(id="c", question="q", kind="clock", scope="horizon",
                                           hidden=True, clock=1, span=10)])
        self.assertAlmostEqual(far, 0.0); self.assertAlmostEqual(near, 0.9)

    def test_player_visible_drops_hidden(self):
        # red-team fix (Brick D): loom is single-surface — a hidden (director-only) thread must NEVER reach a
        # player-facing display (the quest-book / the plan sidebar). It appears only once revealed.
        T = threads.Thread
        ths = [T(id="a", question="open"), T(id="b", question="secret", hidden=True), T(id="c", question="q2")]
        self.assertEqual([t.id for t in threads.player_visible(ths)], ["a", "c"])


if __name__ == "__main__":
    unittest.main()
