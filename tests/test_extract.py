"""Per-turn entity extraction + the confabulation signal (storyteller-memory Phase 3). Deterministic,
on-demand from the transcript. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import extract, canon, transcript


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class ExtractTest(unittest.TestCase):
    def test_present_matches_canon_by_name_token(self):
        camp = _camp()
        canon.write_node(camp / "world", "Professor Ysolde Finch", "a prof", {"kind": "character"})
        canon.write_node(camp / "world", "Aldermere College", "a college", {"kind": "place"})
        pres = extract.present("Finch walked the halls of Aldermere College", camp / "world")
        self.assertIn("Professor Ysolde Finch", pres)             # matched on the distinctive token 'finch'
        self.assertIn("Aldermere College", pres)

    def test_candidates_are_midsentence_and_strip_possessive(self):
        c = extract.candidates("Together they walked. The great Ashford Keep loomed over Wren's shoulder.")
        self.assertIn("Ashford Keep", c)                          # mid-sentence proper phrase kept
        self.assertNotIn("Together", c)                           # sentence-start noise dropped
        self.assertTrue(any("Wren" in x for x in c))              # 'Wren's' -> 'Wren' (possessive stripped)

    def test_contraction_collapses_to_stopword(self):
        # a contraction reduces to a pronoun/stopword and must NOT be a candidate
        c = extract.candidates("and You're certain of it, so We'll go now")
        self.assertNotIn("You're", c)
        self.assertNotIn("You", c)
        self.assertNotIn("We'll", c)

    def test_emergent_flags_recurring_noncanon_name(self):
        camp = _camp()
        canon.write_node(camp / "world", "Wren", "a cadet", {"kind": "character"})
        t = camp / "t.jsonl"
        transcript.append(t, "player", "who leads the guild?")
        transcript.append(t, "narrator", "Wren mentions the sly Duke Varro runs the guild now.")
        transcript.append(t, "player", "tell me more")
        transcript.append(t, "narrator", "The influence of Duke Varro spreads through the city.")
        names = [e["name"] for e in extract.emergent(t, camp / "world", min_turns=2)]
        self.assertTrue(any("Varro" in n for n in names))         # recurring non-canon name flagged
        self.assertFalse(any("Wren" in n for n in names))         # canon entity is NOT a miss

    def test_emergent_ignores_a_oneoff(self):
        camp = _camp()
        canon.write_node(camp / "world", "Wren", "a cadet", {"kind": "character"})
        t = camp / "t.jsonl"
        transcript.append(t, "player", "hi")
        transcript.append(t, "narrator", "A stranger named Bob appears once and is gone.")
        self.assertEqual(extract.emergent(t, camp / "world", min_turns=2), [])   # one-off < recurrence threshold


if __name__ == "__main__":
    unittest.main()
