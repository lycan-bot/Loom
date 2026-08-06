"""loom.worldturn — the world round: major NPCs take turns advancing their agendas.

Between and during the player's turns, the world's people act on their own. Each major NPC (a
character with a `wants`) has a LOCATION; those sharing a location take a COUPLED turn — an
interaction, cooperating if their aims align or clashing if they collide — while NPCs apart each
take a SOLO turn. Every turn is a small, in-character, canon-grounded step, PROPOSE-ONLY (the diode).

This is inter-NPC politics as a turn mechanic. Restraint is preserved: a turn reaches the player
only when they are co-located with it (surfaced as a scene beat, still governed by pacing) or when
the world toggle shows the round; otherwise it just moves the world in the background.

Location is a `location:` frontmatter field naming a place node; if unset it is seeded from the
first place a character is linked to, and is otherwise 'unknown' (the NPC acts solo). It is meant
to be MUTABLE — an NPC's own turn can carry them elsewhere, so groups form and dissolve over rounds.
"""
from __future__ import annotations
import json
import re
from . import canon, npc, llm, state

_JSON_RE = re.compile(r"\{[\s\S]*\}")
_MAX_TURNS = 4          # groups that act per round — the world moves without flooding the prompt

_ROUND_PROMPT = """You are the chronicler of a living story world. The player is elsewhere — this
is the world's people taking their own turn. For EACH group below, write ONE short beat (1-2
sentences) of what they do this round: a small, in-character, concrete step toward what they want,
grounded strictly in the canon. A group of one acts alone; a group of several INTERACT — cooperating
if their aims align, at odds if they collide. The world does NOT rearrange itself around the absent
player, and nothing hands the player an advantage.

THIS ROUND (each line is one group taking its turn):
%s

CANON (the world's established truth):
%s

Respond with ONE json object:
{"turns": [{"where": "<location>", "who": ["character names"], "beat": "the prose beat"}]}
"""


def _s(x) -> str:
    """A model scalar coerced to a clean string — never a crash on a bad type (audit lesson)."""
    return x if isinstance(x, str) else ""


def _location(node, places) -> str:
    """Where a character is: their `location:` frontmatter, or — if unset — the first PLACE they're
    linked to (so the field is optional; the canon graph seeds it). '' = whereabouts unknown."""
    loc = str(node["frontmatter"].get("location", "")).strip()
    if loc:
        return loc
    for link in node.get("links", []):
        target = link.split("|")[0].strip()
        if target in places:
            return target
    return ""


def majors(world) -> list:
    """The major NPCs — characters with a stated want — as (node, Moral, location)."""
    nodes = canon.load_all(world)
    places = {n["name"] for n in nodes if n["frontmatter"].get("kind") == "place"}
    out = []
    for n in nodes:
        if n["frontmatter"].get("kind") != "character":
            continue
        want = str(n["frontmatter"].get("wants", "")).strip()
        if not want:
            continue
        m = npc.moral_read(want, str(n["frontmatter"].get("bound", "")).strip())
        out.append((n, m, _location(n, places)))
    return out


def groups(majors_list) -> list:
    """Group majors by location — same known location → a coupled group (an interaction); each
    unknown-location NPC is its own solo group. Interactions first, then stable by name."""
    by_loc: dict = {}
    solo: list = []
    for entry in majors_list:
        loc = entry[2]
        if loc:
            by_loc.setdefault(loc, []).append(entry)
        else:
            solo.append([entry])
    return sorted(list(by_loc.values()) + solo, key=lambda g: (-len(g), g[0][0]["name"]))


def run(cfg, world) -> dict:
    """Play one world round: each group of major NPCs takes a turn. Propose-only — returns the
    turns, writes nothing. `pending` is True when there were actors, even if the beat text failed
    (so a caller can distinguish 'no one has an agenda' from 'the model was unreachable')."""
    gs = groups(majors(world))[:_MAX_TURNS]
    if not gs:
        return {"turns": [], "pending": False}
    lines = [f"- At {g[0][2] or 'parts unknown'}: "
             + "; ".join(f"{node['name']} ({m.because})" for node, m, _loc in g) for g in gs]
    canon_text = "\n".join(f"{n['name']}: {n['body'][:150]}" for n in canon.load_all(world))[:1500]
    ccfg = dict(cfg)
    if cfg.get("consolidate_llm_url"):
        ccfg["llm_url"] = cfg["consolidate_llm_url"]
    if cfg.get("consolidate_model"):
        ccfg["llm_model"] = cfg["consolidate_model"]
    if cfg.get("consolidate_api_key"):
        ccfg["api_key"] = cfg["consolidate_api_key"]
    try:
        raw = llm.complete(_ROUND_PROMPT % ("\n".join(lines), canon_text), ccfg, max_tokens=400,
                           temperature=0.5, response_format={"type": "json_object"})
        m = _JSON_RE.search(raw)
        data = json.loads(m.group(0)) if m else {}
    except Exception:
        data = {}
    turns = [{"where": _s(t.get("where")).strip(),
              "who": [w for w in (t.get("who") or []) if isinstance(w, str)],
              "beat": _s(t.get("beat")).strip()}
             for t in (data.get("turns") or []) if isinstance(t, dict) and _s(t.get("beat")).strip()]
    return {"turns": turns, "pending": True}


def maybe_round(cfg, world, state_path) -> list:
    """Run a world round if the SHOW toggle is on and the cadence is due — the live-loop hook.
    Advances a per-campaign turn counter in state; returns the turns (possibly []) for the caller
    to display. When the toggle is off, the world's between-turn life is carried by sleep instead,
    so this never fires (and never spends a model call). Depth-gated like everything else."""
    if not cfg.get("world_rounds") or float(cfg.get("depth", 0) or 0) <= 0:
        return []
    st = state.load(state_path)
    n = int(st.get("_wturn", 0) or 0) + 1
    st["_wturn"] = n
    state.save(state_path, st)
    cadence = max(1, int(cfg.get("world_cadence", 3) or 3))
    if n % cadence != 0:                                  # the world takes a round every `cadence` turns
        return []
    return run(cfg, world)["turns"]
