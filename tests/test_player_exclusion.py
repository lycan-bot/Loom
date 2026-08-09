"""The player's own character lives in canon (so the narrator knows them), but it is NOT an NPC:
it must be excluded from the world round, sleep drive-moves, and the cast rail — the PLAYER drives
it, not the world. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import canon, player, worldturn, npc, salience


def _world():
    camp = Path(tempfile.mkdtemp())
    w = camp / "world"
    w.mkdir()
    canon.write_node(w, "Tavern", "a tavern", {"kind": "place"})
    canon.write_node(w, "Rook", "a rogue [[Tavern]]", {"kind": "character", "wants": "the ledger", "location": "Tavern"})
    player.save(w, "Fáelán", role="a summoned wolf", wants="to protect its chosen", location="Tavern")
    return camp, w


class PlayerExclusionTest(unittest.TestCase):
    def test_is_player_predicate(self):
        _camp, w = _world()
        self.assertTrue(player.is_player(player.get(w)))
        self.assertFalse(player.is_player(canon.read_node(w, "Rook")))

    def test_world_round_excludes_the_player(self):
        _camp, w = _world()
        names = [node["name"] for node, _m, _loc in worldturn.majors(w)]
        self.assertIn("Rook", names)
        self.assertNotIn("Fáelán", names)          # the player never takes a world-round turn

    def test_sleep_drives_exclude_the_player(self):
        _camp, w = _world()
        names = [n for n, _m, _e in npc.drives(w)]
        self.assertIn("Rook", names)
        self.assertNotIn("Fáelán", names)          # the player's want isn't a world drive-move

    def test_cast_rail_excludes_the_player(self):
        camp, w = _world()
        allnames = [c["name"] for t in salience.classify(w, camp / "t.jsonl", camp / "state.json") for c in t["cards"]]
        self.assertIn("Rook", allnames)
        self.assertNotIn("Fáelán", allnames)       # it's you, not cast


if __name__ == "__main__":
    unittest.main()
