"""Node compaction (storyteller-memory Phase 7): distill a bloated canon node, fail-closed (never drop
a [[link]], must actually shrink). Offline — the model call is stubbed."""
import tempfile
import unittest
from pathlib import Path
from loom import compact, guard, canon, llm


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class CompactTest(unittest.TestCase):
    def test_oversized_detects_big_nodes(self):
        camp = _camp()
        canon.write_node(camp / "world", "Big", "x" * 2500, {"kind": "character"})
        canon.write_node(camp / "world", "Small", "tiny", {"kind": "character"})
        self.assertEqual([n["name"] for n in compact.oversized(camp / "world")], ["Big"])

    def test_verify_refuses_dropped_link(self):
        orig = "A long body mentioning [[Wren]] and [[The College]]. " + "filler " * 300
        ok, reason = compact.verify(orig, "A shorter but still adequately long body mentioning only [[Wren]] here.")
        self.assertFalse(ok)
        self.assertIn("The College", reason)                     # names the link it would have dropped

    def test_verify_refuses_no_shrink(self):
        orig = "[[Wren]] " + "filler " * 300
        ok, reason = compact.verify(orig, orig + " and then some more text appended on the end")
        self.assertFalse(ok)
        self.assertIn("shrink", reason)

    def test_verify_accepts_good_distillation(self):
        orig = "[[Wren]] and [[The College]]. " + "repetitive filler " * 300
        ok, reason = compact.verify(orig, "[[Wren]] studies wards at [[The College]] — a sharp, warm cadet.")
        self.assertTrue(ok, reason)

    def test_verify_refuses_dropped_prose_fact(self):
        # red-team HIGH: a fact in unlinked PROSE ('Varro betrayed them') must not vanish silently
        orig = "[[Wren]] fought bravely. Varro betrayed them at the ford. " + "filler " * 300
        ok, reason = compact.verify(orig, "[[Wren]] fought bravely — a distilled body long enough to pass the length check truly.")
        self.assertFalse(ok)
        self.assertIn("varro", reason.lower())

    def test_verify_refuses_invented_entity(self):
        # red-team HIGH: the model must not INVENT a named entity absent from the original
        orig = "[[Wren]] studied the wards. " + "filler " * 300
        ok, reason = compact.verify(orig, "[[Wren]] studied the wards under Grimwald, a distilled body long enough to pass length checks.")
        self.assertFalse(ok)
        self.assertIn("grimwald", reason.lower())

    def test_verify_allows_lowercase_rephrase_of_a_name(self):
        # a legit distillation may rephrase; a name appearing lowercased is still preserved (no false refusal)
        orig = "[[Wren]] and Varro met at the Ford. " + "repetitive filler " * 300
        ok, reason = compact.verify(orig, "[[Wren]] and varro met at the ford — sharp, tense, and brief indeed.")
        self.assertTrue(ok, reason)

    def test_apply_replaces_body_keeps_frontmatter(self):
        camp = _camp()
        canon.write_node(camp / "world", "Wren", "old [[The College]] body " + "x" * 2000,
                         {"kind": "character", "disposition": "warm"})
        compact.apply(camp / "world", "Wren", "tight [[The College]] body")
        n = canon.read_node(camp / "world", "Wren")
        self.assertEqual(n["body"].strip(), "tight [[The College]] body")
        self.assertEqual(n["frontmatter"].get("disposition"), "warm")   # frontmatter preserved

    def test_propose_calls_the_model(self):
        node = {"name": "X", "frontmatter": {"kind": "character"}, "body": "a long body"}
        orig = llm.complete
        llm.complete = lambda *a, **k: "distilled body"
        try:
            out = compact.propose(node, {"llm_url": "u", "llm_model": "m", "api_key": ""})
        finally:
            llm.complete = orig
        self.assertEqual(out, "distilled body")

    def test_guard_flags_bloated_node(self):
        camp = _camp()
        canon.write_node(camp / "world", "Huge", "y" * 2500, {"kind": "character"})
        self.assertTrue(any(f.kind == "bloated-node" for f in guard.check(camp / "world", camp / "threads.json")))


if __name__ == "__main__":
    unittest.main()
