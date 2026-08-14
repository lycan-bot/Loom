"""Player-as-canon: the player authors their own character; the narrator then addresses them as
that person. Stored as a character node flagged player:true, one per campaign. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import player, canon, narrate, llm, config, provenance


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class PlayerCardTest(unittest.TestCase):
    def test_save_and_read_back(self):
        camp = _camp()
        player.save(camp / "world", "Kestrel", role="a rain-soaked courier",
                    description="quick, wary, owes a debt", wants="to clear her name", location="Saltmarrow")
        c = player.card(camp / "world")
        self.assertEqual(c["name"], "Kestrel")
        self.assertEqual(c["role"], "a rain-soaked courier")
        self.assertEqual(c["wants"], "to clear her name")
        self.assertIn("owes a debt", c["description"])
        n = canon.read_node(camp / "world", "Kestrel")
        self.assertEqual(n["frontmatter"].get("player"), True)       # flagged as the PC (parsed to bool)
        self.assertEqual(n["frontmatter"].get("kind"), "character")  # but an ordinary character node

    def test_one_player_per_campaign(self):
        camp = _camp()
        player.save(camp / "world", "Kestrel", role="courier")
        player.save(camp / "world", "Bram", role="smith")           # new PC → old one demoted
        self.assertEqual(player.card(camp / "world")["name"], "Bram")
        prior = canon.read_node(camp / "world", "Kestrel")["frontmatter"]
        self.assertNotIn("player", prior)                            # demoted, flag cleared
        self.assertEqual(prior.get("kind"), "character")             # still a character in the world

    def test_clause_empty_until_set_then_names_the_player(self):
        camp = _camp()
        self.assertEqual(player.clause(camp / "world"), "")          # no PC → no clause
        player.save(camp / "world", "Kestrel", role="a courier", wants="to clear her name")
        cl = player.clause(camp / "world")
        self.assertIn("Kestrel", cl)
        self.assertIn("courier", cl)
        self.assertIn("clear her name", cl)


class PlayerReconcileTest(unittest.TestCase):
    def test_resave_preserves_consolidation_grown_fields(self):
        # red-team: a UI re-save must NOT drop fields the form never carries (disposition/voice grown
        # by consolidation) — the rebuild-from-scratch clobber
        camp = _camp()
        player.save(camp / "world", "Kestrel", role="courier")
        n = canon.read_node(camp / "world", "Kestrel")
        fm = dict(n["frontmatter"]); fm["disposition"] = "haunted"; fm["voice"] = "clipped"
        canon.write_node(camp / "world", "Kestrel", n["body"], fm)          # consolidation grows them
        player.save(camp / "world", "Kestrel", role="a veteran courier", description="quick, wary")
        fm2 = canon.read_node(camp / "world", "Kestrel")["frontmatter"]
        self.assertEqual(fm2.get("disposition"), "haunted")                 # preserved, not clobbered
        self.assertEqual(fm2.get("voice"), "clipped")                       # preserved
        self.assertEqual(fm2.get("role"), "a veteran courier")             # the edited field updated

    def test_resave_logs_field_change_to_provenance(self):
        camp = _camp()
        player.save(camp / "world", "Kestrel", role="courier", location="Saltmarrow")
        player.save(camp / "world", "Kestrel", role="courier", location="The Docks")
        h = provenance.history(camp / "state.json", name="Kestrel", field="location")
        self.assertEqual((h[0]["old"], h[0]["new"]), ("Saltmarrow", "The Docks"))

    def test_first_save_logs_nothing(self):
        camp = _camp()
        player.save(camp / "world", "Kestrel", role="courier", location="Saltmarrow")
        self.assertEqual(provenance.entries(camp / "state.json"), [])       # nothing to reconcile yet


class PlayerInNarrateTest(unittest.TestCase):
    def test_narrator_is_told_who_the_player_is(self):
        camp = _camp()
        canon.write_node(camp / "world", "Room", "a plain room")
        player.save(camp / "world", "Kestrel", role="a rain-soaked courier")
        cfg = dict(config.DEFAULTS)
        cap = {}
        orig = llm.chat
        llm.chat = lambda m, c, **k: (cap.__setitem__("sys", m[0]["content"]), "ok.")[1]
        try:
            narrate.turn("I look around.", cfg, camp / "t.jsonl", camp / "world", camp / "state.json")
        finally:
            llm.chat = orig
        self.assertIn("Kestrel", cap["sys"])                         # the world knows who you are
        self.assertIn("THE PLAYER'S CHARACTER", cap["sys"])


if __name__ == "__main__":
    unittest.main()
