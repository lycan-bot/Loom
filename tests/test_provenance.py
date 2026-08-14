"""Reconciliation + provenance at the diode (the memory keystone): a change to durable truth —
disposition, location, a state fact — is recorded old→new instead of silently clobbered, a contradicting
REVERSAL is flagged, and an undo rolls the ledger back with the turn. Offline."""
import json
import tempfile
import unittest
from pathlib import Path
from loom import consolidate, provenance, state, canon, undo, transcript


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class ReversalLogicTest(unittest.TestCase):
    def test_disposition_valence_flip_is_reversal(self):
        self.assertTrue(provenance.is_reversal("disposition", "warm", "hostile"))
        self.assertTrue(provenance.is_reversal("disposition", "friendly and trusting", "cold, guarded"))

    def test_disposition_deepening_is_not_reversal(self):
        self.assertFalse(provenance.is_reversal("disposition", "warm", "warmer"))
        self.assertFalse(provenance.is_reversal("disposition", "wary", "warier"))   # same valence, deeper

    def test_neutral_shift_is_not_flagged(self):
        # neither side carries a known valence → not a *contradiction* (nothing to reverse)
        self.assertFalse(provenance.is_reversal("disposition", "curious about the relic", "focused on the relic"))

    def test_location_change_is_a_candidate(self):
        self.assertTrue(provenance.is_reversal("location", "The Docks", "The Tavern"))

    def test_no_prior_value_is_never_a_reversal(self):
        self.assertFalse(provenance.is_reversal("disposition", "", "hostile"))
        self.assertFalse(provenance.is_reversal("location", None, "The Tavern"))


class LedgerTest(unittest.TestCase):
    def test_log_and_history_roundtrip(self):
        camp = _camp()
        sp = camp / "state.json"
        provenance.log(sp, [{"kind": "character", "name": "Mara", "field": "disposition",
                             "old": "cold", "new": "warm", "entry_start": 3, "entry_end": 4}])
        h = provenance.history(sp, name="Mara")
        self.assertEqual(len(h), 1)
        self.assertEqual((h[0]["old"], h[0]["new"]), ("cold", "warm"))

    def test_log_skips_noops(self):
        camp = _camp()
        sp = camp / "state.json"
        self.assertEqual(provenance.log(sp, [{"name": "X", "field": "f", "old": "a", "new": "a"}]), 0)
        self.assertEqual(provenance.log(sp, [{"name": "X", "field": "f", "old": "a", "new": ""}]), 0)
        self.assertEqual(provenance.entries(sp), [])

    def test_history_newest_first_and_filtered(self):
        camp = _camp()
        sp = camp / "state.json"
        provenance.log(sp, [{"name": "Mara", "field": "disposition", "old": "cold", "new": "warm"}])
        provenance.log(sp, [{"name": "Rook", "field": "location", "old": "Docks", "new": "Tavern"}])
        provenance.log(sp, [{"name": "Mara", "field": "disposition", "old": "warm", "new": "wary"}])
        mara = provenance.history(sp, name="Mara")
        self.assertEqual([r["new"] for r in mara], ["wary", "warm"])       # newest first
        self.assertEqual(len(provenance.history(sp, field="location")), 1)

    def test_reversals_filter(self):
        camp = _camp()
        sp = camp / "state.json"
        provenance.log(sp, [{"name": "A", "field": "disposition", "old": "warm", "new": "warmer",
                             "entry_start": 2, "reversal": False}])
        provenance.log(sp, [{"name": "B", "field": "disposition", "old": "warm", "new": "hostile",
                             "entry_start": 5, "reversal": True}])
        self.assertEqual([r["name"] for r in provenance.reversals(sp)], ["B"])
        self.assertEqual(provenance.reversals(sp, since_entry=6), [])       # window excludes it


class ReconcileAtDiodeTest(unittest.TestCase):
    def test_disposition_change_is_recorded_not_clobbered(self):
        camp = _camp()
        canon.write_node(camp / "world", "Mara", "A fisher.", {"kind": "character", "disposition": "cold"})
        consolidate.apply({"character_updates": [{"name": "Mara", "disposition": "warm"}]},
                          camp / "world", camp / "state.json", approve=lambda *a: True, deed_window=(7, 8))
        # canon still updates (last value stands)…
        self.assertEqual(canon.read_node(camp / "world", "Mara")["frontmatter"]["disposition"], "warm")
        # …but the old value is preserved in the ledger with the turn-window
        h = provenance.history(camp / "state.json", name="Mara", field="disposition")
        self.assertEqual(len(h), 1)
        self.assertEqual((h[0]["old"], h[0]["new"], h[0]["entry_start"]), ("cold", "warm", 7))
        # the ledger records the sign-cross factually (cold↔warm); whether a flip is *suspicious* is the
        # guard's later call (was there a cause this window?) — the ledger just never loses the old value
        self.assertTrue(h[0]["reversal"])

    def test_hostile_flip_is_flagged_reversal(self):
        camp = _camp()
        canon.write_node(camp / "world", "Mara", "A fisher.",
                         {"kind": "character", "disposition": "warm and trusting"})
        consolidate.apply({"character_updates": [{"name": "Mara", "disposition": "hostile"}]},
                          camp / "world", camp / "state.json", approve=lambda *a: True)
        self.assertEqual([r["name"] for r in provenance.reversals(camp / "state.json")], ["Mara"])

    def test_first_time_set_logs_nothing(self):
        camp = _camp()
        canon.write_node(camp / "world", "Mara", "A fisher.", {"kind": "character"})  # no prior disposition
        consolidate.apply({"character_updates": [{"name": "Mara", "disposition": "warm"}]},
                          camp / "world", camp / "state.json", approve=lambda *a: True)
        self.assertEqual(provenance.entries(camp / "state.json"), [])       # nothing to reconcile

    def test_refused_change_logs_nothing(self):
        camp = _camp()
        canon.write_node(camp / "world", "Mara", "A fisher.", {"kind": "character", "disposition": "cold"})
        consolidate.apply({"character_updates": [{"name": "Mara", "disposition": "warm"}]},
                          camp / "world", camp / "state.json", approve=lambda *a: False)  # gate says no
        self.assertEqual(provenance.entries(camp / "state.json"), [])       # the ledger only records blessed writes

    def test_location_move_is_recorded(self):
        camp = _camp()
        canon.write_node(camp / "world", "Rook", "A rogue.",
                         {"kind": "character", "location": "The Docks"})
        consolidate.apply({"character_updates": [{"name": "Rook", "location": "The Tavern"}]},
                          camp / "world", camp / "state.json", approve=lambda *a: True)
        h = provenance.history(camp / "state.json", name="Rook", field="location")
        self.assertEqual((h[0]["old"], h[0]["new"]), ("The Docks", "The Tavern"))

    def test_state_fact_change_is_recorded(self):
        camp = _camp()
        sp = camp / "state.json"
        state.save(sp, {"beacon": "unlit"})
        consolidate.apply({"state": {"beacon": "lit"}}, camp / "world", sp, approve=lambda *a: True)
        h = provenance.history(sp, field="beacon")
        self.assertEqual((h[0]["old"], h[0]["new"]), ("unlit", "lit"))


class UndoRollsBackLedgerTest(unittest.TestCase):
    def test_undo_truncates_facts_log(self):
        camp = _camp()
        sp, tp = camp / "state.json", camp / "transcript.jsonl"
        canon.write_node(camp / "world", "Mara", "A fisher.", {"kind": "character", "disposition": "cold"})
        transcript.append(tp, "player", "hi")
        undo.snapshot(tp, sp)                                # snapshot BEFORE the fold (0 facts recorded)
        consolidate.apply({"character_updates": [{"name": "Mara", "disposition": "warm"}]},
                          camp / "world", sp, approve=lambda *a: True)
        self.assertEqual(len(provenance.entries(sp)), 1)
        undo.undo(tp, sp)
        self.assertEqual(provenance.entries(sp), [])         # the recorded change rolled back with the turn


if __name__ == "__main__":
    unittest.main()
