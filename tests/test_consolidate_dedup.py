"""Consolidation dedup: a proposed node name that's a near-miss the archivist invented ('The
Inquisitor' → 'Inquisitor Vael') resolves to the existing node and MERGES; a genuinely new entity
still gets its own node. Conservative — when unsure it creates new, never a wrong merge. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import canon, consolidate


def _world():
    d = Path(tempfile.mkdtemp())
    w = d / "world"
    w.mkdir()
    canon.write_node(w, "Aldermere College", "a college", {"kind": "place"})
    canon.write_node(w, "Inquisitor Vael", "an inquisitor", {"kind": "character"})
    canon.write_node(w, "The Orders", "a militant order", {"kind": "faction"})
    return w


class ResolveTest(unittest.TestCase):
    def test_exact(self):
        self.assertEqual(consolidate._resolve_existing(_world(), "Aldermere College"), "Aldermere College")

    def test_subset_with_distinctive_token(self):
        self.assertEqual(consolidate._resolve_existing(_world(), "The Inquisitor"), "Inquisitor Vael")

    def test_normalized_the_prefix(self):
        self.assertEqual(consolidate._resolve_existing(_world(), "Orders"), "The Orders")

    def test_close_spelling_typo(self):
        self.assertEqual(consolidate._resolve_existing(_world(), "Inquisiter Vael"), "Inquisitor Vael")

    def test_only_a_generic_word_shared_is_new(self):
        # "Arcane College" and "Aldermere College" share only the generic "College" → NOT the same
        self.assertIsNone(consolidate._resolve_existing(_world(), "The Arcane College"))

    def test_a_different_order_is_not_merged(self):
        self.assertIsNone(consolidate._resolve_existing(_world(), "The Silent Circle"))

    def test_genuinely_new_is_new(self):
        self.assertIsNone(consolidate._resolve_existing(_world(), "The Familiar Statutes"))


class ApplyMergeTest(unittest.TestCase):
    def _proposal(self, name, body, kind):
        return {"nodes": [{"name": name, "body": body, "kind": kind, "fields": {}}],
                "state": {}, "threads_new": [], "threads_resolved": [], "character_updates": [], "reputation": []}

    def test_near_miss_merges_into_the_canonical_node(self):
        w = _world(); sp = w.parent / "state.json"
        written = consolidate.apply(self._proposal("The Inquisitor", "He investigated Fáelán.", "event"),
                                    w, sp, approve=lambda *a: True)
        self.assertEqual(written["nodes"], ["Inquisitor Vael"])                 # merged under the real name
        self.assertIsNone(canon.read_node(w, "The Inquisitor"))                 # no duplicate created
        self.assertIn("investigated Fáelán", canon.read_node(w, "Inquisitor Vael")["body"])  # content folded in

    def test_genuinely_new_node_is_still_created(self):
        w = _world(); sp = w.parent / "state.json"
        consolidate.apply(self._proposal("The Familiar Statutes", "ancient laws", "lore"),
                          w, sp, approve=lambda *a: True)
        self.assertIsNotNone(canon.read_node(w, "The Familiar Statutes"))       # new stuff folded properly


if __name__ == "__main__":
    unittest.main()
