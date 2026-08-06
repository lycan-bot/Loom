"""loom.seal — the wall. The narrator's whole safety model: fiction never touches
the real system. Everything reads/writes only inside the campaign directory, and
canon/state are scanned for leaks of real-world paths or the source project.

Containment is enforced by three things: campaign NAMES pass config.valid_campaign_name +
campaign_dir (they can't escape the campaigns dir), node names are reduced to safe slugs by
canon.slug, and canon.write_node runs every node path through guard_path as a structural belt.
This scan is the belt-and-suspenders audit on top — it catches a real-world path or
source-project marker that bled into fiction.
"""
from __future__ import annotations
import re
from pathlib import Path
from . import canon, state, threads

# markers that must never appear in fiction — signs the log bled into the real world
_LEAK_PATTERNS = [
    re.compile(r"/(?:home|etc|root|var|usr|opt|boot|proc|sys|mnt|run|srv)/[^\s'\"]+"),
    re.compile(r"\b[A-Za-z]:[\\/][^\s'\"]+"),        # C:\path or C:/path — \b so 'word:/x' prose doesn't match
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
        text = node["body"] + " " + " ".join(str(v) for v in node["frontmatter"].values())
        for leak in leaks_in(text):                      # body AND frontmatter (voice/disposition/…)
            problems.append(f"{node['path'].name}: leak '{leak}'")
    for k, v in state.load(state_path).items():
        for leak in leaks_in(f"{k}: {v}"):
            problems.append(f"state[{k}]: leak '{leak}'")
    for t in threads.load(Path(state_path).parent / "threads.json"):
        for leak in leaks_in(" ".join(str(x) for x in [t.question, t.seed, t.payoff, *t.entities])):
            problems.append(f"thread[{t.id}]: leak '{leak}'")
    return problems
