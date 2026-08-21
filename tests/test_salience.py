"""Salience tiering: the cast + world sorted into world / main / antagonist / side / passing from
grounded signals, with an explicit importance: override winning (the hybrid). Antagonism means
opposition to the PLAYER (hostile disposition / negative standing) — NOT a character's own inner
conflict. Offline, deterministic."""
import tempfile
import unittest
from pathlib import Path
from loom import salience, canon, state, transcript


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


def _tiers(camp):
    return {t["key"]: [c["name"] for c in t["cards"]]
            for t in salience.classify(camp / "world", camp / "t.jsonl", camp / "state.json")}


def _cards(camp):
    return {c["name"]: c for t in salience.classify(camp / "world", camp / "t.jsonl", camp / "state.json")
            for c in t["cards"]}


class SalienceTest(unittest.TestCase):
    def test_world_tier_holds_the_fabric_setting_first(self):
        camp = _camp()
        canon.write_node(camp / "world", "Harbor", "a harbor", {"kind": "place"})
        canon.write_node(camp / "world", "The Realm", "a realm", {"kind": "lore", "setting": "true"})
        world = _tiers(camp)["world"]
        self.assertEqual(world[0], "The Realm")     # the flagged setting sorts first
        self.assertIn("Harbor", world)

    def test_hostile_disposition_is_a_primary_antagonist(self):
        camp = _camp()
        canon.write_node(camp / "world", "Harbor", "a harbor", {"kind": "place"})
        canon.write_node(camp / "world", "Grax", "a warlord [[Harbor]]",
                         {"kind": "character", "role": "warlord", "wants": "to burn the realm",
                          "disposition": "hostile, wants the player dead"})
        self.assertIn("Grax", _tiers(camp)["antagonist"])

    def test_factions_are_filed_under_their_own_band(self):
        # a faction is a GROUP, not an individual — it belongs under Factions & groups (never the
        # character tiers), even with a hostile standing (its card still shows the standing)
        camp = _camp()
        canon.write_node(camp / "world", "The Cult", "a cult", {"kind": "faction"})
        state.save(camp / "state.json", {"_rep": {"The Cult": {"standing": -2, "log": ["▼ you burned their shrine"]}}})
        t = _tiers(camp)
        self.assertIn("The Cult", t["factions"])
        self.assertNotIn("The Cult", t["antagonist"] + t["main"] + t["side"] + t["passing"])

    def test_inner_conflict_is_not_antagonism(self):
        # a sympathetic NPC with a want held back (moral tension) must NOT be tiered as an antagonist
        camp = _camp()
        canon.write_node(camp / "world", "Harbor", "a harbor", {"kind": "place"})
        canon.write_node(camp / "world", "Mara", "a healer [[Harbor]]",
                         {"kind": "character", "role": "healer", "wants": "to find her lost son",
                          "bound": "a vow of silence", "disposition": "kind but guarded"})
        t = _tiers(camp)
        self.assertNotIn("Mara", t["antagonist"])
        self.assertIn("Mara", t["side"] + t["main"] + t["passing"])   # tiered by salience, not opposition

    def test_importance_override_wins_and_is_flagged(self):
        camp = _camp()
        canon.write_node(camp / "world", "Bob", "a nobody", {"kind": "character", "importance": "main"})
        canon.write_node(camp / "world", "Smiler", "warm and kind",
                         {"kind": "character", "importance": "antagonist", "disposition": "warm"})
        t, cards = _tiers(camp), _cards(camp)
        self.assertIn("Bob", t["main"])              # pinned up despite zero salience
        self.assertIn("Smiler", t["antagonist"])     # pinned antagonist despite a warm disposition
        self.assertTrue(cards["Bob"]["overridden"])

    def test_score_orders_within_a_tier(self):
        camp = _camp()
        canon.write_node(camp / "world", "Hub", "a hub", {"kind": "place"})
        canon.write_node(camp / "world", "Busy", "linked [[Hub]]", {"kind": "character", "importance": "side"})
        canon.write_node(camp / "world", "Quiet", "alone", {"kind": "character", "importance": "side"})
        side = _tiers(camp)["side"]
        self.assertLess(side.index("Busy"), side.index("Quiet"))   # more connected sorts higher


if __name__ == "__main__":
    unittest.main()


class CharRungTest(unittest.TestCase):
    """char_rung(tier, depth): the depth-modulation primitive — personhood budget = tier × depth."""

    def test_tier_and_depth_scale(self):
        self.assertEqual(salience.char_rung("main", 1.0), 1.0)
        self.assertEqual(salience.char_rung("main", 0.5), 0.5)
        self.assertEqual(salience.char_rung("side", 1.0), 0.5)
        self.assertEqual(salience.char_rung("passing", 1.0), 0.0)     # a walk-on is never a person
        self.assertEqual(salience.char_rung("world", 1.0), 0.0)       # setting isn't an agent

    def test_depth_zero_darkens_everyone(self):
        for t in ("main", "antagonist", "side", "passing"):
            self.assertEqual(salience.char_rung(t, 0.0), 0.0)

    def test_bad_inputs_are_zero_not_crash(self):
        self.assertEqual(salience.char_rung("nonsense", 1.0), 0.0)
        self.assertEqual(salience.char_rung("main", None), 0.0)
        self.assertEqual(salience.char_rung("main", "x"), 0.0)

    def test_recall_k_scales(self):
        self.assertEqual(salience.recall_k(salience.char_rung("main", 1.0)), 4)
        self.assertEqual(salience.recall_k(salience.char_rung("side", 1.0)), 2)
        self.assertEqual(salience.recall_k(salience.char_rung("passing", 1.0)), 0)

    def test_gates(self):
        # agenda: main from depth 0.5, side only at depth 1.0, passing never
        self.assertTrue(salience.has_agenda(salience.char_rung("main", 0.5)))
        self.assertTrue(salience.has_agenda(salience.char_rung("side", 1.0)))
        self.assertFalse(salience.has_agenda(salience.char_rung("side", 0.5)))
        self.assertFalse(salience.has_agenda(salience.char_rung("passing", 1.0)))
        # deliberation: main/antagonist at high depth only; side never reaches it
        self.assertTrue(salience.deliberates(salience.char_rung("main", 0.8)))
        self.assertFalse(salience.deliberates(salience.char_rung("side", 1.0)))

    def test_tiers_by_name_maps_cast(self):
        camp = _camp()
        canon.write_node(camp / "world", "Mara", "a fisher", {"kind": "character", "importance": "main"})
        canon.write_node(camp / "world", "Harbor", "a cold harbor", {"kind": "place"})
        t = _camp() and salience.tiers_by_name(camp / "world", camp / "t.jsonl", camp / "state.json")
        self.assertEqual(t.get("Mara"), "main")           # explicit override honored
        self.assertEqual(t.get("Harbor"), "world")        # a place is world-fabric


class NarratorDiscountTest(unittest.TestCase):
    """Red-team #1: a character's own world-round beats reach the transcript as NARRATOR prose; those
    must not pump its salience/tier (the self-amplification decay._recency already guards against)."""

    def _tiers(self, camp, t):
        return {g["key"]: [c["name"] for c in g["cards"]]
                for g in salience.classify(camp / "world", t, camp / "state.json")}

    def test_narrator_mentions_cannot_promote_a_tier(self):
        camp = _camp()
        canon.write_node(camp / "world", "Wren", "a cadet", {"kind": "character", "wants": "to leave"})
        t = camp / "t.jsonl"
        for _ in range(8):                                   # the narrator names Wren relentlessly (its own beats)
            transcript.append(t, "narrator", "Wren does something Wren-ish; Wren, Wren, Wren.")
        self.assertNotIn("Wren", self._tiers(camp, t).get("main", []))   # capped → stays side

    def test_player_mentions_still_promote(self):
        camp = _camp()
        canon.write_node(camp / "world", "Wren", "a cadet", {"kind": "character", "wants": "to leave"})
        t = camp / "t.jsonl"
        for _ in range(8):                                   # the PLAYER engaging Wren lifts the tier (full weight)
            transcript.append(t, "player", "I seek out Wren; Wren, Wren, hello Wren.")
        self.assertIn("Wren", self._tiers(camp, t).get("main", []))
