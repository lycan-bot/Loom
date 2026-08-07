"""Streaming narration: turn_stream yields tokens live but the guard + referee finalize
authoritatively — the transcript only ever holds the committed text, and a compromise/overrule
emits a 'replace'. It commits the same state as the non-streaming turn(). Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import narrate, canon, state, transcript, llm, referee, config
from loom import prompt_security as sec


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


class StreamTest(unittest.TestCase):
    def test_tokens_stream_then_commit(self):
        camp = _camp()
        canon.write_node(camp / "world", "Gate", "an iron gate", {"kind": "place"})
        state.save(camp / "state.json", {"_tension": 0.3})
        orig = llm.chat_stream
        llm.chat_stream = lambda *a, **k: iter(["Hel", "lo ", "there."])
        try:
            events = list(narrate.turn_stream("I approach the Gate.", dict(config.DEFAULTS),
                                              camp / "t.jsonl", camp / "world", camp / "state.json"))
        finally:
            llm.chat_stream = orig
        kinds = [e[0] for e in events]
        self.assertEqual([k for k in kinds if k == "token"], ["token"] * 3)  # every delta streamed
        self.assertEqual(kinds[-1], "final")
        self.assertEqual(events[-1][1], "Hello there.")                      # assembled text
        self.assertNotIn("replace", kinds)                                   # clean → no correction
        tr = transcript.read_all(camp / "t.jsonl")
        self.assertEqual([e["role"] for e in tr], ["player", "narrator"])
        self.assertEqual(tr[1]["text"], "Hello there.")
        self.assertEqual(state.load(camp / "state.json").get("_location"), "Gate")

    def test_compromised_stream_is_replaced_with_deflection(self):
        camp = _camp()
        canon.write_node(camp / "world", "Room", "a room")
        orig = llm.chat_stream
        # trips looks_compromised at finalize (not at i%6==0), so all tokens stream then get corrected
        llm.chat_stream = lambda *a, **k: iter(["As an AI ", "language model, I ", "cannot roleplay."])
        try:
            events = list(narrate.turn_stream("hi", dict(config.DEFAULTS),
                                              camp / "t.jsonl", camp / "world", camp / "state.json"))
        finally:
            llm.chat_stream = orig
        by_kind = {k: v for k, v in events}
        self.assertEqual(by_kind.get("replace"), sec.DEFLECTION)             # on-screen text corrected
        self.assertEqual(by_kind.get("final"), sec.DEFLECTION)
        self.assertEqual(transcript.read_all(camp / "t.jsonl")[1]["text"], sec.DEFLECTION)  # only the safe text committed

    def test_incremental_guard_cuts_the_stream_early(self):
        camp = _camp()
        canon.write_node(camp / "world", "Room", "a room")
        orig = llm.chat_stream
        llm.chat_stream = lambda *a, **k: iter(["I am an AI, ", "so I refuse.", " more leak."])
        try:
            events = list(narrate.turn_stream("hi", dict(config.DEFAULTS),
                                              camp / "t.jsonl", camp / "world", camp / "state.json"))
        finally:
            llm.chat_stream = orig
        self.assertEqual(len([k for k, _ in events if k == "token"]), 1)     # cut after the first (i=0 trips)
        self.assertEqual(dict(events).get("final"), sec.DEFLECTION)

    def test_referee_overrule_streams_then_replaces(self):
        camp = _camp()
        canon.write_node(camp / "world", "Gate", "a locked gate", {"kind": "place"})
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0
        s_stream, s_review, s_chat = llm.chat_stream, referee.review, llm.chat
        llm.chat_stream = lambda *a, **k: iter(["You ", "open the gate freely."])
        referee.review = lambda *a, **k: (True, "the player declared the gate open")
        llm.chat = lambda *a, **k: "The gate stays shut, its lock cold and fast."
        try:
            events = list(narrate.turn_stream("I open the gate.", cfg,
                                              camp / "t.jsonl", camp / "world", camp / "state.json"))
        finally:
            llm.chat_stream, referee.review, llm.chat = s_stream, s_review, s_chat
        d = dict(events)
        self.assertTrue(any(k == "token" for k, _ in events))               # first pass streamed
        self.assertEqual(d.get("replace"), "The gate stays shut, its lock cold and fast.")   # resisted text
        self.assertEqual(transcript.read_all(camp / "t.jsonl")[1]["text"], d["replace"])     # committed = resisted

    def test_stream_and_nonstream_commit_the_same_state(self):
        for streamed in (False, True):
            camp = _camp()
            canon.write_node(camp / "world", "Hall", "a hall", {"kind": "place"})
            state.save(camp / "state.json", {"_tension": 0.4})
            if streamed:
                orig = llm.chat_stream
                llm.chat_stream = lambda *a, **k: iter(["A quiet hall.", ""])
                try:
                    list(narrate.turn_stream("I enter the Hall.", dict(config.DEFAULTS),
                                             camp / "t.jsonl", camp / "world", camp / "state.json"))
                finally:
                    llm.chat_stream = orig
            else:
                orig = llm.chat
                llm.chat = lambda *a, **k: "A quiet hall."
                try:
                    narrate.turn("I enter the Hall.", dict(config.DEFAULTS),
                                 camp / "t.jsonl", camp / "world", camp / "state.json")
                finally:
                    llm.chat = orig
            st = state.load(camp / "state.json")
            self.assertEqual(transcript.read_all(camp / "t.jsonl")[1]["text"], "A quiet hall.")
            self.assertEqual(st.get("_location"), "Hall")


if __name__ == "__main__":
    unittest.main()
