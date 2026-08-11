"""Player location: narrate tracks where the player is (the scene's place, persisted), weaves a
co-located NPC's world-turn into the next scene, and the world round routes turns AT the player's
place into that 'nearby' note vs the 'meanwhile' pulse elsewhere. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import narrate, worldturn, canon, state, llm, config, transcript


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

    def test_colocation_matches_across_article_and_case(self):
        # "the library" (player) vs "Library" (world round) must co-locate — the raw string compare
        # missed the article/case difference; both sides now route through the place normalizer
        camp = _camp()
        canon.write_node(camp / "world", "The Library", "a hall of books", {"kind": "place"})
        canon.write_node(camp / "world", "Wren", "a cadet",
                         {"kind": "character", "wants": "a grimoire", "location": "The Library"})
        state.save(camp / "state.json", {"_location": "the library", "_wturn": 0})
        cfg = dict(config.DEFAULTS); cfg["world_rounds"] = True; cfg["depth"] = 1.0; cfg["world_cadence"] = 1
        orig = llm.complete
        llm.complete = lambda *a, **k: '{"turns":[{"where":"Library","who":["Wren"],"beat":"Wren pulls a grimoire from the shelf."}]}'
        try:
            pulse = worldturn.maybe_round(cfg, camp / "world", camp / "state.json")
        finally:
            llm.complete = orig
        self.assertIn("grimoire from the shelf", state.load(camp / "state.json").get("_nearby", ""))  # co-located
        self.assertEqual(pulse, [])                                                                   # nothing to the pulse

    def test_scene_present_npc_excluded_from_world_round(self):
        # an NPC NAMED in the live scene (the narrator is voicing them) must not also run as an
        # off-screen world-round actor — the fix for the companion appearing 'elsewhere'
        camp = _camp()
        canon.write_node(camp / "world", "Wren", "a cadet",
                         {"kind": "character", "wants": "to master wards", "location": "Aldermere College"})
        canon.write_node(camp / "world", "Professor Ysolde Finch", "a professor",
                         {"kind": "character", "wants": "to document a familiar", "location": "The Grand Library"})
        canon.write_node(camp / "world", "Vane", "a rogue",
                         {"kind": "character", "wants": "the ledger", "location": "The Docks"})
        transcript.append(camp / "t.jsonl", "player", "I lean against Wren and close my eyes")
        transcript.append(camp / "t.jsonl", "narrator", "Wren rests a hand in your fur, thoughtful")
        ex = worldturn.scene_characters(dict(config.DEFAULTS), camp / "world", camp / "t.jsonl")
        self.assertIn("Wren", ex)                                     # named in the scene → excluded
        self.assertNotIn("Vane", ex)                                 # not present
        self.assertNotIn("Professor Ysolde Finch", ex)               # a title word ('Professor') must NOT match
        names = [n[0]["name"] for n in worldturn.majors(camp / "world", exclude=ex)]
        self.assertNotIn("Wren", names)                              # dropped from the round
        self.assertIn("Vane", names)                                 # off-scene NPC still rounds


if __name__ == "__main__":
    unittest.main()
