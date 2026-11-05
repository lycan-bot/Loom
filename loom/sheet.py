"""loom.sheet — the character objectifier (D&D-mode S1): a character's MECHANICAL state as structured,
diode-gated truth, so the game is coherent instead of the model waving you to a win.

The sheet is the character-side twin of world.py's object layer: abilities, skills (0..cap, earned by use),
HP, conditions, the magic systems they can wield, a peril track, and whether they are alive/downed/dead.
It rides `_sheets` in state.json (keyed by character, like `_rep`), so it survives undo/sleep and never
leaks into the prompt as a raw fact. The diode holds exactly as for canon and the world: the resolver and
the dice WRITE the sheet (on blessed outcomes — a check made, damage taken), the narrator only READS it to
COLOUR how a character acts (mighty, frail, deft) — never numbers in the prose, never a self-granted buff.

It reads off the bible (races → ability mods + size; skills → which ability they key off), so a sheet is
always consistent with the rules. Default-OFF behind `rpg_mode`: with it off the sheet is never loaded or
clause'd, and everything is byte-identical.
"""
from __future__ import annotations
from . import state, provenance, bible
from . import prompt_security as sec

_KEY = "_sheets"
SKILL_CAP = 100
_ABILITY_BASE = 5
_COND_CAP = 12                     # a character carries at most N conditions (bound, like the deed log)
_STATUSES = ("alive", "downed", "dead")

# an ability far from the baseline of 5 shows in the prose, never as a number
_LOW = {"might": "frail", "grace": "clumsy", "wits": "slow-witted", "will": "meek"}
_HIGH = {"might": "powerful", "grace": "deft", "wits": "sharp-eyed", "will": "iron-willed"}


def _norm(name) -> str:
    return " ".join(str(name or "").strip().lower().split())


def _int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def blank(name, race="human", abilities=None) -> dict:
    """A fresh sheet: abilities seeded from the bible race (base 5 ± racial), no skills yet, HP from Might,
    no systems, alive. `abilities` (a dict) overrides per-ability scores — the character-creation hook."""
    r = bible.race(race)
    ab = {}
    for a in bible.ABILITIES:
        base = _ABILITY_BASE + (r.ability_mods.get(a, 0) if r else 0)
        ab[a] = _int((abilities or {}).get(a), base)
    size = r.size if r else "medium"
    hp = 10 + ab["might"] * 2
    return {"name": str(name).strip(), "race": (r.name if r else "human"), "size": size,
            "abilities": ab, "skills": {}, "systems": [], "hp": hp, "hp_max": hp,
            "conditions": [], "peril": 0, "status": "alive"}


def _clean(sheet):
    """A well-formed sheet, or None — fail-soft coercion so a hand-edited state can't crash a read."""
    if not isinstance(sheet, dict) or not str(sheet.get("name", "")).strip():
        return None
    # guard EVERY container by type (not just falsiness) so a hand-edited list/str/number can't crash the read
    ab = sheet.get("abilities") if isinstance(sheet.get("abilities"), dict) else {}
    sk = sheet.get("skills") if isinstance(sheet.get("skills"), dict) else {}
    sy = sheet.get("systems") if isinstance(sheet.get("systems"), list) else []
    co = sheet.get("conditions") if isinstance(sheet.get("conditions"), list) else []
    status = str(sheet.get("status", "alive")).strip().lower()   # normalise so 'DEAD '/'Dead' don't resurrect to alive
    out = {"name": str(sheet["name"]).strip(),
           "race": str(sheet.get("race", "human")).strip() or "human",
           "size": str(sheet.get("size", "medium")).strip() or "medium",
           "abilities": {a: _int(ab.get(a), _ABILITY_BASE) for a in bible.ABILITIES},
           "skills": {_norm(k): _clamp(_int(v, 0), 0, SKILL_CAP) for k, v in sk.items() if _norm(k)},
           "systems": [_norm(s) for s in sy if _norm(s)],
           "hp_max": max(1, _int(sheet.get("hp_max"), 10)),
           "conditions": [str(c).strip() for c in co if str(c).strip()][:_COND_CAP],
           "peril": max(0, _int(sheet.get("peril"), 0)),
           "status": status if status in _STATUSES else "alive"}
    out["hp"] = _clamp(_int(sheet.get("hp"), out["hp_max"]), 0, out["hp_max"])
    return out


def load(state_dict) -> dict:
    """{norm_name: sheet} out of a loaded state dict — well-formed only. Pure read."""
    raw = state_dict.get(_KEY)
    if not isinstance(raw, dict):
        return {}
    return {_norm(c["name"]): c for c in (_clean(s) for s in raw.values()) if c}


def get(sheets, name):
    return (sheets or {}).get(_norm(name))


# --- read helpers the resolver + the clause use (pure) ---

def skill_level(sheet, skill) -> int:
    return _int((sheet or {}).get("skills", {}).get(_norm(skill), 0), 0) if sheet else 0


def ability_score(sheet, ability) -> int:
    return _int((sheet or {}).get("abilities", {}).get(_norm(ability), _ABILITY_BASE), _ABILITY_BASE) \
        if sheet else _ABILITY_BASE


def stat_bonus(sheet, skill) -> int:
    """The flat roll bonus a character's ability lends to a check of `skill` (via the bible's keying)."""
    sk = bible.skill(skill)
    return bible.ability_bonus(ability_score(sheet, sk.ability)) if sk else 0


# --- the diode writes: the resolver / creation / danger write the sheet; the narrator NEVER does ---

def _save(spath, sheets, logs):
    st = state.load(spath)
    st[_KEY] = dict(sheets)
    state.save(spath, st)
    if logs:
        provenance.log(spath, logs)


def _diff(name, old, new) -> list:
    """old→new provenance rows for the fields that changed between two sheets (never a silent overwrite)."""
    rows = []
    for f in ("race", "size", "hp", "hp_max", "peril", "status"):
        if str(old.get(f)) != str(new.get(f)):
            rows.append({"kind": "sheet", "name": name, "field": f,
                         "old": str(old.get(f)), "new": str(new.get(f)), "source": "operator"})
    return rows


def put(spath, sheet) -> dict:
    """Set (or replace) a character's whole sheet — character creation / an operator edit. Logs the scalar
    fields that CHANGED from any prior sheet. Returns the stored sheet (or {} if malformed)."""
    sheet = _clean(sheet)
    if not sheet:
        return {}
    st = state.load(spath)
    sheets = load(st)
    key = _norm(sheet["name"])
    prior = sheets.get(key)
    logs = _diff(sheet["name"], prior, sheet) if prior else []
    sheets[key] = sheet
    _save(spath, sheets, logs)
    return sheet


def _mutate(spath, name, field, read, change):
    """Load the named sheet, read the old value, apply `change`, save + log old→new on `field`. The one
    write chokepoint — every durable sheet change passes through it with provenance."""
    st = state.load(spath)
    sheets = load(st)
    sh = sheets.get(_norm(name))
    if not sh:
        return {}
    old = read(sh)
    change(sh)
    new = read(sh)
    logs = [{"kind": "sheet", "name": sh["name"], "field": field,
             "old": str(old), "new": str(new), "source": "play"}] if str(old) != str(new) else []
    _save(spath, sheets, logs)
    return sh


def bump_skill(spath, name, skill, level) -> dict:
    """Set a skill's level — progression (S4) writes this from blessed use + outcomes, never model improv."""
    sk = _norm(skill)
    return _mutate(spath, name, "skill:" + sk, lambda sh: skill_level(sh, sk),
                   lambda sh: sh["skills"].__setitem__(sk, _clamp(_int(level, 0), 0, SKILL_CAP)))


def adjust_hp(spath, name, delta) -> dict:
    """Change current HP by delta (damage negative, heal positive), clamped 0..max. Danger (S5) writes this."""
    d = _int(delta, 0)
    return _mutate(spath, name, "hp", lambda sh: sh["hp"],
                   lambda sh: sh.__setitem__("hp", _clamp(sh["hp"] + d, 0, sh["hp_max"])))


def set_status(spath, name, status) -> dict:
    """Set alive/downed/dead — the danger + lethality layer (S5) writes this through the blessed path."""
    s = status if status in _STATUSES else "alive"
    return _mutate(spath, name, "status", lambda sh: sh["status"], lambda sh: sh.__setitem__("status", s))


# --- the read-clause: COLOUR the narration with who this character is, in prose, never numbers ---

def clause(sheet) -> str:
    """A narrator-prompt fragment that colours how a character moves and fares — their build shown, never
    stated as numbers. '' for no/empty sheet. Character-centric: it describes the person, not the dice."""
    sh = sheet if (isinstance(sheet, dict) and "abilities" in sheet) else _clean(sheet)
    if not sh:
        return ""
    bits = []
    traits = []
    for a in bible.ABILITIES:
        sc = sh["abilities"].get(a, _ABILITY_BASE)
        if sc <= _ABILITY_BASE - 2:
            traits.append(_LOW[a])
        elif sc >= _ABILITY_BASE + 2:
            traits.append(_HIGH[a])
    if traits:
        bits.append(", ".join(traits))
    skilled = [sec.neutralize(k) for k, v in sorted(sh["skills"].items(), key=lambda kv: -kv[1])[:3] if v >= 30]
    if skilled:
        bits.append("practised at " + ", ".join(skilled))
    if sh["status"] == "dead":
        bits.append("dead")
    elif sh["status"] == "downed":
        bits.append("down and barely conscious")
    elif sh["hp_max"] and sh["hp"] <= sh["hp_max"] // 3:
        bits.append("wounded and failing")
    elif sh["hp_max"] and sh["hp"] <= sh["hp_max"] * 2 // 3:
        bits.append("hurt")
    if not bits:
        return ""
    who = sec.neutralize(" ".join(str(sh["name"]).split()))
    return ("\n\nCHARACTER (let this COLOUR how they move and fare in the scene — show it, never state the "
            "numbers): " + who + " is " + "; ".join(bits) + ".")
