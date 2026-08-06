"""loom.config — project + campaign paths and settings, loaded from config.json.

Zero-dependency. The whole project reads its settings through here so there is
exactly one place that knows where things live.
"""
from __future__ import annotations
import json, os
from pathlib import Path

# Project root = the directory that contains this package.
ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    # --- the local model (llama-server, OpenAI-compatible endpoint) ---
    "llm_url":         "http://localhost:8090/v1/chat/completions",  # loom's OWN server — see serve.sh
    "llm_model":       "local",
    "api_key":         "sk-local",
    "max_tokens":      700,
    "temperature":     0.85,
    "request_timeout": 180,

    # optional 2nd model — a separate obedient "archivist" for consolidation (which
    # wants clean JSON, unlike a wild uncensored narrator). Blank → reuse the narrator.
    "consolidate_llm_url": "",
    "consolidate_model":   "",
    "consolidate_api_key": "",         # a separate key for the archivist endpoint (falls back to api_key)
    "imagine_on_consolidate": False,   # opt-in: dream new threads at the end of consolidation

    # --- embeddings are OPTIONAL; lexical retrieval is the zero-dep default ---
    "use_embeddings":  False,
    "embed_url":       "http://localhost:8090/v1/embeddings",
    "embed_model":     "local",

    # --- retrieval / prompt shaping ---
    "retrieve_k":       6,    # canon nodes pulled in to ground a turn
    "recent_turns":     8,    # transcript lines kept for immediate continuity
    "tension_baseline": 0.15, # a campaign's resting dramatic tension (cozy 0.05 … grim 0.35)
    "tension_decay":    0.7,  # how slowly tension returns to baseline after a climax
    "mechanics":        False, # opt-in dice: uncertain actions decided by an impartial d20
    "depth":            0.0,   # the realness dial: 0 = mirror (referee off) … 1 = other (strict spine)
    "sleep_beats":      4,     # world-time that passes per 'sleep' pass, scaled by depth (0 at depth 0)
    "sleep_moves":      2,     # how many characters take a step toward their want per sleep (depth-scaled)
    "world_rounds":     False, # the toggle: run + SHOW a world round during play (off → sleep carries it)
    "world_cadence":    3,      # when the toggle is on, the world takes a round every N player turns

    # --- which campaign is live ---
    "campaign":        "example",
    "campaigns_dir":   "campaigns",

    # --- the narrator's voice (system-prompt seed; overridable per campaign) ---
    "narrator_voice": (
        "You are the narrator and game master of an ongoing story. "
        "You describe the world, voice its characters, and respond to the player. "
        "Stay in fiction. Treat the CANON below as the established truth of this "
        "world and never contradict it. Be vivid but concise.\n\n"
        "Follow the player's lead. Let quiet scenes stay quiet — a calm moment, rest, "
        "or reflection does not need a threat, a twist, a stranger, or a sudden noise. "
        "Do NOT manufacture conflict, danger, or drama to keep things interesting. "
        "Introduce complications only when the scene has genuinely stalled or when the "
        "player reaches for them. React to what the player actually does; never escalate "
        "on their behalf. Trust silence and small moments."
    ),
}


def load(path: str | os.PathLike | None = None) -> dict:
    """Load config.json merged over DEFAULTS. Missing file → pure defaults."""
    cfg = dict(DEFAULTS)
    p = Path(path) if path else ROOT / "config.json"
    if p.exists():
        try:
            loaded = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            raise RuntimeError(f"could not parse {p}: {e}")
        if not isinstance(loaded, dict):
            raise RuntimeError(f"{p} must be a JSON object")
        cfg.update(loaded)
    return cfg


def save(updates: dict, path=None) -> dict:
    """Merge `updates` into config.json (creating it) and return the merged config."""
    p = Path(path) if path else ROOT / "config.json"
    current = {}
    if p.exists():
        try:
            current = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            current = {}
    current.update(updates)
    p.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    return current


def valid_campaign_name(name) -> bool:
    """A campaign name that cannot escape the campaigns dir OR crash the filesystem — the single
    guard every create/switch entry point (CLI `new`, web /api/new + /api/use) must pass a name
    through before it becomes a path. Rejects traversal, path separators, NUL/control characters
    (an embedded-null ValueError on mkdir), and dot/space-only names that resolve to no real subdir."""
    name = str(name or "")
    if not name or any(c in name for c in "/\\") or ".." in name:
        return False
    if any(ord(c) < 32 for c in name):            # NUL / control chars → mkdir ValueError
        return False
    return name.strip(". ") != ""                 # ".", " ", "…" resolve to the campaigns dir itself


def campaign_dir(cfg: dict) -> Path:
    base = ROOT / cfg["campaigns_dir"]
    name = str(cfg["campaign"])
    if (base / name).resolve() != base.resolve() and base.resolve() not in (base / name).resolve().parents:
        raise ValueError(f"unsafe campaign name (escapes the campaigns dir): {name!r}")
    return base / name

def transcript_path(cfg: dict) -> Path:
    return campaign_dir(cfg) / "transcript.jsonl"

def world_dir(cfg: dict) -> Path:
    return campaign_dir(cfg) / "world"

def state_path(cfg: dict) -> Path:
    return campaign_dir(cfg) / "state.json"
