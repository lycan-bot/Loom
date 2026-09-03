"""loom.guard — the continuity guard: read-only checks over canon + the plan that flag
inconsistencies a long campaign accrues. Advisory ONLY — it never mutates anything.

A small detector registry (after Primarch's): each detector is a pure function over
(nodes, threads) → findings, so new checks are one function away. A broken detector never
breaks the guard.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from . import canon, threads


@dataclass(frozen=True)
class Finding:
    severity: str    # "high" | "med" | "low"
    kind: str
    message: str


def _target(link):
    return link.split("|")[0].strip()


def dangling_links(nodes, thr):
    names = {n["name"] for n in nodes}
    return [Finding("low", "dangling-link",
                    f"'{n['name']}' links to [[{_target(l)}]], which has no canon node")
            for n in nodes for l in n["links"] if _target(l) not in names]


def thread_unknown_entities(nodes, thr):
    names = {n["name"] for n in nodes}
    out = []
    for t in thr:
        if t.status == "resolved":
            continue
        for e in t.entities:
            if e not in names:
                out.append(Finding("med", "unknown-entity",
                                   f"thread '{t.id}' involves '{e}', which has no canon node"))
    return out


def orphan_nodes(nodes, thr):
    names = {n["name"] for n in nodes}
    inbound = {_target(l) for n in nodes for l in n["links"]}
    out = []
    for n in nodes:
        outbound = [_target(l) for l in n["links"] if _target(l) in names]
        if not outbound and n["name"] not in inbound:
            out.append(Finding("low", "orphan",
                               f"'{n['name']}' is isolated — nothing links to it and it links to nothing"))
    return out


def bloated_node(nodes, thr):
    """A canon node that has accreted past the compaction threshold — a candidate for `loom compact`
    (Phase 7), so a long campaign's central nodes don't slow every turn."""
    from . import compact
    big = [n for n in nodes if len(n.get("body", "") or "") > compact._DEFAULT_THRESHOLD]
    return [Finding("low", "bloated-node",
                    f"'{n['name']}' has grown large ({len(n['body'])} chars) — 'loom compact' distills it")
            for n in sorted(big, key=lambda n: -len(n["body"]))[:5]]


DETECTORS = [dangling_links, thread_unknown_entities, orphan_nodes, bloated_node]   # structural: (nodes, thr)


# --- consistency detectors (storyteller-memory Phase 4): transcript-aware, so they catch the story
# CONTRADICTING its own canon. Signature (nodes, thr, ctx) where ctx = {world, tpath, spath}. Advisory. ---

_DEAD_STATUS = {"dead", "deceased", "slain", "killed", "fallen", "perished"}
_ALIVE_STATUS = {"alive", "living", "well"}
# ONLY an explicit author marker — a parenthetical '(deceased)' or an inline 'status: dead'. NOT free
# prose: a flat regex can't tell 'Varro was slain' (he died) from 'her sister was slain' (she didn't)
# or 'in her nightmares she was slain' (negated), so incidental prose is never treated as a death.
_DEAD_MARKER_RE = re.compile(
    r"[\(\[](?:dead|deceased|slain|killed|late)[\)\]]|"
    r"\b(?:status|fate|state)\s*[:=]\s*(?:dead|deceased|slain|killed)\b", re.I)


def _canonically_dead(node) -> bool:
    """Whether canon marks this character dead. Structured frontmatter is AUTHORITATIVE (an explicit
    `status: alive` / `alive: yes` skips the body entirely); the body counts only via an explicit
    death MARKER, never incidental backstory prose (which can't be attributed to the right subject)."""
    fm = node["frontmatter"]
    alive = str(fm.get("alive", "")).strip().lower()
    status = " ".join(str(fm.get(k, "")).strip().lower() for k in ("status", "fate", "state")).split()
    if alive in ("no", "false") or any(w in _DEAD_STATUS for w in status):
        return True
    if alive in ("yes", "true") or any(w in _ALIVE_STATUS for w in status):
        return False                                   # explicit alive → authoritative, ignore the body
    return bool(_DEAD_MARKER_RE.search(node.get("body", "") or ""))


def _recent_text(tpath, n_pairs=6) -> str:
    from . import recall
    return " ".join(p["text"] for p in recall.pairs(tpath)[-n_pairs:])


def dead_but_active(nodes, thr, ctx):
    """A character canon marks dead who is NAMED in a recent turn — a resurrection the story forgot,
    or a stale death record. The classic continuity collapse ('a character stated dead who then acts')."""
    from . import extract
    dead = [n for n in nodes if n["frontmatter"].get("kind") == "character" and _canonically_dead(n)]
    if not dead:
        return []
    present = set(extract.present(_recent_text(ctx["tpath"]), ctx["world"]))
    return [Finding("med", "dead-but-active",
                    f"'{n['name']}' is marked dead in canon but is mentioned in a recent turn "
                    "— a stale death record, or a resurrection the story dropped")
            for n in dead if n["name"] in present]


def confabulated_entities(nodes, thr, ctx):
    """Names the narrator keeps using that have no canon node (Phase 3's emergent signal, surfaced as a
    continuity note) — a confabulation to squash, or an emergent entity worth adding to canon."""
    from . import extract
    return [Finding("low", "confabulated-entity",
                    f"the narrator keeps using '{e['name']}' ({e['count']} turns) — no canon node; "
                    "add it or catch a confabulation")
            for e in extract.emergent(ctx["tpath"], ctx["world"], min_turns=2)]


def disposition_reversal(nodes, thr, ctx):
    """A character whose recorded feeling toward the player has FLIP-FLOPPED — reversed direction two
    or more times in the provenance ledger (warm→hostile→warm…). A single reversal is a legitimate arc
    (a betrayal, a reconciliation), so it stays quiet; OSCILLATION is the archivist contradicting itself,
    the data-integrity smell the ledger exists to catch. `loom why <name>` shows the full old→new trail."""
    spath = ctx.get("spath")
    if not spath:
        return []
    from collections import Counter
    from . import provenance
    counts = Counter(r["name"] for r in provenance.reversals(spath)
                     if r.get("field") == "disposition" and r.get("name")
                     and r.get("source") != "reversal_bless")   # an operator-BLESSED flip is authorised, not self-contradiction
    return [Finding("med", "disposition-reversal",
                    f"'{name}' feeling toward the player has flip-flopped {c}× in the record — the archivist "
                    f"may be contradicting itself; 'loom why {name}' shows the trail")
            for name, c in sorted(counts.items()) if c >= 2]


# the symbolic-object layer feeds continuity: a subject the WORLD store marks terminally gone that the
# story then contradicts. Unambiguous terminal VALUES only (a `state`/`condition` field, not free prose —
# and 'gone' is dropped as ambiguous: left ≠ destroyed), so a tracked fact, never a guessed one.
_TERMINAL_STATES = {"dead", "deceased", "slain", "killed", "fallen", "perished", "destroyed", "burned",
                    "burnt", "shattered", "ruined", "razed", "demolished", "obliterated", "incinerated",
                    "dissolved", "collapsed", "sunk", "sunken"}
_TERMINAL_ATTRS = {"state", "condition", "status", "fate"}


def world_dead_but_active(nodes, thr, ctx):
    """A subject the WORLD store marks terminally gone (destroyed / dead / burned) that is still ACTIVE.
    Two deterministic, structured signals — no prose parsing:
      • STRONG (med): the subject acts as a `who` in a blessed episodic beat dated STRICTLY AFTER it was
        marked gone (both clocks known) — a temporal contradiction the other detectors can't see, since a
        canon death carries no timestamp but a world fact carries `since`;
      • MENTION (low): a canon CHARACTER the world store marks terminal, still named in a recent turn.
    The world layer's continuity contribution: a tracked terminal state the story then violates."""
    spath = ctx.get("spath")
    if not spath:
        return []
    from . import world as world_layer, episodic, extract
    terminal = {}                                        # subject_norm -> (subject, value, since|None)
    for f in world_layer.load(spath):
        if world_layer._norm(f["attribute"]) in _TERMINAL_ATTRS and world_layer._norm(f["value"]) in _TERMINAL_STATES:
            since = f.get("since")
            terminal[world_layer._norm(f["subject"])] = (f["subject"], f["value"],
                                                         since if isinstance(since, int) else None)
    if not terminal:
        return []
    out, flagged = [], set()
    for e in episodic.entries(spath):                    # STRONG: it acts in a beat AFTER it was marked gone
        es = e.get("entry_start")
        whos = e.get("who") if isinstance(e.get("who"), list) else []
        for w in whos:
            wn = world_layer._norm(w)
            subj_val = terminal.get(wn)
            if subj_val and wn not in flagged and isinstance(es, int) and isinstance(subj_val[2], int) and es > subj_val[2]:
                out.append(Finding("med", "world-dead-but-active",
                                   f"the world marks '{subj_val[0]}' {subj_val[1]}, but '{subj_val[0]}' acts in a "
                                   "later beat — a continuity break (a dropped resurrection, or a stale world fact)"))
                flagged.add(wn)
    char_norms = {world_layer._norm(n["name"]) for n in nodes if n["frontmatter"].get("kind") == "character"}
    present = ({world_layer._norm(p) for p in extract.present(_recent_text(ctx["tpath"]), ctx["world"])}
               if ctx.get("tpath") else set())
    for sn, (subj, val, _since) in terminal.items():     # MENTION: a canon char marked terminal, named recently
        if sn not in flagged and sn in char_norms and sn in present:
            out.append(Finding("low", "world-dead-but-active",
                               f"the world marks '{subj}' {val}, but they are named in a recent turn — a stale "
                               "record, or a resurrection the story dropped"))
            flagged.add(sn)
    return out


TX_DETECTORS = [confabulated_entities, dead_but_active, disposition_reversal, world_dead_but_active]


def check(world, threads_path, tpath=None, spath=None):
    """Run every detector; return findings sorted most-severe first. Never raises. When `tpath` is
    given, the transcript-aware consistency detectors run too (the story-vs-canon checks)."""
    nodes = canon.load_all(world)
    thr = threads.load(threads_path)
    findings = []
    for d in DETECTORS:
        try:
            findings += d(nodes, thr)
        except Exception:
            continue
    if tpath is not None:
        ctx = {"world": world, "tpath": tpath, "spath": spath}
        for d in TX_DETECTORS:
            try:
                findings += d(nodes, thr, ctx)
            except Exception:
                continue
    order = {"high": 0, "med": 1, "low": 2}
    return sorted(findings, key=lambda f: order.get(f.severity, 3))
