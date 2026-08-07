"""Player location: narrate tracks where the player is (the scene's place, persisted), weaves a
co-located NPC's world-turn into the next scene, and the world round routes turns AT the player's
place into that 'nearby' note vs the 'meanwhile' pulse elsewhere. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import narrate, worldturn, canon, state, llm, config


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class LocationTrackTest(unittest.TestCase):
    def test_location_set_from_the_scene_place(self):
        camp = _camp()
        canon.write_node(camp / "world", "The Docks", "the wharf where the fishing boats dock", {"kind": "place"})
        orig = llm.chat
        llm.chat = lambda *a, **k: "ok."
        try:
            narrate.turn("I walk the Docks and watch the boats.", dict(config.DEFAULTS),
                         camp / "t.jsonl", camp / "world", camp / "state.json")
        finally:
            llm.chat = orig
        self.assertEqual(state.load(camp / "state.json").get("_location"), "The Docks")

    def test_nearby_event_woven_in_then_cleared(self):
        camp = _camp()
        canon.write_node(camp / "world", "Room", "a room")
        state.save(camp / "state.json", {"_nearby": "The smith bars the door and arms himself."})
        cap = {}
        orig = llm.chat
        llm.chat = lambda m, c, **k: (cap.__setitem__("sys", m[0]["content"]), "ok.")[1]
        try:
            narrate.turn("I look up.", dict(config.DEFAULTS), camp / "t.jsonl", camp / "world", camp / "state.json")
        finally:
            llm.chat = orig
        self.assertIn("bars the door", cap["sys"])                       # woven into the prompt
        self.assertIsNone(state.load(camp / "state.json").get("_nearby"))  # consumed once, then cleared


class RoutingTest(unittest.TestCase):
    def test_colocated_turn_routes_into_the_scene(self):
        camp = _camp()
        canon.write_node(camp / "world", "Tavern", "a tavern", {"kind": "place"})
        canon.write_node(camp / "world", "Rook", "a rogue", {"kind": "character", "wants": "the ledger", "location": "Tavern"})
        state.save(camp / "state.json", {"_location": "Tavern", "_wturn": 0})
        cfg = dict(config.DEFAULTS); cfg["world_rounds"] = True; cfg["depth"] = 1.0; cfg["world_cadence"] = 1
        orig = llm.complete
        llm.complete = lambda *a, **k: ('{"turns":[{"where":"Tavern","who":["Rook"],"beat":"Rook slips the ledger into his coat."},'
                                        '{"where":"The Docks","who":["Vane"],"beat":"Vane watches the tide."}]}')
        try:
            pulse = worldturn.maybe_round(cfg, camp / "world", camp / "state.json")
        finally:
            llm.complete = orig
        self.assertIn("ledger into his coat", state.load(camp / "state.json").get("_nearby", ""))  # here → nearby
        self.assertEqual([t["where"] for t in pulse], ["The Docks"])                                # elsewhere → pulse


if __name__ == "__main__":
    unittest.main()
