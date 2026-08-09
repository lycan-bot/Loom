"""loom.player — the player's OWN character: who they are in the world (player-as-canon).

The player authors their character card — name, role, who they are, what they want, where they
start — and the narrator then KNOWS them: it addresses them as that person and lets the world react
to who they are, instead of a faceless "you". Stored as an ordinary character node flagged
`player: true` (one per campaign), so it lives in canon like everyone else — the world round and
consolidation see it too.

Character creation is legitimate player authorship (you shape who you are up front), so this is
trusted setup, not the mid-play rewrite the referee guards; the free-text fields are still
defanged before they enter the prompt.
"""
from __future__ import annotations
from . import canon
from . import prompt_security as sec

_TRUE = ("true", "1", "yes")


def is_player(node) -> bool:
    """True if this canon node is the player's OWN character. Excluded from the NPC machinery —
    the world round, sleep drive-moves, the cast rail — because the PLAYER drives it, not the world
    (having the world narrate the player's character acting on its own is the bug this prevents)."""
    fm = node.get("frontmatter", {}) if isinstance(node, dict) else {}
    return fm.get("kind") == "character" and str(fm.get("player", "")).strip().lower() in _TRUE


def get(world):
    """The player-character node (a character flagged player: true), or None."""
    for n in canon.load_all(world):
        if is_player(n):
            return n
    return None


def card(world) -> dict:
    """The player's card, or {} if they haven't defined one yet."""
    n = get(world)
    if not n:
        return {}
    fm = n["frontmatter"]
    return {"name": n["name"], "role": str(fm.get("role", "")).strip(),
            "wants": str(fm.get("wants", "")).strip(), "location": str(fm.get("location", "")).strip(),
            "description": n["body"].strip()}


def clause(world) -> str:
    """The narrator-prompt injection that makes the world address the player AS their character."""
    c = card(world)
    if not c.get("name"):
        return ""
    line = f"The player is {sec.neutralize(c['name'])}"
    if c["role"]:
        line += f", {sec.neutralize(c['role'])}"
    line += "."
    if c["description"]:
        line += f" {sec.neutralize(c['description'])}"
    if c["wants"]:
        line += f" They want {sec.neutralize(c['wants'])}."
    return ("\n\nTHE PLAYER'S CHARACTER: " + line + " Address them as this person and let the world "
            "react to who they are; but never narrate their private thoughts or decide their actions "
            "for them — the player drives their own character.")


def save(world, name, role="", description="", wants="", location=""):
    """Write (or replace) the player-character node. One PC per campaign: the flag is cleared from
    any prior player-character of a different name first."""
    name = (name or "").strip()
    if not name:
        return
    prior = get(world)
    if prior and prior["name"] != name:                 # demote the old PC to an ordinary character
        pfm = dict(prior["frontmatter"])
        pfm.pop("player", None)
        canon.write_node(world, prior["name"], prior["body"], pfm)
    fm = {"kind": "character", "player": "true"}
    for k, v in (("role", role), ("wants", wants), ("location", location)):
        if (v or "").strip():
            fm[k] = v.strip()
    canon.write_node(world, name, (description or "").strip() or name, fm)
