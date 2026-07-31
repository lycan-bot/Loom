"""loom.guard — the continuity guard: read-only checks over canon + the plan that flag
inconsistencies a long campaign accrues. Advisory ONLY — it never mutates anything.

A small detector registry (after Primarch's): each detector is a pure function over
(nodes, threads) → findings, so new checks are one function away. A broken detector never
breaks the guard.
"""
from __future__ import annotations
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


DETECTORS = [dangling_links, thread_unknown_entities, orphan_nodes]


def check(world, threads_path):
    """Run every detector; return findings sorted most-severe first. Never raises."""
    nodes = canon.load_all(world)
    thr = threads.load(threads_path)
    findings = []
    for d in DETECTORS:
        try:
            findings += d(nodes, thr)
        except Exception:
            continue
    order = {"high": 0, "med": 1, "low": 2}
    return sorted(findings, key=lambda f: order.get(f.severity, 3))
