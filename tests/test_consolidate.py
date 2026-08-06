"""Consolidation authors threads: the archivist proposes new dramatic questions and
resolutions from play; apply writes them only with approval, and dedups. Offline."""
import json
import tempfile
import unittest
from pathlib import Path
from loom import consolidate, threads, llm, canon
from loom.threads import Thread

_CFG = {"llm_url": "x", "llm_model": "m", "api_key": "k",
        "max_tokens": 10, "temperature": 0.0, "request_timeout": 1}


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class ProposeTest(unittest.TestCase):
    def test_propose_parses_thread_fields(self):
        payload = json.dumps({"nodes": [], "state": {}, "summary": "s",
                              "threads_new": [{"question": "who lit the beacon?", "entities": ["Beacon"]}],
                              "threads_resolved": ["old-q"]})
        orig = llm.complete
        llm.complete = lambda *a, **k: "sure, here: " + payload
        try:
            out = consolidate.propose(_CFG, [{"role": "player", "text": "hi"}], [Thread("old-q", "q")])
        finally:
            llm.complete = orig
        self.assertEqual(out["threads_new"][0]["question"], "who lit the beacon?")
        self.assertEqual(out["threads_resolved"], ["old-q"])
        self.assertEqual(out["nodes"], [])            # defaults still fill

    def test_propose_parses_character_updates(self):
        payload = json.dumps({"character_updates": [{"name": "Mara", "disposition": "warmer"}]})
        orig = llm.complete
        llm.complete = lambda *a, **k: payload
        try:
            out = consolidate.propose(_CFG, [{"role": "player", "text": "hi"}], [])
        finally:
            llm.complete = orig
        self.assertEqual(out["character_updates"][0]["disposition"], "warmer")
        self.assertEqual(out["nodes"], [])            # missing keys default


class LenientTest(unittest.TestCase):
    def test_repairs_truncated_object(self):
        d = consolidate._loads_lenient('{"nodes": [{"name": "A", "body": "cut off here')
        self.assertEqual(d["nodes"][0]["name"], "A")

    def test_passes_valid_through(self):
        self.assertEqual(consolidate._loads_lenient('{"a": 1}'), {"a": 1})


class ApplyThreadsTest(unittest.TestCase):
    def test_adds_new_thread_on_approval(self):
        camp = _camp()
        prop = {"threads_new": [{"question": "What haunts the mill?", "entities": ["Mill"],
                                 "seed": "a cold draft", "payoff": "a face at the window"}]}
        w = consolidate.apply(prop, camp / "world", camp / "state.json", approve=lambda *a: True)
        th = threads.load(camp / "threads.json")
        self.assertEqual([t.question for t in th], ["What haunts the mill?"])
        self.assertEqual(th[0].status, "dormant")
        self.assertEqual(w["threads"], ["What haunts the mill?"])

    def test_writes_nothing_without_approval(self):
        camp = _camp()
        consolidate.apply({"threads_new": [{"question": "q?"}]}, camp / "world",
                          camp / "state.json", approve=lambda *a: False)
        self.assertEqual(threads.load(camp / "threads.json"), [])

    def test_resolves_existing_thread(self):
        camp = _camp()
        threads.save(camp / "threads.json", [Thread("mill-q", "What haunts the mill?")])
        consolidate.apply({"threads_resolved": ["mill-q"]}, camp / "world",
                          camp / "state.json", approve=lambda *a: True)
        self.assertEqual(threads.load(camp / "threads.json")[0].status, "resolved")

    def test_updates_existing_node_preserving_frontmatter(self):
        camp = _camp()
        canon.write_node(camp / "world", "Mara", "A fisher.", {"kind": "character", "wants": "to leave"})
        consolidate.apply({"nodes": [{"name": "Mara", "body": "She now trusts the stranger.", "kind": "character"}]},
                          camp / "world", camp / "state.json", approve=lambda *a: True)
        node = canon.read_node(camp / "world", "Mara")
        self.assertIn("A fisher.", node["body"])                 # original kept, not clobbered
        self.assertIn("trusts the stranger", node["body"])       # new content appended
        self.assertEqual(node["frontmatter"].get("wants"), "to leave")   # drive preserved

    def test_updates_character_disposition(self):
        camp = _camp()
        canon.write_node(camp / "world", "Mara", "A fisher.", {"kind": "character", "disposition": "cold"})
        consolidate.apply({"character_updates": [{"name": "Mara", "disposition": "warming to the stranger"}]},
                          camp / "world", camp / "state.json", approve=lambda *a: True)
        self.assertEqual(canon.read_node(camp / "world", "Mara")["frontmatter"].get("disposition"),
                         "warming to the stranger")

    def test_updates_character_location(self):
        # NPCs relocate over play so the world-round groups shift — a location-only update applies
        # even when disposition is unchanged, and it preserves the rest of the frontmatter
        camp = _camp()
        canon.write_node(camp / "world", "Rook", "A rogue.",
                         {"kind": "character", "wants": "the ledger", "location": "The Docks"})
        consolidate.apply({"character_updates": [{"name": "Rook", "location": "The Salt & Anchor"}]},
                          camp / "world", camp / "state.json", approve=lambda *a: True)
        fm = canon.read_node(camp / "world", "Rook")["frontmatter"]
        self.assertEqual(fm.get("location"), "The Salt & Anchor")     # moved
        self.assertEqual(fm.get("wants"), "the ledger")               # drive preserved

    def test_location_gate_is_independent_of_disposition(self):
        # a MOVE must be independently refusable — approving a feeling can't smuggle in a relocation
        camp = _camp()
        canon.write_node(camp / "world", "Rook", "A rogue.",
                         {"kind": "character", "disposition": "cold", "location": "The Docks"})
        consolidate.apply({"character_updates": [{"name": "Rook", "disposition": "warmer", "location": "The Tavern"}]},
                          camp / "world", camp / "state.json",
                          approve=lambda kind, name, p: kind == "disposition")   # bless feeling, refuse move
        fm = canon.read_node(camp / "world", "Rook")["frontmatter"]
        self.assertEqual(fm.get("disposition"), "warmer")     # applied
        self.assertEqual(fm.get("location"), "The Docks")     # move refused → stays put

    def test_location_counted_as_a_move_not_a_disposition(self):
        camp = _camp()
        canon.write_node(camp / "world", "Rook", "A rogue.", {"kind": "character", "location": "The Docks"})
        w = consolidate.apply({"character_updates": [{"name": "Rook", "location": "The Tavern"}]},
                              camp / "world", camp / "state.json", approve=lambda *a: True)
        self.assertEqual(w["locations"], ["Rook"])
        self.assertEqual(w["dispositions"], [])               # a relocation is not a feeling

    def test_node_fields_written_and_merged(self):
        camp = _camp()
        consolidate.apply({"nodes": [{"name": "Mara", "body": "A fisher.", "kind": "character",
                                       "fields": {"role": "a fisher", "met": "on the docks"}}]},
                          camp / "world", camp / "state.json", approve=lambda *a: True)
        n = canon.read_node(camp / "world", "Mara")
        self.assertEqual(n["frontmatter"].get("role"), "a fisher")
        self.assertEqual(n["frontmatter"].get("met"), "on the docks")
        consolidate.apply({"nodes": [{"name": "Mara", "body": "", "kind": "character",
                                       "fields": {"met": "again at the tavern"}}]},
                          camp / "world", camp / "state.json", approve=lambda *a: True)
        self.assertEqual(canon.read_node(camp / "world", "Mara")["frontmatter"].get("met"),
                         "again at the tavern")

    def test_skips_duplicate_body(self):
        camp = _camp()
        canon.write_node(camp / "world", "Mara", "A fisher who left.", {"kind": "character"})
        w = consolidate.apply({"nodes": [{"name": "Mara", "body": "who left", "kind": "character"}]},
                              camp / "world", camp / "state.json", approve=lambda *a: True)
        self.assertEqual(w["nodes"], [])                         # already present → no-op

    def test_dedups_by_id(self):
        camp = _camp()
        tid = threads.make_id("What haunts the mill?")
        threads.save(camp / "threads.json", [Thread(tid, "What haunts the mill?")])
        consolidate.apply({"threads_new": [{"question": "What haunts the mill?"}]},
                          camp / "world", camp / "state.json", approve=lambda *a: True)
        self.assertEqual(len(threads.load(camp / "threads.json")), 1)     # not duplicated


if __name__ == "__main__":
    unittest.main()
