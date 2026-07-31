"""loom.consolidate — the diode: the ONLY path from transcript → canon.

Between sessions, the model reads the raw play log and PROPOSES canon/state
updates. Nothing is written until the operator blesses it. This is what keeps the
narrator grounded in curated truth instead of drifting on its own improv (the
write→re-read collapse the Sigilus floor exists to prevent, in miniature).
"""
from __future__ import annotations
import json, re
from pathlib import Path
from . import llm, canon, state, threads

_JSON_RE = re.compile(r"\{[\s\S]*\}")


def _loads_lenient(text: str):
    """json.loads, but if the object was truncated (e.g. hit max_tokens), repair it by
    closing any open string and balancing braces/brackets. The grammar guarantees valid
    JSON *syntax*; this guards against a valid-but-cut-off object."""
    try:
        return json.loads(text)
    except Exception:
        pass
    stack, in_str, esc = [], False, False
    closer = {"{": "}", "[": "]"}
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in closer:
            stack.append(closer[ch])
        elif ch in ("}", "]") and stack and stack[-1] == ch:
            stack.pop()
    repaired = text + ('"' if in_str else "") + "".join(reversed(stack))
    return json.loads(repaired)

_PROMPT = """You are the archivist of an ongoing story. Read the play log and propose durable \
updates to the world. Extract only what is now ESTABLISHED; do not invent beyond the log.

Also tend the STORY THREADS — the open dramatic questions and pending tensions that give the \
story momentum. Currently open threads:
%s

Respond with ONE json object:
{
  "nodes":   [{"name": "...", "body": "markdown, may use [[links]]", "kind": "character|place|faction|event|lore"}],
  "state":   {"key": "value"},
  "threads_new":      [{"question": "a NEW open dramatic question this session RAISED", "entities": ["canon names it involves"], "seed": "a subtle detail to foreshadow it later", "payoff": "what answering it might look like"}],
  "threads_resolved": ["<id of an open thread the session ANSWERED, if any>"],
  "character_updates": [{"name": "an existing character", "disposition": "how they now feel toward the player, ONLY if it clearly shifted this session"}],
  "summary": "one sentence on what changed"
}
Only open a thread for a genuine NEW dramatic question the session actually raised; only resolve \
one it truly closed. If none, use empty lists.

PLAY LOG:
%s
"""


def propose(cfg: dict, session_lines: list[dict], existing_threads=None) -> dict:
    """Ask the model for proposed canon/state/thread changes. Returns a dict; writes nothing.

    `existing_threads` (Thread objects) are shown to the archivist so it can avoid opening
    duplicates and can name a thread it has answered. Uses the optional archivist endpoint
    (consolidate_llm_url / consolidate_model) — consolidation wants reliable JSON, which a
    wild uncensored narrator may botch.
    """
    ccfg = dict(cfg)
    if cfg.get("consolidate_llm_url"):
        ccfg["llm_url"] = cfg["consolidate_llm_url"]
    if cfg.get("consolidate_model"):
        ccfg["llm_model"] = cfg["consolidate_model"]
    open_str = "\n".join(f"- [{t.id}] {t.question}" for t in (existing_threads or [])
                         if getattr(t, "status", "") != "resolved") or "(none yet)"
    log_text = "\n".join(f"{e.get('role', '?')}: {e.get('text', '')}" for e in session_lines)
    raw = llm.complete(_PROMPT % (open_str, log_text), ccfg, max_tokens=1400, temperature=0.2,
                       response_format={"type": "json_object"})   # grammar-guaranteed valid JSON
    m = _JSON_RE.search(raw)
    if not m:
        raise ValueError(f"no JSON object in consolidation output: {raw[:200]}")
    data = _loads_lenient(m.group(0))
    for key, default in (("nodes", []), ("state", {}), ("threads_new", []),
                         ("threads_resolved", []), ("character_updates", []), ("summary", "")):
        data.setdefault(key, default)
    return data


def apply(proposals: dict, world: Path, state_path: Path, approve) -> dict:
    """Write approved proposals to canon + state. `approve(kind, name, payload) -> bool`
    is called for EVERY change; nothing is written unless it returns True. This callback
    is the diode — the operator's hand between improv and canon.
    """
    written: dict[str, list] = {"nodes": [], "state": [], "threads": [], "resolved": [], "dispositions": []}
    for node in proposals.get("nodes", []):
        name = node.get("name")
        body = (node.get("body") or "").strip()
        if not name:
            continue
        if approve("node", name, node):
            existing = canon.read_node(world, name)
            if existing is None:                                  # create
                canon.write_node(world, name, body, {"kind": node.get("kind", "lore")})
                written["nodes"].append(name)
            elif body and body not in existing["body"]:           # update: append novel content,
                merged = existing["body"].rstrip() + "\n\n" + body   # preserving frontmatter (drives!)
                canon.write_node(world, name, merged, existing["frontmatter"])
                written["nodes"].append(name)
            # else: node exists and nothing new to add — leave it untouched
    st = state.load(state_path)
    changed = False
    for key, val in (proposals.get("state") or {}).items():
        if approve("state", key, val):
            st[key] = val
            written["state"].append(key)
            changed = True
    if changed:
        state.save(state_path, st)

    # story threads: open new dramatic questions, resolve answered ones (the diode gates both)
    thpath = Path(state_path).parent / "threads.json"
    th = threads.load(thpath)
    by_id = {t.id: t for t in th}
    th_changed = False
    for nt in proposals.get("threads_new", []):
        q = (nt.get("question") or "").strip()
        if not q:
            continue
        tid = threads.make_id(q)
        if tid in by_id:                                 # dedup against existing
            continue
        if approve("thread", q, nt):
            new = threads.Thread(id=tid, question=q, kind="question", status="dormant",
                                 entities=nt.get("entities") or [], seed=nt.get("seed") or "",
                                 payoff=nt.get("payoff") or "")
            th.append(new)
            by_id[tid] = new
            written["threads"].append(q)
            th_changed = True
    for rid in proposals.get("threads_resolved", []):
        t = by_id.get(rid)
        if t and t.status != "resolved" and approve("resolve", rid, t.question):
            t.status = "resolved"
            written["resolved"].append(rid)
            th_changed = True
    if th_changed:
        threads.save(thpath, th)

    # a character's disposition toward the player, updated in place (relationship growth)
    for cu in proposals.get("character_updates", []):
        name = cu.get("name")
        disp = (cu.get("disposition") or "").strip()
        if not name or not disp:
            continue
        node = canon.read_node(world, name)
        if node is None or node["frontmatter"].get("kind") != "character":
            continue
        if approve("disposition", name, disp):
            fm = dict(node["frontmatter"])
            fm["disposition"] = disp
            canon.write_node(world, name, node["body"], fm)
            written["dispositions"].append(name)
    return written
