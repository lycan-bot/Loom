"""loom.salience — who matters right now, and how much.

Deterministic tiering of the cast for the card rail. From GROUNDED signals only (no model
inference): how many active threads a character sits in, how often they've been mentioned in play,
how connected they are in the canon graph, whether they carry an agenda (a `wants`), and how the
world regards them (reputation). An explicit `importance:` frontmatter field OVERRIDES the derived
tier — the hybrid: auto by default, pin what matters. The tiers shift as the story does.

Tiers, in order: world (setting + places + lore + events) · main · antagonist · side · passing.
Characters AND factions are tiered as agents (a faction can be an antagonist); everything else is
the world's fabric.
"""
from __future__ import annotations
import re
from pathlib import Path
from . import canon, threads as _threads, transcript, state, reputation, player

TIERS = ["world", "factions", "main", "antagonist", "side", "passing"]
TIER_LABELS = {"world": "World", "factions": "Factions & groups", "main": "Main characters",
               "antagonist": "Primary antagonists", "side": "Major side characters", "passing": "Passing NPCs"}

_MAIN_MIN = 5          # salience score → tier thresholds (tunable; threads + mentions dominate once play starts)
_SIDE_MIN = 2
_HOSTILE = ("hostil", "antagon", "enemy", "foe", "hate", "menac", "threat", "cruel",
            "murder", "kill", "venge", "despis", "loath", "wrath", "rival")


def _norm_tier(v) -> str | None:
    v = str(v or "").strip().lower()
    if v in ("main", "protagonist", "major", "lead"):
        return "main"
    if v in ("antagonist", "villain", "enemy", "adversary"):
        return "antagonist"
    if v in ("side", "supporting", "secondary"):
        return "side"
    if v in ("passing", "minor", "background", "extra", "bit"):
        return "passing"
    return None


def _truthy(v) -> bool:
    return str(v or "").strip().lower() in ("true", "1", "yes")


def _degree(nodes) -> dict:
    """Undirected degree in the canon graph — a rough centrality signal."""
    names = {n["name"] for n in nodes}
    deg = {n["name"]: 0 for n in nodes}
    for n in nodes:
        for link in n.get("links", []):
            tgt = link.split("|")[0].strip()
            if tgt in names and tgt != n["name"]:
                deg[n["name"]] += 1
                deg[tgt] += 1
    return deg


def scores(world: Path, spath: Path) -> dict:
    """Per-node PERSISTENT salience — structural importance independent of recent chatter, for the
    decay re-ranker: thread membership + canon-graph degree + carrying an agenda + reputation
    magnitude. Recent mentions are DELIBERATELY excluded (decay's recency term covers those). Pure
    read; deterministic. {name: score}."""
    nodes = canon.load_all(world)
    ths = [t for t in _threads.load(Path(spath).parent / "threads.json")
           if getattr(t, "status", "") != "resolved"]
    st = state.load(spath)
    rep = st.get("_rep") if isinstance(st.get("_rep"), dict) else {}
    deg = _degree(nodes)

    def standing(name):
        r = rep.get(name)
        try:
            return int(r.get("standing", 0) or 0) if isinstance(r, dict) else 0
        except (TypeError, ValueError):
            return 0

    out = {}
    for n in nodes:
        name, fm = n["name"], n["frontmatter"]
        th = sum(1 for t in ths if name in (getattr(t, "entities", []) or []))
        wants = 1 if str(fm.get("wants", "")).strip() else 0
        out[name] = 3 * th + deg.get(name, 0) + 2 * wants + 2 * abs(standing(name))
    return out


def classify(world: Path, tpath: Path, spath: Path) -> list:
    """Return the ordered tiers, each {key, label, cards:[{name, kind, hint, overridden, score,
    standing}]}. Empty tiers are included (the UI hides them). Pure read — writes nothing."""
    nodes = canon.load_all(world)
    ths = [t for t in _threads.load(Path(spath).parent / "threads.json")
           if getattr(t, "status", "") != "resolved"]
    st = state.load(spath)
    rep = st.get("_rep") if isinstance(st.get("_rep"), dict) else {}
    # split the log by role: the PLAYER's mentions anchor salience at full weight; the NARRATOR's prose
    # (model output — which an NPC's own world-round beat can reach via the _nearby weave) counts at HALF
    # and is CAPPED, so a character can't self-amplify its own tier/rung off its own output (the same
    # anti-self-amplification diode decay._recency uses; without it char_rung ratchets on improv).
    _entries = transcript.read_all(tpath)
    player_log = "\n".join(str(e.get("text", "")) for e in _entries if e.get("role") == "player").lower()
    narr_log = "\n".join(str(e.get("text", "")) for e in _entries if e.get("role") != "player").lower()
    deg = _degree(nodes)

    def mentions(name: str) -> int:
        low = name.lower()
        try:
            pat = r"\b" + re.escape(low) + r"\b"
            p, n = len(re.findall(pat, player_log)), len(re.findall(pat, narr_log))
        except re.error:
            p, n = player_log.count(low), narr_log.count(low)
        return p + min(1, int(round(0.5 * n)))       # narrator caps at +1 — strictly BELOW a tier quantum
        #                                              (a want+link NPC sits at 3; +2 would reach _MAIN_MIN=5
        #                                               and self-promote off its own improv, +1 cannot)

    def thread_hits(name: str) -> int:
        return sum(1 for t in ths if name in (getattr(t, "entities", []) or []))

    def _standing(name):
        r = rep.get(name)
        if isinstance(r, dict):
            try:
                return int(r.get("standing", 0) or 0)
            except (TypeError, ValueError):
                return 0
        return 0

    tiers = {k: [] for k in TIERS}
    for n in nodes:
        fm = n["frontmatter"]
        kind = fm.get("kind", "lore")
        name = n["name"]

        if player.is_player(n):
            continue                              # the player's own character isn't cast — it's you

        # factions/groups are the world's ORGANIZATIONS — filed under the world, not tiered as
        # individuals (a faction isn't a 'main character'). Their standing still colours the card.
        if kind == "faction":
            st_ = _standing(name)
            hint = str(fm.get("role") or "").strip() or (reputation.label(st_) if st_ else "")
            tiers["factions"].append({"name": name, "kind": kind, "hint": hint, "overridden": False,
                                      "score": deg.get(name, 0) + 2 * abs(st_), "standing": st_})
            continue

        if kind != "character":
            hint = "setting" if _truthy(fm.get("setting")) else kind
            tiers["world"].append({"name": name, "kind": kind, "hint": hint,
                                   "overridden": False, "score": deg.get(name, 0), "standing": 0})
            continue

        want = str(fm.get("wants", "")).strip()
        disp = str(fm.get("disposition", "")).strip()
        standing = _standing(name)

        th, mn, dg = thread_hits(name), mentions(name), deg.get(name, 0)
        score = 3 * th + mn + dg + (2 if want else 0) + 2 * abs(standing)

        # antagonist signal = opposition to the PLAYER specifically: an openly hostile disposition
        # toward them, or a badly negative reputation standing. A character's own inner conflict
        # (wants-but-held-back) is depth, NOT antagonism — it must not tip a sympathetic NPC here.
        disp_hostile = any(w in disp.lower() for w in _HOSTILE)
        hostile = disp_hostile or standing <= -2

        # explicit override wins (the hybrid) — importance:, or antagonist: true
        override = _norm_tier(fm.get("importance"))
        if _truthy(fm.get("antagonist")):
            override = "antagonist"
        if override:
            tier, overridden = override, True
        else:
            overridden = False
            if hostile and score >= _SIDE_MIN:
                tier = "antagonist"
            elif score >= _MAIN_MIN:
                tier = "main"
            elif score >= _SIDE_MIN:
                tier = "side"
            else:
                tier = "passing"

        hint = str(fm.get("role") or "").strip()
        if not hint:                                    # no role → a short 'why it's here'
            bits = []
            if hostile:
                bits.append("hostile" if disp_hostile else f"standing {standing:+d}")
            if th:
                bits.append(f"{th} thread{'s' if th > 1 else ''}")
            if mn:
                bits.append("met often" if mn >= 4 else "met a few times" if mn >= 2 else "met once")
            hint = " · ".join(bits)
        tiers[tier].append({"name": name, "kind": kind, "hint": hint,
                            "overridden": overridden, "score": score, "standing": standing})

    for k in tiers:
        if k == "world":
            tiers[k].sort(key=lambda c: (c["hint"] != "setting", -c["score"], c["name"]))
        else:
            tiers[k].sort(key=lambda c: (-c["score"], c["name"]))
    return [{"key": k, "label": TIER_LABELS[k], "cards": tiers[k]} for k in TIERS]


# --- char_rung: the depth-modulation primitive (NPC-agency P3) ---
# An NPC's PERSONHOOD BUDGET = their salience TIER weight × the realness dial (depth). This is the one
# scalar the whole agency arc reads: it sets how many past beats an NPC recalls (npc_memory), whether it
# earns a tracked agenda that it pursues over time, and whether it deliberates before acting. A passing
# walk-on gets 0 (today's stateless behavior); a main character at high depth gets the full person.
_TIER_WEIGHT = {"main": 1.0, "antagonist": 1.0, "side": 0.5,
                "passing": 0.0, "world": 0.0, "factions": 0.0}

AGENDA_RUNG = 0.5        # at/above this an NPC earns a tracked, progress-bearing agenda (P2)
DELIBERATE_RUNG = 0.75   # at/above this an NPC thinks before it acts (P4) — bounds the deliberation cost


def char_rung(tier: str, depth) -> float:
    """Personhood budget in [0, 1] = tier weight × depth. 0 = a walk-on (no memory, no agenda);
    1 = a full character. Pure + deterministic; the arc's single depth-modulation dial."""
    try:
        d = max(0.0, min(1.0, float(depth)))
    except (TypeError, ValueError):
        d = 0.0
    return _TIER_WEIGHT.get(str(tier or "").strip().lower(), 0.0) * d


def recall_k(rung: float) -> int:
    """How many past beats this NPC recalls — 0 for a walk-on, up to ~4 for a full character."""
    return int(round(max(0.0, float(rung or 0.0)) * 4))


def has_agenda(rung: float) -> bool:
    return float(rung or 0.0) >= AGENDA_RUNG


def deliberates(rung: float) -> bool:
    return float(rung or 0.0) >= DELIBERATE_RUNG


def tiers_by_name(world: Path, tpath: Path, spath: Path) -> dict:
    """name -> tier key (main/antagonist/side/passing/world/factions), from classify — so a caller can
    compute char_rung per NPC. Pure read (classify writes nothing)."""
    out = {}
    for group in classify(world, tpath, spath):
        for c in group["cards"]:
            out[c["name"]] = group["key"]
    return out
