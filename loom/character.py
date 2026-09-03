"""loom.character — per-character voice + evolving disposition.

A character's manner of speech (canon frontmatter `voice:`) is injected when they are in
the scene, so NPCs sound like themselves turn to turn rather than blurring into one
narrator voice. Their `disposition:` toward the player (updated by consolidation as the
relationship grows) colors how they treat you.

Pairs with npc.py: the characters that *want* things (drives) now also *sound* like
themselves and warm or cool toward the player.
"""
from __future__ import annotations
from pathlib import Path
from . import prompt_security as sec


def scene_characters(nodes) -> list:
    """Characters present in the retrieved scene, with their voice + disposition."""
    out = []
    for n in nodes:
        if n["frontmatter"].get("kind") != "character":
            continue
        out.append({"name": n["name"],
                    "voice": str(n["frontmatter"].get("voice", "")).strip(),
                    "disposition": str(n["frontmatter"].get("disposition", "")).strip()})
    return out


def voice_clause(nodes) -> str:
    """A prompt clause giving each in-scene character's voice + disposition, so the narrator
    keeps them consistent. Empty when no voiced characters are present."""
    lines = []
    for c in scene_characters(nodes):
        bits = []
        if c["voice"]:
            bits.append(f"speaks {c['voice']}")
        if c["disposition"]:
            bits.append(f"is {c['disposition']} toward the player")
        if bits:
            # voice/disposition are model-authored (consolidation) → fence as untrusted data,
            # one block per character, so an injected instruction can't act as a directive
            lines.append(f"- {sec.neutralize(c['name'])}: {sec.wrap('; '.join(bits), 'character')}")
    if not lines:
        return ""
    return "\n\nVOICES (keep each character consistent, distinct from the narrator):\n" + "\n".join(lines)


def card(node) -> dict:
    """A structured character card from a canon node — who/what they are, when/where they
    were met, their drive, voice, and disposition. Frontmatter fields + the body."""
    fm = node["frontmatter"]

    def g(k):
        return str(fm.get(k, "")).strip()

    return {"name": node["name"], "role": g("role"), "met": g("met"),
            "voice": g("voice"), "disposition": g("disposition"),
            "want": g("wants"), "bound": g("bound"),
            "description": node["body"].strip()}


def interior(world, tpath, spath, cfg, node) -> dict:
    """The composed NPC INTERIOR — card + personhood rung + mood + agenda + memory + memory-of-you, all
    from BLESSED signals (nothing stored, nothing self-propagating). Shared by GET /api/npc and the
    `loom npc` CLI. For INSPECTION the agenda/mood compose at a 0.5 display floor even for a low-rung NPC;
    `agenda_projected` flags that so it can't be misread as the live budget (the live gate still holds)."""
    from . import salience, agenda, mood, npc_memory, npc, threads, player, reputation, state, npc_standing
    name, fm = node["name"], node["frontmatter"]
    depth = float(cfg.get("depth", 0) or 0)
    tier = salience.tiers_by_name(world, tpath, spath).get(name, "side")
    rung = salience.char_rung(tier, depth)
    m = npc.moral_read(str(fm.get("wants", "")), str(fm.get("bound", "")))
    thread_list = threads.load(Path(spath).parent / "threads.json")
    pursuit = agenda.pursuit(name, m, thread_list, spath, max(rung, 0.5))
    st_all = state.load(spath)
    # how this NPC stands with the OTHERS — gated on the toggle like its two sibling reads (worldturn / narrate),
    # so a store left over from an ON period doesn't leak into the panel once the feature is turned off
    standings = npc_standing.of(npc_standing.load(st_all), name) if cfg.get("npc_standing") else []
    standing = 0
    rep_e = reputation.load(st_all).get(name)
    if isinstance(rep_e, dict):
        try:
            standing = int(rep_e.get("standing", 0) or 0)
        except (TypeError, ValueError):
            standing = 0
    pc = (player.card(world).get("name") or "").strip()

    def _mem(rows):
        return [{"what": e.get("what", ""), "source": e.get("source", "")} for e in rows]

    return {"name": name, "tier": tier, "rung": round(rung, 2), "is_player": player.is_player(node),
            "agenda_projected": bool(rung < salience.AGENDA_RUNG), "card": card(node),
            "mood": mood.label(fm.get("disposition", ""), standing, pursuit.get("status", "")),
            "agenda": pursuit, "remembers": _mem(npc_memory.recall(spath, name, k=6, blessed_only=False)),
            "remembers_player": _mem(npc_memory.shared(spath, name, pc, k=6, blessed_only=False)) if pc and pc != name else [],
            "standings": standings}
