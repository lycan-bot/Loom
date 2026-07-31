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

    # --- embeddings are OPTIONAL; lexical retrieval is the zero-dep default ---
    "use_embeddings":  False,
    "embed_url":       "http://localhost:8090/v1/embeddings",
    "embed_model":     "local",

    # --- retrieval / prompt shaping ---
    "retrieve_k":      6,     # canon nodes pulled in to ground a turn
    "recent_turns":    8,     # transcript lines kept for immediate continuity

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
            cfg.update(json.loads(p.read_text(encoding="utf-8")))
        except Exception as e:
            raise RuntimeError(f"could not parse {p}: {e}")
    return cfg


def campaign_dir(cfg: dict) -> Path:
    return ROOT / cfg["campaigns_dir"] / cfg["campaign"]

def transcript_path(cfg: dict) -> Path:
    return campaign_dir(cfg) / "transcript.jsonl"

def world_dir(cfg: dict) -> Path:
    return campaign_dir(cfg) / "world"

def state_path(cfg: dict) -> Path:
    return campaign_dir(cfg) / "state.json"
