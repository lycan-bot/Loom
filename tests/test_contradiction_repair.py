"""Contradiction-repair (Primarch reconsolidation-arbiter pattern): a disposition VALENCE flip proposed
by the AUTO-drain (no operator authority) is HELD for the operator instead of silently overwriting an
established feeling; the manual path (operator present) applies. A progression / first-set passes.
Offline, deterministic."""
import tempfile
import unittest
from pathlib import Path
from loom import consolidate, canon


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


def _char(camp, disp="warm and trusting"):
    fm = {"kind": "character"}
    if disp:
        fm["disposition"] = disp
    canon.write_node(camp / "world", "Mara", "a fisher", fm)


def _disp(camp):
    return canon.read_node(camp / "world", "Mara")["frontmatter"].get("disposition")


class HoldTest(unittest.TestCase):
    def test_auto_reversal_is_held_not_applied(self):
        camp = _camp(); _char(camp); sp = camp / "state.json"
        w = consolidate.apply({"character_updates": [{"name": "Mara", "disposition": "hostile"}]},
                              camp / "world", sp, approve=lambda *a: True, deed_window=(1, 2), hold_reversals=True)
        self.assertIn("Mara", w["held_reversals"])
        self.assertEqual(_disp(camp), "warm and trusting")           # the established feeling is NOT overwritten
        pen = consolidate.pending_reversals(sp)
        self.assertEqual([(r["old"], r["new"]) for r in pen], [("warm and trusting", "hostile")])
        self.assertEqual(w["dispositions"], [])                      # nothing applied

    def test_progression_applies_not_held(self):
        camp = _camp(); _char(camp, "warm"); sp = camp / "state.json"
        consolidate.apply({"character_updates": [{"name": "Mara", "disposition": "warmer"}]},
                          camp / "world", sp, approve=lambda *a: True, deed_window=(1, 2), hold_reversals=True)
        self.assertEqual(_disp(camp), "warmer")                      # same valence → applied
        self.assertEqual(consolidate.pending_reversals(sp), [])

    def test_first_time_set_applies(self):
        camp = _camp(); _char(camp, ""); sp = camp / "state.json"    # no prior disposition
        consolidate.apply({"character_updates": [{"name": "Mara", "disposition": "hostile"}]},
                          camp / "world", sp, approve=lambda *a: True, deed_window=(1, 2), hold_reversals=True)
        self.assertEqual(_disp(camp), "hostile")                     # no established feeling to contradict → applied
        self.assertEqual(consolidate.pending_reversals(sp), [])

    def test_manual_path_applies_the_reversal(self):
        camp = _camp(); _char(camp); sp = camp / "state.json"        # hold_reversals=False (the operator is present)
        consolidate.apply({"character_updates": [{"name": "Mara", "disposition": "hostile"}]},
                          camp / "world", sp, approve=lambda *a: True, deed_window=(1, 2))
        self.assertEqual(_disp(camp), "hostile")                     # operator authority → applied
        self.assertEqual(consolidate.pending_reversals(sp), [])

    def test_fold_proposals_auto_holds(self):
        camp = _camp(); _char(camp, "warm"); sp = camp / "state.json"
        consolidate._fold_proposals({"character_updates": [{"name": "Mara", "disposition": "hostile"}]},
                                    camp / "world", sp, 0, 2, apply_canon=False)   # the live auto path
        self.assertEqual(len(consolidate.pending_reversals(sp)), 1)
        self.assertEqual(_disp(camp), "warm")                        # held, not flipped


class DecideTest(unittest.TestCase):
    def _held(self, camp):
        _char(camp, "warm and fond")
        sp = camp / "state.json"
        consolidate.apply({"character_updates": [{"name": "Mara", "disposition": "hostile"}]},
                          camp / "world", sp, approve=lambda *a: True, deed_window=(3, 4), hold_reversals=True)
        return sp

    def test_bless_applies_and_clears(self):
        camp = _camp(); sp = self._held(camp)
        self.assertTrue(consolidate.apply_reversal(camp / "world", sp, "Mara", "disposition", approve=lambda *a: True))
        self.assertEqual(_disp(camp), "hostile")                     # blessed → the flip lands
        self.assertEqual(consolidate.pending_reversals(sp), [])      # left the pen

    def test_reject_clears_without_applying(self):
        camp = _camp(); sp = self._held(camp)
        self.assertFalse(consolidate.apply_reversal(camp / "world", sp, "Mara", "disposition", approve=lambda *a: False))
        self.assertEqual(_disp(camp), "warm and fond")               # rejected → the feeling stands
        self.assertEqual(consolidate.pending_reversals(sp), [])      # a decision is final — never re-nags

    def test_dedup_latest_flip_wins(self):
        camp = _camp(); sp = self._held(camp)
        consolidate.queue_reversal(sp, [{"name": "Mara", "field": "disposition", "old": "warm and fond", "new": "wary"}])
        pen = consolidate.pending_reversals(sp)
        self.assertEqual(len(pen), 1)
        self.assertEqual(pen[0]["new"], "wary")                      # the later proposal wins the slot

    def test_pen_is_uncapped(self):
        # red-team HIGH: a held flip advances the watermark past its turns, so a silently-dropped
        # contradiction is lost forever — the pen must NOT cap (dedup already bounds it to one/decision)
        camp = _camp(); sp = camp / "state.json"
        consolidate.queue_reversal(sp, [{"name": f"NPC{i}", "field": "disposition", "old": "warm", "new": "hostile"}
                                        for i in range(25)])
        self.assertEqual(len(consolidate.pending_reversals(sp)), 25)   # all 25 distinct decisions retained


if __name__ == "__main__":
    unittest.main()
