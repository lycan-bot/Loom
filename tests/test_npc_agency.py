"""NPC-agency integration (P4): the world round becomes tier-aware and goal-continuous — a walk-on
doesn't take a turn, a character with the personhood budget gets its agenda (goal + blessed memory)
injected, and a high-rung focal character DELIBERATES before acting. Offline (model stubbed)."""
import tempfile
import unittest
from pathlib import Path
from loom import worldturn, canon, episodic, config, llm


def _camp():
    d = Path(tempfile.mkdtemp())
    (d / "world").mkdir()
    return d


def _world(camp):
    w = camp / "world"
    canon.write_node(w, "Library", "a vast warded library", {"kind": "place"})
    canon.write_node(w, "Wren", "a sharp cadet", {"kind": "character", "importance": "main",
                                                  "wants": "to escape the college", "bound": "a vow to her mentor",
                                                  "location": "Library"})
    canon.write_node(w, "Extra", "a nameless porter", {"kind": "character", "importance": "passing",
                                                       "wants": "to loiter", "location": "Library"})
    return w


class AgencyIntegrationTest(unittest.TestCase):
    def _run(self, camp, cfg):
        tp, sp = camp / "transcript.jsonl", camp / "state.json"
        calls = []
        orig = llm.complete

        def fake(prompt, c, **kw):
            calls.append(prompt)
            if kw.get("response_format"):                     # the batched beat call
                return '{"turns":[{"where":"Library","who":["Wren"],"beat":"Wren pockets a warded page."}]}'
            return "I will slip into the archive tonight and copy the ward."   # the deliberation call

        llm.complete = fake
        try:
            out = worldturn.run(cfg, camp / "world", tpath=tp, spath=sp)
        finally:
            llm.complete = orig
        return out, calls

    def test_walkon_is_not_cast_but_main_is(self):
        camp = _camp(); _world(camp)
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0
        _out, calls = self._run(camp, cfg)
        beat_prompt = next(p for p in calls if "THIS ROUND" in p)
        actors = beat_prompt.split("THIS ROUND")[1].split("CANON")[0]   # the cast block, not canon grounding
        self.assertIn("Wren", actors)                         # a main character acts…
        self.assertNotIn("Extra", actors)                     # …a passing walk-on (rung 0) does not

    def test_agenda_injected_into_the_round(self):
        camp = _camp(); _world(camp)
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0
        _out, calls = self._run(camp, cfg)
        beat_prompt = next(p for p in calls if "THIS ROUND" in p)
        self.assertIn("Wren wants to escape the college", beat_prompt)     # the goal, not just a name
        self.assertIn("vow to her mentor", beat_prompt)                    # what holds them back

    def test_focal_character_deliberates(self):
        camp = _camp(); _world(camp)
        sp = camp / "state.json"
        episodic.record(sp, [{"what": "Wren copied a warded page", "who": "Wren"}], entry_start=1, source="play")
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0
        _out, calls = self._run(camp, cfg)
        delib = [p for p in calls if "state your INTENT" in p]
        self.assertEqual(len(delib), 1)                       # exactly one think-pass for the focal main
        self.assertIn("You are Wren", delib[0])
        self.assertIn("to escape the college", delib[0])
        self.assertIn("copied a warded page", delib[0])       # deliberates from its BLESSED memory
        beat_prompt = next(p for p in calls if "THIS ROUND" in p)
        self.assertIn("intent this round", beat_prompt)       # the intent is fed into the beat

    def test_no_deliberation_at_low_depth(self):
        # at depth 0.5 Wren is main → rung 0.5: has an agenda, but below the deliberation threshold (0.75)
        camp = _camp(); _world(camp)
        cfg = dict(config.DEFAULTS); cfg["depth"] = 0.5
        _out, calls = self._run(camp, cfg)
        self.assertEqual([p for p in calls if "state your INTENT" in p], [])   # no extra think-call
        beat_prompt = next(p for p in calls if "THIS ROUND" in p)
        self.assertIn("Wren wants to escape", beat_prompt)    # still agenda-injected (rung 0.5 >= 0.5)

    def test_legacy_path_has_no_agency_layer(self):
        # run() without paths (the legacy/test entrypoint) keeps the old flat behavior — no agenda, no deliberation
        camp = _camp(); _world(camp)
        cfg = dict(config.DEFAULTS); cfg["depth"] = 1.0
        calls = []
        orig = llm.complete
        llm.complete = lambda prompt, c, **kw: (calls.append(prompt),
                                                '{"turns":[]}' if kw.get("response_format") else "x")[1]
        try:
            worldturn.run(cfg, camp / "world")                # no tpath/spath
        finally:
            llm.complete = orig
        self.assertEqual([p for p in calls if "state your INTENT" in p], [])   # no deliberation
        beat_prompt = next(p for p in calls if "THIS ROUND" in p)
        self.assertNotIn("Their pursuit is", beat_prompt)     # the agenda layer is the agency marker, absent here


if __name__ == "__main__":
    unittest.main()
