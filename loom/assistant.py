"""loom.assistant — Orbit: an out-of-character game-master console.

A NON-DIEGETIC side-channel that lives OUTSIDE the seal. It answers meta/OOC questions about the
world and the rules, and helps craft the world — but it is NOT a second narrator. Nothing it says
enters the transcript or canon, and every world-change it suggests is a PROPOSAL the player applies
through the SAME gated endpoints the author UI uses (the consolidation diode, in miniature): the
assistant proposes, the player's click disposes.

It reads canon + open threads + settings to ground its answers. Its actions are normalized to a tiny
safe vocabulary (create a node / add a thread / change depth+mechanics) — anything else the model
emits is dropped here, so a garbled or over-reaching reply can't do anything on its own.
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from . import llm, canon, threads

_JSON_RE = re.compile(r"\{[\s\S]*\}")
_KINDS = ("character", "place", "faction", "event", "lore")

_SYSTEM = """You are Orbit, an OUT-OF-CHARACTER assistant for a solo storytelling game (loom). You help \
the player understand and shape their world. You are NOT the narrator and you never speak in-story or \
advance the plot.

You can:
- Answer questions about the world, grounded strictly in the CANON below — if something isn't in the \
canon, say so plainly; do NOT invent it as fact. You may then OFFER to create it as a proposal.
- Answer questions about how the game works, from the RULES below.
- Propose changes: a new/edited canon node, a new story thread, or a settings change.

Every world-change is a PROPOSAL the player must approve — you never apply anything yourself, and you \
never write narration.

Respond with ONE json object and nothing else:
{
  "reply": "your conversational, out-of-character answer to the player (plain text)",
  "actions": [
    {"type": "create_node", "name": "...", "kind": "character|place|faction|event|lore", "body": "a short description", "fields": {"role": "...", "wants": "...", "genre": "...", "tone": "..."}},
    {"type": "add_thread", "question": "an open dramatic question", "seed": "a detail to foreshadow", "payoff": "what answering it looks like"},
    {"type": "set_config", "depth": 0.5, "mechanics": true}
  ]
}
Include ONLY actions the player actually asked for. A pure question → "actions": []. Keep "reply" short."""

_RULES = """loom is a solo story game. The player acts; a sealed narrator responds from the world's \
established canon (never from raw improv). Degrees of freedom (modes): 'power fantasy' = depth 0, the \
world agrees; 'writing a story' = depth ~0.5; 'real campaign' = depth ~1, the world resists, with \
optional dice (mechanics). THREADS are the open dramatic questions the story pulls toward. \
CONSOLIDATION folds a played session into canon. The world can move on its own (sleep / world rounds). \
REPUTATION tracks how factions and people regard the player."""


def _canon_digest(world: Path, limit: int = 2600) -> str:
    parts = []
    for n in canon.load_all(world):
        kind = n["frontmatter"].get("kind", "lore")
        parts.append(f"[[{n['name']}]] ({kind}): {n['body'][:160].strip()}")
    return "\n".join(parts)[:limit] or "(the world is empty — nothing has been established yet)"


def _threads_digest(spath: Path) -> str:
    ts = [t for t in threads.load(Path(spath).parent / "threads.json") if t.status != "resolved"]
    return "\n".join(f"- {t.question}" for t in ts) or "(no open threads yet)"


def _clean_action(a: dict):
    """Normalize one proposed action to the safe vocabulary — or drop it. The player still approves
    each; this is the structural belt so a malformed/over-reaching action can't reach an endpoint."""
    if not isinstance(a, dict):
        return None
    t = a.get("type")
    if t == "create_node":
        name = str(a.get("name", "")).strip()
        if not name:
            return None
        kind = a.get("kind") if a.get("kind") in _KINDS else "lore"
        rf = a.get("fields")
        fields = ({str(k): str(v).strip() for k, v in rf.items()
                   if isinstance(v, (str, int, float)) and str(v).strip()} if isinstance(rf, dict) else {})
        return {"type": "create_node", "name": name, "kind": kind,
                "body": str(a.get("body", "")).strip(), "fields": fields}
    if t == "add_thread":
        q = str(a.get("question", "")).strip()
        if not q:
            return None
        return {"type": "add_thread", "question": q,
                "seed": str(a.get("seed", "")).strip(), "payoff": str(a.get("payoff", "")).strip()}
    if t == "set_config":
        out = {"type": "set_config"}           # ONLY depth + mechanics — never the safety/seal knobs
        if "depth" in a:
            try:
                out["depth"] = max(0.0, min(1.0, float(a["depth"])))
            except (TypeError, ValueError):
                pass
        if "mechanics" in a:
            out["mechanics"] = bool(a["mechanics"])
        return out if len(out) > 1 else None
    return None


def _parse(raw: str) -> dict:
    m = _JSON_RE.search(raw or "")
    try:
        data = json.loads(m.group(0)) if m else {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    reply = data.get("reply")
    reply = reply.strip() if isinstance(reply, str) and reply.strip() else (raw or "").strip()[:800]
    raw_actions = data.get("actions")
    actions = []
    for a in (raw_actions if isinstance(raw_actions, list) else []):
        act = _clean_action(a)
        if act:
            actions.append(act)
    return {"reply": reply, "actions": actions}


def ask(cfg: dict, world: Path, spath: Path, history, message: str) -> dict:
    """One OOC turn. `history` = prior {role, text} OOC messages (kept OUT of the sealed transcript).
    Returns {reply, actions}; actions are PROPOSALS the caller applies via the gated endpoints."""
    system = (_SYSTEM + "\n\n=== RULES ===\n" + _RULES +
              "\n\n=== CANON (the world's established truth) ===\n" + _canon_digest(world) +
              "\n\n=== OPEN THREADS ===\n" + _threads_digest(spath) +
              f"\n\n=== CURRENT SETTINGS ===\ndepth={cfg.get('depth', 0)}, mechanics={bool(cfg.get('mechanics'))}")
    msgs = [{"role": "system", "content": system}]
    for h in (history if isinstance(history, list) else [])[-8:]:
        if not isinstance(h, dict):
            continue
        role = "assistant" if h.get("role") == "assistant" else "user"
        msgs.append({"role": role, "content": str(h.get("text", ""))})
    msgs.append({"role": "user", "content": str(message)})

    acfg = dict(cfg)                            # prefer the archivist endpoint (reliable JSON) if set
    for dst, src in (("llm_url", "consolidate_llm_url"), ("llm_model", "consolidate_model"),
                     ("api_key", "consolidate_api_key")):
        if cfg.get(src):
            acfg[dst] = cfg[src]
    raw = llm.chat(msgs, acfg, max_tokens=700, temperature=0.4,
                   response_format={"type": "json_object"})
    return _parse(raw)
