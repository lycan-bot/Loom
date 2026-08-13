"""Episodic recall (storyteller-memory Phase 2): the narrator can search the story's OWN transcript
and quote a past turn verbatim when the player asks about it. On-demand from the transcript (undo-safe),
lexical BM25. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import recall, narrate, transcript, canon, state, llm, config


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


def _story(camp):
    t = camp / "t.jsonl"
    transcript.append(t, "player", "I ask the innkeeper about the north road")
    transcript.append(t, "narrator", "The innkeeper leans in: 'The north road is cursed past the mill. Turn back at the broken oak.'")
    transcript.append(t, "player", "I nod and drink my ale")
    transcript.append(t, "narrator", "The ale is warm and bitter; the fire pops.")
    return t


class RecallTest(unittest.TestCase):
    def test_pairs_join_player_to_the_reply(self):
        camp = _camp(); t = _story(camp)
        prs = recall.pairs(t)
        self.assertEqual([p["turn"] for p in prs], [1, 2])          # numbered, one per player→narrator pair
        self.assertIn("innkeeper", prs[0]["player"])
        self.assertIn("cursed", prs[0]["narrator"])

    def test_in_progress_turn_excluded(self):
        camp = _camp(); t = _story(camp)
        transcript.append(t, "player", "I stand up")                # no narrator reply yet
        self.assertEqual(len(recall.pairs(t)), 2)                   # the unpaired current turn is not indexed

    def test_search_finds_the_right_turn(self):
        camp = _camp(); t = _story(camp)
        hits = recall.search(t, "what did the innkeeper say about the north road", k=1)
        self.assertEqual(len(hits), 1)
        self.assertIn("cursed", hits[0]["narrator"])

    def test_search_empty_on_no_match(self):
        camp = _camp(); t = _story(camp)
        self.assertEqual(recall.search(t, "zzzznomatch dragons spaceships", k=2), [])

    def test_references_past_prefilter(self):
        for yes in ("what did she say earlier?", "do you remember when we met?",
                    "what exactly did the innkeeper tell me", "remember when we swore the oath"):
            self.assertTrue(recall.references_past(yes), yes)
        for no in ("I draw my sword and charge", "I look around the room", "we go north"):
            self.assertFalse(recall.references_past(no), no)

    def test_forward_filler_does_not_false_fire(self):
        # the red-team bug: common forward-play phrases must NOT trigger recall (they'd inject an
        # irrelevant old turn as 'quote faithfully')
        for no in ("I said a prayer and step outside", "I recall a knife in my belt",
                   "I read the words carved on the door", "she mentioned to me she was leaving"):
            self.assertFalse(recall.references_past(no), no)

    def test_recall_query_strips_the_cue(self):
        # the cue phrase is a trigger, not part of the search — leaving it in pollutes BM25 ranking
        q = recall.recall_query("what exactly did the innkeeper say about the north road?")
        self.assertIsNotNone(q)
        self.assertNotIn("what exactly did", q)
        self.assertIn("innkeeper", q)
        self.assertIsNone(recall.recall_query("I ride north out of town"))


class NarrateIntegrationTest(unittest.TestCase):
    def test_recall_injected_when_player_references_past(self):
        camp = _camp(); t = _story(camp)
        canon.write_node(camp / "world", "Room", "a room")
        cap = {}
        orig = llm.chat
        llm.chat = lambda m, c, **k: (cap.__setitem__("sys", m[0]["content"]), "ok.")[1]
        try:
            narrate.turn("what exactly did the innkeeper say about the north road?",
                         dict(config.DEFAULTS), t, camp / "world", camp / "state.json")
        finally:
            llm.chat = orig
        self.assertIn("FROM THE RECORD", cap["sys"])                # recall clause injected
        self.assertIn("cursed", cap["sys"])                        # the ACTUAL past line, verbatim

    def test_no_recall_on_ordinary_action(self):
        camp = _camp(); t = _story(camp)
        canon.write_node(camp / "world", "Room", "a room")
        cap = {}
        orig = llm.chat
        llm.chat = lambda m, c, **k: (cap.__setitem__("sys", m[0]["content"]), "ok.")[1]
        try:
            narrate.turn("I draw my blade and step toward the door",
                         dict(config.DEFAULTS), t, camp / "world", camp / "state.json")
        finally:
            llm.chat = orig
        self.assertNotIn("FROM THE RECORD", cap["sys"])            # no back-reference → no recall cost

    def test_turn_counter_increments(self):
        camp = _camp()
        canon.write_node(camp / "world", "Room", "a room")
        orig = llm.chat
        llm.chat = lambda *a, **k: "ok."
        try:
            narrate.turn("hi", dict(config.DEFAULTS), camp / "t.jsonl", camp / "world", camp / "state.json")
            narrate.turn("ho", dict(config.DEFAULTS), camp / "t.jsonl", camp / "world", camp / "state.json")
        finally:
            llm.chat = orig
        self.assertEqual(state.load(camp / "state.json").get("_turn"), 2)


if __name__ == "__main__":
    unittest.main()
