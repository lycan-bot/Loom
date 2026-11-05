"""The rules-substrate bible (D&D-mode S0): reference data + pure lookups. Offline, deterministic."""
import unittest
from loom import bible


class DataIntegrityTest(unittest.TestCase):
    def test_races_reference_valid_abilities_and_sizes(self):
        for r in bible.races():
            for ab in r.ability_mods:
                self.assertIn(ab, bible.ABILITIES, f"{r.name} mods an unknown ability {ab}")
            self.assertIn(r.size, bible._SIZES, f"{r.name} has an unknown size {r.size}")

    def test_skills_key_off_valid_abilities(self):
        for s in bible.skills():
            self.assertIn(s.ability, bible.ABILITIES, f"skill {s.name} keys off unknown ability {s.ability}")

    def test_magic_systems_reference_existing_skills_and_defenses(self):
        for m in bible.magic_systems():
            for sk in tuple(m.casting) + tuple(m.requires):
                self.assertIsNotNone(bible.skill(sk), f"{m.name} references missing skill {sk}")
            for d in m.defenses:
                self.assertIsNotNone(bible.defense(d), f"{m.name} raises a missing defense {d}")
            if m.peril:
                self.assertIsNotNone(bible.skill(m.peril.get("control")),
                                     f"{m.name} peril names a missing control skill")

    def test_every_attack_type_has_a_counter(self):
        # coherence (the psionic_kinetic gap the red-team caught): every attack a system can produce must be
        # blockable by SOME defense — no strictly-unanswerable attack line
        for at in {t for m in bible.magic_systems() for t in m.attack_types}:
            self.assertTrue(any(bible.covers(d.name, at) for d in bible.DEFENSES.values()),
                            f"attack type {at} has no defense that covers it")


class LookupTest(unittest.TestCase):
    def test_lookups_are_case_insensitive_and_unknown_is_none(self):
        self.assertEqual(bible.race("DWARF").name, "dwarf")
        self.assertEqual(bible.skill("  Arcana ").ability, "wits")
        self.assertEqual(bible.magic_system("Psionics").name, "psionics")
        self.assertIsNone(bible.race("tiefling"))
        self.assertIsNone(bible.skill(""))
        self.assertIsNone(bible.defense(None))


class SizeTest(unittest.TestCase):
    def test_size_rank_and_unknown_is_medium(self):
        self.assertEqual(bible.size_rank("tiny"), 1)
        self.assertEqual(bible.size_rank("huge"), 5)
        self.assertEqual(bible.size_rank("colossal"), 3)   # unknown → medium

    def test_rat_cannot_fight_the_dragonborn(self):
        # a tiny rat vs a large dragonborn is a −45 to the rat, +45 to the dragonborn — the gulf lives here
        self.assertEqual(bible.size_mod("tiny", "large"), -45)
        self.assertEqual(bible.size_mod("large", "tiny"), 45)
        self.assertEqual(bible.size_mod("medium", "medium"), 0)


class AbilityTest(unittest.TestCase):
    def test_ability_bonus_centered_on_five(self):
        self.assertEqual(bible.ability_bonus(5), 0)        # baseline
        self.assertEqual(bible.ability_bonus(6), 3)        # a dragonborn's Might
        self.assertEqual(bible.ability_bonus(4), -3)       # an elf's Might
        self.assertEqual(bible.ability_bonus("oops"), 0)          # fail-soft on junk…
        self.assertEqual(bible.ability_bonus(float("inf")), 0)    # …and on overflow, not a crash


class DomainCoverageTest(unittest.TestCase):
    def test_the_shield_does_not_save_the_nerd(self):
        # THE headline rule: a defense only blocks what its DOMAIN covers
        self.assertTrue(bible.covers("arcane_barrier", "arcane_bolt"))          # it stops a bolt…
        self.assertTrue(bible.covers("arcane_barrier", "physical_melee"))       # …and steel in reach…
        self.assertTrue(bible.covers("arcane_barrier", "physical_projectile"))  # …and a thrown thing…
        self.assertFalse(bible.covers("arcane_barrier", "psionic_mental"))      # …but NOT a mind-attack
        self.assertTrue(bible.covers("mental_ward", "psionic_mental"))          # only a mental ward stops that…
        self.assertTrue(bible.covers("mental_ward", "psionic_kinetic"))         # …and it contests BOTH psionic lines
        self.assertFalse(bible.covers("mental_ward", "arcane_bolt"))            # but it doesn't stop a bolt

    def test_unknown_defense_covers_nothing(self):
        self.assertFalse(bible.covers("nonexistent", "arcane_bolt"))


class PerilTest(unittest.TestCase):
    def test_sorcery_is_safe_psionics_is_not(self):
        self.assertEqual(bible.peril_of("sorcery"), {})
        self.assertFalse(bible.has_peril("sorcery"))
        pp = bible.peril_of("psionics")
        self.assertTrue(bible.has_peril("psionics"))
        self.assertEqual(pp["control"], "control")                 # held in check by the Control skill
        self.assertIn("severity", pp)

    def test_psionics_demands_several_leveled_skills(self):
        # the balance on "I cast forever sleep, nerd": you can't wield it safely on one skill
        self.assertGreaterEqual(len(bible.magic_system("psionics").requires), 3)


class MutationSafetyTest(unittest.TestCase):
    def test_reference_data_cannot_be_mutated_by_a_consumer(self):
        # the read-only-rules guarantee: a consumer can't corrupt the shipped bible by reference
        with self.assertRaises(TypeError):
            bible.race("dwarf").ability_mods["might"] = 99
        with self.assertRaises(TypeError):
            bible.magic_system("sorcery").peril["severity"] = "catastrophic"
        self.assertEqual(bible.race("dwarf").ability_mods.get("might"), 1)   # a fresh lookup is unchanged
        self.assertEqual(bible.peril_of("sorcery"), {})


if __name__ == "__main__":
    unittest.main()
