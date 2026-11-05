"""loom.bible — the system/rules substrate (the D&D-mode reference tier).

Distinct from a campaign's CANON (what is true in THIS world) and from `setting` (its narrative register):
the bible is the GAME's rules — the abilities, races, skills, sizes, and magic systems the mechanical spine
reads from. It is reference DATA + pure lookups, authored (shipped here as a starter; operator-overridable
later), NEVER written from model output — a read-only rules layer, not a diode surface. The sheet (per-
character state, S1) and the resolver (the dice, S3) build ON this; the bible itself consumes nothing and
changes no behaviour, so it is inert until they read it.

The one mechanical idea that earns the whole tier: a defense only blocks what its DOMAIN covers. An arcane
barrier stops arcane bolts and thrown things; it does nothing against a psionic mind-attack — so
`covers("arcane_barrier", "psionic_mental")` is False, and the shield does not save the nerd.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from types import MappingProxyType

# the four core abilities — broad aptitudes a character is built on (base ~5 at creation; skills key off them)
ABILITIES = ("might", "grace", "wits", "will")

# size ranks, tiny→huge; a PHYSICAL clash between mismatched sizes is a big modifier (the rat vs the dragon)
_SIZES = ("tiny", "small", "medium", "large", "huge")
_SIZE_STEP = 15                 # roll modifier per rank of size difference in a physical clash
_ABILITY_BASE = 5               # the baseline ability score (a creation ability sits near here)
_ABILITY_STEP = 3               # roll modifier per ability point above/below the baseline


@dataclass(frozen=True)
class Race:
    name: str
    ability_mods: dict = field(default_factory=dict)   # ability → ±score at creation
    size: str = "medium"
    traits: tuple = ()

    def __post_init__(self):   # freeze the dict so a consumer can't corrupt the shipped rules by reference
        object.__setattr__(self, "ability_mods", MappingProxyType(dict(self.ability_mods)))


@dataclass(frozen=True)
class Skill:
    name: str
    ability: str                 # which ability its rolls take a bonus from
    blurb: str = ""


@dataclass(frozen=True)
class MagicSystem:
    name: str
    casting: tuple               # the skills/abilities it draws on
    attack_types: tuple          # the attack types it can produce
    defenses: tuple = ()         # the defenses it can raise (names into DEFENSES)
    requires: tuple = ()         # skills that must be leveled to wield it safely
    peril: dict = field(default_factory=dict)   # {} = conventional/safe; else a backlash profile

    def __post_init__(self):   # freeze the dict so a consumer can't disarm a system's peril by reference
        object.__setattr__(self, "peril", MappingProxyType(dict(self.peril)))


@dataclass(frozen=True)
class Defense:
    name: str
    domain: tuple                # the attack_types it BLOCKS — anything outside this walks straight through
    blurb: str = ""


# --- the starter rules (a real seed, not a stub: enough to prove the sorcerer-vs-psion dynamic) ---

RACES = {r.name: r for r in (
    Race("human", {}, "medium", ("versatile",)),
    Race("dwarf", {"might": 1, "grace": -1}, "medium", ("stoneblood",)),
    Race("elf", {"grace": 1, "wits": 1, "might": -1}, "medium", ("keen-senses",)),
    Race("dragonborn", {"might": 1, "will": 1}, "large", ("scaled", "breath")),
    Race("goblin", {"grace": 1, "might": -1}, "small", ("skittish",)),
)}

SKILLS = {s.name: s for s in (
    Skill("melee", "might", "striking in reach"),
    Skill("ranged", "grace", "bows, slings, thrown things"),
    Skill("athletics", "might", "climbing, leaping, forcing"),
    Skill("stealth", "grace", "moving unseen"),
    Skill("perception", "wits", "noticing what is there"),
    Skill("arcana", "wits", "the structured magic of sorcery"),
    Skill("psionics", "wits", "shaping reality by thought"),
    Skill("control", "will", "holding a power in check — the guard against peril"),
    Skill("resolve", "will", "enduring fear, pain, domination"),
    Skill("persuasion", "will", "bending others by word"),
    Skill("lore", "wits", "knowing the world"),
    Skill("survival", "wits", "living off the land, tracking"),
)}

DEFENSES = {d.name: d for d in (
    Defense("arcane_barrier", ("arcane_bolt", "conjured_force", "physical_melee", "physical_projectile"),
            "a wall of structured force — stops force and steel, but never a thought"),
    Defense("physical_armor", ("physical_melee", "physical_projectile"), "worn protection"),
    Defense("mental_ward", ("psionic_mental", "psionic_kinetic"),
            "a disciplined will that contests the psion's focus — the one thing that turns any psionic effect aside"),
)}

MAGIC_SYSTEMS = {m.name: m for m in (
    MagicSystem("sorcery",
                casting=("arcana",),
                attack_types=("arcane_bolt", "conjured_force"),
                defenses=("arcane_barrier",),
                requires=("arcana",),
                peril={}),                         # conventional — no backlash
    MagicSystem("psionics",
                casting=("psionics", "perception"),
                attack_types=("psionic_mental", "psionic_kinetic"),
                defenses=("mental_ward",),
                requires=("psionics", "perception", "control"),   # three leveled skills to wield it safely
                peril={"control": "control", "severity": "catastrophic",
                       "blurb": "overreach turns the power inward — nosebleed, seizure, then the mind gutters out"}),
)}


# --- pure lookups the sheet + the resolver read (case-insensitive; unknown → None/neutral) ---

def _k(name) -> str:
    return str(name or "").strip().lower()


def race(name):
    return RACES.get(_k(name))


def races() -> list:
    return list(RACES.values())


def skill(name):
    return SKILLS.get(_k(name))


def skills() -> list:
    return list(SKILLS.values())


def size_rank(size) -> int:
    """1 (tiny) … 5 (huge); an unknown/absent size reads as medium (3)."""
    try:
        return _SIZES.index(_k(size)) + 1
    except ValueError:
        return 3


def size_mod(attacker_size, defender_size) -> int:
    """The PHYSICAL-clash roll modifier from a size mismatch — big, and in the big one's favour. A tiny rat
    vs a large dragonborn is (1-4)*15 = -45 to the rat, crushing its fair-ish base chance to nearly nothing;
    the dragonborn gets the +45. Engine-derived (read off the bible), never the model's to grant itself."""
    return (size_rank(attacker_size) - size_rank(defender_size)) * _SIZE_STEP


def ability_bonus(score) -> int:
    """The flat roll bonus an ability lends to its keyed skills — (score - 5) * 3, so the baseline 5 is +0.
    A dragonborn's Might 6 adds +3 to a melee roll; an elf's Might 4 subtracts 3."""
    try:
        return (int(score) - _ABILITY_BASE) * _ABILITY_STEP
    except (TypeError, ValueError, ArithmeticError):   # ArithmeticError covers int(inf)'s OverflowError
        return 0


def magic_system(name):
    return MAGIC_SYSTEMS.get(_k(name))


def magic_systems() -> list:
    return list(MAGIC_SYSTEMS.values())


def defense(name):
    return DEFENSES.get(_k(name))


def covers(defense_name, attack_type) -> bool:
    """Does this defense BLOCK this attack type? A defense modifies a clash ONLY when it covers the incoming
    type; anything outside its domain walks straight through (the barrier vs the mind-attack). An unknown
    defense covers nothing — an attack is never free-blocked by something that isn't actually there."""
    d = defense(defense_name)
    return bool(d and _k(attack_type) in d.domain)


def peril_of(system_name) -> dict:
    """The backlash profile of a magic system — {} for a conventional/safe system, else the peril it carries
    (the control skill that holds it in check, and how bad an overreach gets). The resolver rolls against this."""
    m = magic_system(system_name)
    return dict(m.peril) if m and m.peril else {}


def has_peril(system_name) -> bool:
    return bool(peril_of(system_name))
