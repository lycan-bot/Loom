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


DETECTORS = [dangling_links, thread_unknown_entities, orphan_nodes]   # structural: (nodes, thr)


# --- consistency detectors (storyteller-memory Phase 4): transcript-aware, so they catch the story
# CONTRADICTING its own canon. Signature (nodes, thr, ctx) where ctx = {world, tpath, spath}. Advisory. ---

_DEAD_STATUS = {"dead", "deceased", "slain", "killed", "fallen", "perished"}
_DEAD_RE = re.compile(
    r"\b(?:is dead|lies dead|now dead|was slain|were slain|was killed|were killed|has died|had died|"
    r"died|perished|passed away|is deceased|met (?:his|her|their) death|drew (?:his|her|their) last breath)\b",
    re.I)


def _canonically_dead(node) -> bool:
    fm = node["frontmatter"]
    if any(str(fm.get(k, "")).strip().lower() in _DEAD_STATUS for k in ("status", "fate", "state")):
        return True
    if str(fm.get("alive", "")).strip().lower() in ("no", "false"):
        return True
    return bool(_DEAD_RE.search(node.get("body", "") or ""))


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
    return [Finding("high", "dead-but-active",
                    f"'{n['name']}' is marked dead in canon but appears in a recent turn "
                    "— a resurrection the story dropped, or a stale death record")
            for n in dead if n["name"] in present]


def confabulated_entities(nodes, thr, ctx):
    """Names the narrator keeps using that have no canon node (Phase 3's emergent signal, surfaced as a
    continuity note) — a confabulation to squash, or an emergent entity worth adding to canon."""
    from . import extract
    return [Finding("low", "confabulated-entity",
                    f"the narrator keeps using '{e['name']}' ({e['count']} turns) — no canon node; "
                    "add it or catch a confabulation")
            for e in extract.emergent(ctx["tpath"], ctx["world"], min_turns=2)]


TX_DETECTORS = [confabulated_entities, dead_but_active]               # consistency: (nodes, thr, ctx)


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
