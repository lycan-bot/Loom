"""The character sheet objectifier (D&D-mode S1): per-character mechanical state, diode-gated. Offline."""
import tempfile
import unittest
from pathlib import Path
from loom import sheet, state, provenance, narrate, config, player, canon, transcript, llm


def _sp():
    return Path(tempfile.mkdtemp()) / "state.json"


class BlankTest(unittest.TestCase):
    def test_blank_seeds_from_the_bible_race(self):
        d = sheet.blank("Thora", "dwarf")
        self.assertEqual(d["abilities"]["might"], 6)    # 5 + dwarf's +1
        self.assertEqual(d["abilities"]["grace"], 4)    # 5 − dwarf's −1
        self.assertEqual(d["size"], "medium")
        self.assertEqual(d["hp"], 10 + 6 * 2)           # HP from Might
        self.assertEqual((d["status"], d["skills"]), ("alive", {}))

    def test_blank_honours_overrides_and_unknown_race(self):
        d = sheet.blank("Kel", "tiefling", abilities={"wits": 9})   # unknown race → human baseline
        self.assertEqual(d["race"], "human")
        self.assertEqual(d["abilities"]["wits"], 9)


class StoreTest(unittest.TestCase):
    def test_put_get_roundtrip(self):
        sp = _sp()
        sheet.put(sp, sheet.blank("Wren", "elf"))
        w = sheet.get(sheet.load(state.load(sp)), "WREN")   # norm-keyed
        self.assertEqual((w["race"], w["abilities"]["grace"]), ("elf", 6))

    def test_malformed_sheets_dropped_not_crashing(self):
        sp = _sp()
        state.save(sp, {"_sheets": {"x": {"no": "name"}, "y": sheet.blank("Ok", "human")}})
        self.assertEqual(list(sheet.load(state.load(sp))), ["ok"])

    def test_reads_fail_soft_on_missing(self):
        self.assertEqual(sheet.skill_level(None, "melee"), 0)
        self.assertEqual(sheet.ability_score(None, "might"), 5)
        self.assertEqual(sheet.stat_bonus(None, "melee"), 0)

    def test_clean_fail_soft_on_wrong_container_types(self):
        # red-team fix: a hand-edited state with wrong-typed containers must NOT crash the read (fail-soft)
        c = sheet._clean({"name": "Corrupt", "skills": [10, 20], "systems": 5,
                          "conditions": "poisoned", "abilities": "nope", "status": "DEAD "})
        self.assertEqual((c["skills"], c["systems"], c["conditions"]), ({}, [], []))
        self.assertEqual(c["abilities"]["might"], 5)   # bad abilities → baseline
        self.assertEqual(c["status"], "dead")          # 'DEAD ' normalised, not silently resurrected to alive

    def test_load_survives_a_corrupt_sheet(self):
        sp = _sp()
        state.save(sp, {"_sheets": {"bad": {"name": "X", "skills": [1, 2]}, "ok": sheet.blank("Ok", "human")}})
        self.assertEqual(sorted(sheet.load(state.load(sp))), ["ok", "x"])   # both survive, load doesn't crash


class StatBonusTest(unittest.TestCase):
    def test_stat_bonus_reads_the_bibles_keying(self):
        d = sheet.blank("Gorm", "dragonborn")           # Might 6
        self.assertEqual(sheet.stat_bonus(d, "melee"), 3)     # melee keys off Might → ability_bonus(6)=+3
        self.assertEqual(sheet.stat_bonus(d, "arcana"), 0)    # arcana keys off Wits 5 → +0
        self.assertEqual(sheet.stat_bonus(d, "not-a-skill"), 0)


class WriteTest(unittest.TestCase):
    def test_bump_skill_clamps_and_logs(self):
        sp = _sp(); sheet.put(sp, sheet.blank("Wren", "human"))
        sheet.bump_skill(sp, "Wren", "Melee", 31)
        self.assertEqual(sheet.skill_level(sheet.get(sheet.load(state.load(sp)), "Wren"), "melee"), 31)
        sheet.bump_skill(sp, "Wren", "melee", 500)      # over the cap
        self.assertEqual(sheet.skill_level(sheet.get(sheet.load(state.load(sp)), "Wren"), "melee"), sheet.SKILL_CAP)
        self.assertTrue(any(r["field"] == "skill:melee" for r in provenance.entries(sp)))

    def test_adjust_hp_clamps_and_status(self):
        sp = _sp(); sheet.put(sp, sheet.blank("Wren", "human"))   # hp 20
        sheet.adjust_hp(sp, "Wren", -100)
        self.assertEqual(sheet.get(sheet.load(state.load(sp)), "Wren")["hp"], 0)       # clamped at 0
        sheet.adjust_hp(sp, "Wren", 999)
        g = sheet.get(sheet.load(state.load(sp)), "Wren")
        self.assertEqual(g["hp"], g["hp_max"])                                          # clamped at max
        sheet.set_status(sp, "Wren", "downed")
        self.assertEqual(sheet.get(sheet.load(state.load(sp)), "Wren")["status"], "downed")

    def test_write_to_missing_sheet_is_a_noop(self):
        self.assertEqual(sheet.bump_skill(_sp(), "Nobody", "melee", 5), {})


class ClauseTest(unittest.TestCase):
    def test_colours_in_prose_never_numbers(self):
        d = sheet.blank("Gorm", "dragonborn")
        d["abilities"]["might"] = 8                     # powerful
        d["abilities"]["grace"] = 3                     # clumsy
        d["skills"] = {"melee": 40}
        c = sheet.clause(d)
        self.assertIn("Gorm is", c)
        self.assertIn("powerful", c); self.assertIn("clumsy", c)
        self.assertIn("practised at melee", c)
        self.assertNotIn("8", c); self.assertNotIn("40", c)   # the build shows, the numbers never do

    def test_wounded_and_downed_show(self):
        d = sheet.blank("Wren", "human"); d["hp"] = 5   # ≤ 1/3 of 20
        self.assertIn("wounded and failing", sheet.clause(d))
        d["status"] = "downed"
        self.assertIn("down and barely conscious", sheet.clause(d))

    def test_baseline_sheet_and_none_are_silent(self):
        self.assertEqual(sheet.clause(sheet.blank("Plain", "human")), "")   # all-baseline, no skills → nothing
        self.assertEqual(sheet.clause(None), "")


class NarrateGateTest(unittest.TestCase):
    def test_off_is_byte_identical(self):
        camp = Path(tempfile.mkdtemp()); (camp / "world").mkdir()
        player.save(camp / "world", "Wren", role="a cadet")
        sheet.put(camp / "state.json", sheet.blank("Wren", "dragonborn"))
        cfg = dict(config.DEFAULTS)                      # rpg_mode defaults False
        self.assertEqual(narrate._sheet_clause(camp / "world", camp / "state.json", cfg), "")

    def test_on_colours_the_pc(self):
        camp = Path(tempfile.mkdtemp()); (camp / "world").mkdir()
        player.save(camp / "world", "Gorm", role="a warrior")
        d = sheet.blank("Gorm", "dragonborn"); d["abilities"]["might"] = 8
        sheet.put(camp / "state.json", d)
        cfg = dict(config.DEFAULTS); cfg["rpg_mode"] = True
        c = narrate._sheet_clause(camp / "world", camp / "state.json", cfg)
        self.assertIn("Gorm is", c); self.assertIn("powerful", c)

    def test_resume_carries_the_sheet_colour(self):
        # the resume-trap fix: a ⤵Continue (resume) must ALSO carry the PC's mechanical colour (both paths)
        camp = Path(tempfile.mkdtemp()); (camp / "world").mkdir()
        canon.write_node(camp / "world", "Room", "a room")
        player.save(camp / "world", "Gorm", role="a warrior")
        d = sheet.blank("Gorm", "dragonborn"); d["abilities"]["might"] = 8; d["hp"] = 3
        sheet.put(camp / "state.json", d)
        transcript.append(camp / "t.jsonl", "player", "I fight on.")
        transcript.append(camp / "t.jsonl", "narrator", "You raise your blade")   # truncated → resume continues
        cfg = dict(config.DEFAULTS); cfg["rpg_mode"] = True
        cap = {}
        orig = llm.chat
        llm.chat = lambda m, c, **k: (cap.__setitem__("sys", m[0]["content"]), "and press the attack.")[1]
        try:
            narrate.resume(cfg, camp / "t.jsonl", camp / "world", camp / "state.json")
        finally:
            llm.chat = orig
        self.assertIn("Gorm is", cap["sys"])                 # the sheet colour reached the ⤵Continue prompt
        self.assertIn("wounded and failing", cap["sys"])     # hp 3 → failing, carried onto resume


if __name__ == "__main__":
    unittest.main()
