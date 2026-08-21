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
from . import canon, npc, llm, state, player, retrieve, consolidate, transcript, config, episodic, salience, agenda, threads, mood, reputation
from . import prompt_security as sec

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


_DELIBERATE_PROMPT = """You are %s — a person in a living story, not the narrator. The player is
elsewhere; this is your own moment. Your goal: %s. What you have ACTUALLY done toward it: %s. With you
now: %s. In ONE sentence, state your INTENT this round: the specific, in-character move you will make
toward your goal (honouring what holds you back). State your intent, not the outcome."""


def _deliberate(name, moral, thread_list, spath, rung, others, ccfg) -> str:
    """The focal NPC of a high-rung group THINKS before it acts — a one-line intent from its goal and
    its BLESSED memory (a goal decision never reads the NPC's own improv, so no self-propagation loop
    can close). '' on any failure (the beat still runs, un-deliberated)."""
    p = agenda.pursuit(name, moral, thread_list, spath, rung)
    if not p:
        return ""
    did = "; ".join(p["remembers"][:3]) or "nothing yet"
    goal = p["goal"] + (f" (held back by {p['opposes']})" if p["opposes"] else "")
    try:
        # goal/memory/name are canon- or model-authored → defang the fence sigil + frame as untrusted,
        # and output-guard the intent (a small RP model can cave); a compromised intent is dropped
        raw = llm.complete(sec.UNTRUSTED_PREAMBLE + "\n\n" + _DELIBERATE_PROMPT % (
            sec.neutralize(name), sec.neutralize(goal), sec.neutralize(did), sec.neutralize(others or "no one")),
            ccfg, max_tokens=60, temperature=0.6)
        intent = " ".join(_s(raw).strip().split())[:200]
        return "" if sec.looks_compromised(intent) else intent
    except Exception:
        return ""


def run(cfg, world, exclude=(), tpath=None, spath=None) -> dict:
    """Play one world round: each group of major NPCs takes a turn. Propose-only — returns the
    turns, writes nothing. `exclude` (names) are in the live scene and skipped. `pending` is True
    when there were actors, even if the beat text failed
    (so a caller can distinguish 'no one has an agenda' from 'the model was unreachable')."""
    depth = float(cfg.get("depth", 0) or 0)
    enrich = bool(tpath and spath and depth > 0)      # the P4 agency layer rides the live, paths-present path
    actors = majors(world, exclude)
    if enrich:
        # TIER-AWARE CASTING: each actor's personhood budget = char_rung(tier, depth). A walk-on (rung 0)
        # doesn't take a world-round turn, the highest-personhood characters act first, and the cast WIDENS
        # with depth (a shallow world moves 1-2 leads; a deep one lets the fuller cast think).
        tiers = salience.tiers_by_name(world, tpath, spath)
        thread_list = threads.load(Path(spath).parent / "threads.json")
        scored = sorted(((n, m, loc, salience.char_rung(tiers.get(n["name"], "side"), depth))
                         for n, m, loc in actors), key=lambda e: -e[3])
        scored = [e for e in scored if e[3] > 0]
        rung_of = {n["name"]: r for n, m, loc, r in scored}
        gs = groups([(n, m, loc) for n, m, loc, _r in scored])
        # groups() re-sorts by SIZE, discarding the rung order — so re-rank by the group's highest-rung
        # member before the cap, or the largest group survives and a lead is dropped for lower-tier extras
        gs = sorted(gs, key=lambda g: -max(rung_of.get(n["name"], 0) for n, _m, _l in g))
        gs = gs[:max(1, min(len(gs), round(1 + depth * 4)))]
    else:
        thread_list, rung_of = [], {}
        gs = groups(actors)[:_MAX_TURNS]              # legacy path (no paths / depth 0): flat cap, no agency
    if not gs:
        return {"turns": [], "pending": False}

    ccfg = dict(cfg)
    for src, dst in (("consolidate_llm_url", "llm_url"), ("consolidate_model", "llm_model"),
                     ("consolidate_api_key", "api_key")):
        if cfg.get(src):
            ccfg[dst] = cfg[src]

    # ground the round in canon RELEVANT to this round's actors (their names, wants, places) — not an
    # arbitrary alphabetical slice of everything (the source of the 'invented testimony' confabulation)
    actor_names = [node["name"] for g in gs for node, m, _loc in g]
    query = " ".join(actor_names + [m.because for g in gs for node, m, _loc in g]
                     + [g[0][2] for g in gs if g[0][2]])
    canon_text = retrieve.grounded_context(world, cfg, query, anchors=actor_names,
                                           tpath=tpath, spath=spath) or "(no canon yet)"

    # each group's line — enriched with the NPC's AGENDA (goal + pursuit state + BLESSED memory) when they
    # have the personhood for one; the focal character of a high-rung group DELIBERATES (think→act) first
    delib_budget = 2                                  # bound the extra 'think' calls to the top groups
    rep = reputation.load(state.load(spath)) if enrich else {}

    def _standing(nm):
        e = rep.get(nm)
        try:
            return int(e.get("standing", 0)) if isinstance(e, dict) else 0
        except (TypeError, ValueError):
            return 0

    lines = []
    for g in gs:
        parts = []
        for node, m, _loc in g:
            name = node["name"]
            rung = rung_of.get(name, 0)
            if enrich and salience.has_agenda(rung):
                p = agenda.pursuit(name, m, thread_list, spath, rung)   # ONE pursuit call → agenda + mood
                md = mood.clause(name, node["frontmatter"].get("disposition", ""), _standing(name), p.get("status", ""), rung)
                parts.append(((agenda.line_of(p) + (" " + md if md else "")).strip()) or f"{name} ({m.because})")
            else:
                parts.append(f"{name} ({m.because})")
        block = f"- At {g[0][2] or 'parts unknown'}: " + " | ".join(parts)
        if enrich and delib_budget > 0:
            focal = max(g, key=lambda e: rung_of.get(e[0]["name"], 0))
            fname = focal[0]["name"]
            if salience.deliberates(rung_of.get(fname, 0)):
                delib_budget -= 1
                others = ", ".join(n["name"] for n, _m, _l in g if n["name"] != fname)
                intent = _deliberate(fname, focal[1], thread_list, spath, rung_of.get(fname, 0), others, ccfg)
                if intent:
                    block += f"\n    ({fname}'s intent this round: {intent})"
        lines.append(block)

    # constrain `where` to the round's actual locations, so the co-location routing below can match it
    where_vals = sorted({g[0][2] for g in gs if g[0][2]})
    where_prop = {"type": "string", "enum": where_vals + ["parts unknown"]} if where_vals else {"type": "string"}
    try:
        # the actors block carries canon wants + names + blessed memory + the (model-authored) intent, and
        # canon is the grounded slice — all untrusted story data → fence it, so an injected want/name/beat
        # can't seize the chronicler (the same discipline narrate/referee already use)
        raw = llm.complete(sec.UNTRUSTED_PREAMBLE + "\n\n"
                           + _ROUND_PROMPT % (sec.wrap("\n".join(lines), "actors"), sec.wrap(canon_text, "canon")),
                           ccfg, max_tokens=400,
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
        if not beat or sec.looks_compromised(beat):     # a beat that leaked the prompt / broke character is dropped
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
    episodic.record(state_path, [{"what": (_who(t.get("who")) + ": " + t["beat"]).strip(": "),
                                  "who": t.get("who")}    # the actor(s) — so each NPC can recall its own beats
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
