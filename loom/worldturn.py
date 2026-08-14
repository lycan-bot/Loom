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
from pathlib import Path
from . import canon, npc, llm, state, player, retrieve, consolidate, transcript, config, episodic

_JSON_RE = re.compile(r"\{[\s\S]*\}")
_MAX_TURNS = 4          # groups that act per round — the world moves without flooding the prompt

_ROUND_PROMPT = """You are the chronicler of a living story world. The player is elsewhere — this
is the world's people taking their own turn. For EACH group below, write ONE short beat (1-2
sentences) of what they do this round: a small, in-character, concrete step toward what they want,
grounded strictly in the canon. A group of one acts alone; a group of several INTERACT — cooperating
if their aims align, at odds if they collide. The world does NOT rearrange itself around the absent
player, and nothing hands the player an advantage.

Each actor's parenthetical is what they WANT — a goal they are still pursuing, NOT something that has
already happened. Write a concrete step TOWARD it; never narrate the goal as already achieved, and
never reference a past event, conversation, or testimony that is not in the canon below.

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


_TITLES = {"the", "a", "an", "inquisitor", "professor", "headmaster", "instructor", "master",
           "mistress", "lord", "lady", "sir", "dame", "captain", "doctor", "dr", "mr", "mrs", "ms"}


def scene_characters(cfg, world, tpath) -> set:
    """Characters NAMED in the CURRENT scene (the last couple of turns) — the ones the narrator is
    already voicing live. They must NOT also run as off-screen world-round actors: that's what put
    Wren (the player's constant companion, in every scene) 'elsewhere, studying with Fáelán' while she
    was right there. Detected by NAME MENTION, not retrieval — narration prose shares no vocabulary
    with a character's card, it just says their name (BM25 mis-ranks it entirely); a distinctive
    name-token (dropping titles like 'Professor') appearing in the recent text is the true signal."""
    try:
        recent = transcript.recent(tpath, 4)
    except Exception:
        return set()
    text_tokens = set(re.findall(r"[\w']+", " ".join(
        e.get("text", "") for e in recent if isinstance(e, dict)).lower()))
    if not text_tokens:
        return set()
    present = set()
    for n in canon.load_all(world):
        if n["frontmatter"].get("kind") != "character":
            continue
        name_tokens = {t for t in re.findall(r"[\w']+", n["name"].lower())
                       if t not in _TITLES and len(t) > 2}
        if name_tokens & text_tokens:                # any distinctive name-token appears in the scene
            present.add(n["name"])
    return present


def majors(world, exclude=()) -> list:
    """The major NPCs — characters with a stated want — as (node, Moral, location). `exclude` (names)
    drops NPCs currently in the live scene, so the world round only moves people who are elsewhere."""
    exclude = set(exclude)
    nodes = canon.load_all(world)
    places = {n["name"] for n in nodes if n["frontmatter"].get("kind") == "place"}
    out = []
    for n in nodes:
        if n["frontmatter"].get("kind") != "character" or player.is_player(n):
            continue                              # the PLAYER's character never takes a world-round turn
        if n["name"] in exclude:
            continue                              # in the live scene — the narrator is already voicing them
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


def run(cfg, world, exclude=(), tpath=None, spath=None) -> dict:
    """Play one world round: each group of major NPCs takes a turn. Propose-only — returns the
    turns, writes nothing. `exclude` (names) are in the live scene and skipped. `pending` is True
    when there were actors, even if the beat text failed
    (so a caller can distinguish 'no one has an agenda' from 'the model was unreachable')."""
    gs = groups(majors(world, exclude))[:_MAX_TURNS]
    if not gs:
        return {"turns": [], "pending": False}
    lines = [f"- At {g[0][2] or 'parts unknown'}: "
             + "; ".join(f"{node['name']} ({m.because})" for node, m, _loc in g) for g in gs]
    # ground the round in canon RELEVANT to this round's actors (their names, wants, places) — not an
    # arbitrary alphabetical slice of everything (the source of the 'invented testimony' confabulation)
    actor_names = [node["name"] for g in gs for node, m, _loc in g]
    query = " ".join(actor_names + [m.because for g in gs for node, m, _loc in g]
                     + [g[0][2] for g in gs if g[0][2]])
    canon_text = retrieve.grounded_context(world, cfg, query, anchors=actor_names,
                                           tpath=tpath, spath=spath) or "(no canon yet)"
    # constrain `where` to the round's actual locations, so the co-location routing below can match it
    where_vals = sorted({g[0][2] for g in gs if g[0][2]})
    where_prop = {"type": "string", "enum": where_vals + ["parts unknown"]} if where_vals else {"type": "string"}
    ccfg = dict(cfg)
    if cfg.get("consolidate_llm_url"):
        ccfg["llm_url"] = cfg["consolidate_llm_url"]
    if cfg.get("consolidate_model"):
        ccfg["llm_model"] = cfg["consolidate_model"]
    if cfg.get("consolidate_api_key"):
        ccfg["api_key"] = cfg["consolidate_api_key"]
    try:
        raw = llm.complete(_ROUND_PROMPT % ("\n".join(lines), canon_text), ccfg, max_tokens=400,
                           temperature=0.5, response_format=llm.schema_format("world_round", {
                               "type": "object", "properties": {"turns": {"type": "array", "items": {
                                   "type": "object", "properties": {
                                       "where": where_prop,
                                       "who": {"type": "array", "items": {"type": "string"}},
                                       "beat": {"type": "string"}}}}}}))
        m = _JSON_RE.search(raw)
        data = json.loads(m.group(0)) if m else {}
    except Exception:
        data = {}
    # model output is grammar-valid JSON but NOT shape-checked — guard every iterable with
    # isinstance (a non-list `turns`/`who` would otherwise crash here, OUTSIDE the try above)
    raw_turns = data.get("turns")
    turns = []
    for t in (raw_turns if isinstance(raw_turns, list) else []):
        if not isinstance(t, dict):
            continue
        beat = _s(t.get("beat")).strip()
        if not beat:
            continue
        who_raw = t.get("who")
        who = [w for w in who_raw if isinstance(w, str)] if isinstance(who_raw, list) else []
        turns.append({"where": _s(t.get("where")).strip(), "who": who, "beat": beat})
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
    cadence = max(1, int(cfg.get("world_cadence", 3) or 3))
    if n % cadence != 0:                                  # the world takes a round every `cadence` turns
        state.save(state_path, st)
        return []
    # NPCs the narrator is already voicing in the live scene are excluded — the world round is only for
    # people ELSEWHERE (this is what finally keeps the in-scene companion out of the 'meanwhile' pulse)
    tpath = Path(state_path).parent / config.transcript_path(cfg).name   # sibling of THIS state file, not the global one
    in_scene = scene_characters(cfg, world, tpath)
    turns = run(cfg, world, exclude=in_scene, tpath=tpath, spath=state_path)["turns"]
    # every world-round beat is a real thing that happened off-screen → the timeline records it (the
    # second clock), anchored just after the latest played entry so 'when did the world move?' resolves.
    # Recorded here (after this turn's undo-snapshot) so an undo of the turn rolls these beats back too.
    n_tx = len(transcript.read_all(tpath))

    def _who(w):                                          # a coupled turn's `who` is a list of names
        return ", ".join(str(x) for x in w) if isinstance(w, (list, tuple)) else str(w or "")
    episodic.record(state_path, [{"what": (_who(t.get("who")) + ": " + t["beat"]).strip(": ")}
                                 for t in turns if consolidate._s(t.get("beat")).strip()],
                    entry_start=n_tx, entry_end=n_tx, source="world")
    # co-located routing: a turn AT the player's current place folds into their SCENE (a 'nearby'
    # note narrate weaves into the next narration), rather than a detached 'meanwhile' pulse. The
    # rest — turns elsewhere in the world — stay the pulse.
    # normalize BOTH sides through the place normalizer (strips 'the ', case, punctuation) so
    # "The Library" and "library" co-locate — the raw string compare silently missed those
    loc = consolidate._norm(st.get("_location", ""))
    here = [t for t in turns if loc and consolidate._norm(t.get("where", "")) == loc]
    if here:
        note = " ".join(t["beat"] for t in here)
        prior = st.get("_nearby", "")
        st["_nearby"] = (prior + " " + note).strip() if prior else note
    state.save(state_path, st)
    return [t for t in turns if t not in here]
