"""loom.consolidate — the diode: the ONLY path from transcript → canon.

Between sessions, the model reads the raw play log and PROPOSES canon/state
updates. Nothing is written until the operator blesses it. This is what keeps the
narrator grounded in curated truth instead of drifting on its own improv (the
write→re-read collapse the Sigilus floor exists to prevent, in miniature).
"""
from __future__ import annotations
import json, re
from pathlib import Path
from . import llm, canon, state

_JSON_RE = re.compile(r"\{[\s\S]*\}")

_PROMPT = """You are the archivist of an ongoing story. Read the play log below and \
propose durable updates to the world's canon and continuity state. Extract only \
what is now ESTABLISHED — new characters/places/factions/events, and changes to \
existing ones. Do not invent beyond the log. Respond with ONE json object:
{
  "nodes":  [{"name": "...", "body": "markdown, may use [[links]]", "kind": "character|place|faction|event|lore"}],
  "state":  {"key": "value"},
  "summary": "one sentence on what changed"
}

PLAY LOG:
%s
"""


def propose(cfg: dict, session_lines: list[dict]) -> dict:
    """Ask the model for proposed canon/state changes. Returns a dict; writes nothing."""
    log_text = "\n".join(f"{e.get('role', '?')}: {e.get('text', '')}" for e in session_lines)
    raw = llm.complete(_PROMPT % log_text, cfg, max_tokens=1200, temperature=0.2)
    m = _JSON_RE.search(raw)
    if not m:
        raise ValueError(f"no JSON object in consolidation output: {raw[:200]}")
    data = json.loads(m.group(0))
    data.setdefault("nodes", [])
    data.setdefault("state", {})
    data.setdefault("summary", "")
    return data


def apply(proposals: dict, world: Path, state_path: Path, approve) -> dict:
    """Write approved proposals to canon + state. `approve(kind, name, payload) -> bool`
    is called for EVERY change; nothing is written unless it returns True. This callback
    is the diode — the operator's hand between improv and canon.
    """
    written: dict[str, list] = {"nodes": [], "state": []}
    for node in proposals.get("nodes", []):
        name = node.get("name")
        if not name:
            continue
        if approve("node", name, node):
            canon.write_node(world, name, node.get("body", ""),
                             {"kind": node.get("kind", "lore")})
            written["nodes"].append(name)
    st = state.load(state_path)
    changed = False
    for key, val in (proposals.get("state") or {}).items():
        if approve("state", key, val):
            st[key] = val
            written["state"].append(key)
            changed = True
    if changed:
        state.save(state_path, st)
    return written
