"""loom.seal — the wall. The narrator's whole safety model: fiction never touches
the real system. Everything reads/writes only inside the campaign directory, and
canon/state are scanned for leaks of real-world paths or the source project.

This is deliberately simple: separation is enforced structurally (every path goes
through guard_path), and this scan is the belt-and-suspenders audit on top.
"""
from __future__ import annotations
import re
from pathlib import Path
from . import canon, state, threads

# markers that must never appear in fiction — signs the log bled into the real world
_LEAK_PATTERNS = [
    re.compile(r"/home/[^\s'\"]+"),
    re.compile(r"[A-Za-z]:\\\\[^\s'\"]+"),
    re.compile(r"\bprimarch\b", re.I),
    re.compile(r"\bSIGILUS_CONFIG_DIR\b"),
    re.compile(r"\binviolable_manifest\b", re.I),
    re.compile(r"\bapi[_-]?key\b", re.I),
]


class SealBreach(RuntimeError):
    pass


def guard_path(p: Path, campaign: Path) -> Path:
    """Raise unless `p` resolves inside the campaign directory."""
    rp, rc = Path(p).resolve(), Path(campaign).resolve()
    if rp != rc and rc not in rp.parents:
        raise SealBreach(f"path escapes the campaign seal: {p}")
    return p


def leaks_in(text: str) -> list[str]:
    hits: list[str] = []
    for pat in _LEAK_PATTERNS:
        hits += pat.findall(text or "")
    return hits


def check_campaign(world: Path, state_path: Path) -> list[str]:
    """Scan all canon + state for real-world leakage. Returns problems (empty = sealed)."""
    problems = []
    for node in canon.load_all(world):
        for leak in leaks_in(node["body"]):
            problems.append(f"{node['path'].name}: leak '{leak}'")
    for k, v in state.load(state_path).items():
        for leak in leaks_in(f"{k}: {v}"):
            problems.append(f"state[{k}]: leak '{leak}'")
    for t in threads.load(Path(state_path).parent / "threads.json"):
        for leak in leaks_in(" ".join([t.question, t.seed, t.payoff, *t.entities])):
            problems.append(f"thread[{t.id}]: leak '{leak}'")
    return problems
