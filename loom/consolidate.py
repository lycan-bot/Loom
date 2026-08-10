"""loom.consolidate — the diode: the ONLY path from transcript → canon.

Between sessions, the model reads the raw play log and PROPOSES canon/state
updates. Nothing is written until the operator blesses it. This is what keeps the
narrator grounded in curated truth instead of drifting on its own improv (the
write→re-read collapse the Sigilus floor exists to prevent, in miniature).
"""
from __future__ import annotations
import difflib
import json
import re
from pathlib import Path
from . import llm, canon, state, threads, reputation, transcript

_JSON_RE = re.compile(r"\{[\s\S]*\}")

# generic words that must NOT anchor a fuzzy merge (many colleges, many orders) — a match needs a
# DISTINCTIVE shared token (a proper-noun-ish word), so "The Silent Order" won't fold into "The Orders"
_GENERIC = {"the", "a", "an", "of", "college", "order", "orders", "guild", "hall", "tower", "house",
            "school", "academy", "city", "town", "statutes", "council", "company", "band", "keep"}


def _norm(s) -> str:
    s = re.sub(r"^\s*the\s+", "", str(s).strip().lower())
    return re.sub(r"[^a-z0-9 ]+", "", s).strip()


def _resolve_existing(world, name: str):
    """The existing canon node a proposed name refers to — exact, or a CONFIDENT near-miss the
    archivist invented ('The Inquisitor' → 'Inquisitor Vael') — else None (a genuinely new entity).
    Conservative: when unsure it returns None (create a new node), never a wrong merge, so new
    content is never silently swallowed into the wrong node."""
    exact = canon.read_node(world, name)
    if exact is not None:
        return exact["name"]
    n = _norm(name)
    if not n:
        return None
    fuzzy = None
    for node in canon.load_all(world):
        ex = node["name"]
        e = _norm(ex)
        if not e:
            continue
        if n == e:
            return ex                                        # identical after stripping the/punct/case
        nt, et = set(n.split()), set(e.split())
        sig = {w for w in (nt & et) if len(w) > 3 and w not in _GENERIC}
        if sig and (nt <= et or et <= nt):                   # one name's tokens ⊆ the other, sharing a
            return ex                                        # distinctive word → the same entity
        if difflib.SequenceMatcher(None, n, e).ratio() >= 0.9:
            fuzzy = ex                                        # very close spelling (typo/variant)
    return fuzzy


def _dicts(x):
    """Model output is grammar-valid JSON but NOT shape-checked; keep only the dict elements
    of a list so a botched container type is skipped, never crashed on."""
    return [e for e in x if isinstance(e, dict)] if isinstance(x, list) else []


def _s(x, default=""):
    """A model scalar coerced to a clean string — a non-str field becomes the default, never a
    crash (`.strip()` / slug on a list or number is the whole class of bug this closes)."""
    return x if isinstance(x, str) else default


_PLACEHOLDER_KEYS = {"key", "value", "fact", "fact name", "fact_name", "factname"}


def _real_key(k) -> bool:
    """Reject the schema's example placeholder echoed back verbatim as a literal fact — a wild model
    copies '{"key": "value"}' or a '<...>' template straight into its output. A real fact key is a
    concrete name, never the template, so those are dropped before they pollute state."""
    s = str(k).strip().lower()
    return bool(s) and s not in _PLACEHOLDER_KEYS and "<" not in s and ">" not in s


def _normalize(proposals: dict) -> dict:
    """Coerce grammar-valid-but-unshaped model output into clean, typed structures so the write
    loop can never crash on a bad type or leave a partial commit. Every malformed field is
    dropped here, up front — nothing downstream ever sees a non-string where a string is due."""
    def _named(d):
        n = d.get("name")
        return n if isinstance(n, str) and n.strip() else None

    nodes = []
    for n in _dicts(proposals.get("nodes")):
        name = _named(n)
        if not name:
            continue
        rf = n.get("fields")
        fields = {k: v for k, v in rf.items() if isinstance(v, str) and v} if isinstance(rf, dict) else {}
        nodes.append({"name": name, "body": _s(n.get("body")).strip(),
                      "kind": _s(n.get("kind"), "lore"), "fields": fields})

    threads_new = []
    for t in _dicts(proposals.get("threads_new")):
        q = _s(t.get("question")).strip()
        if not q:
            continue
        re_ = t.get("entities")
        ents = ([e for e in re_ if isinstance(e, str)] if isinstance(re_, list)
                else [re_] if isinstance(re_, str) and re_ else [])
        threads_new.append({"question": q, "entities": ents,
                            "seed": _s(t.get("seed")), "payoff": _s(t.get("payoff"))})

    updates = []
    for c in _dicts(proposals.get("character_updates")):
        name = _named(c)
        disp, loc = _s(c.get("disposition")).strip(), _s(c.get("location")).strip()
        if name and (disp or loc):
            updates.append({"name": name, "disposition": disp, "location": loc})

    rep = []
    for r in _dicts(proposals.get("reputation")):
        who = _s(r.get("who")).strip()
        if not who:
            continue
        try:
            delta = int(r.get("delta"))
        except (TypeError, ValueError):
            continue
        if delta == 0:                                    # a no-op delta isn't a reputation change
            continue
        rep.append({"who": who, "delta": max(-3, min(3, delta)), "because": _s(r.get("because")).strip()})

    resolved_raw = proposals.get("threads_resolved")
    return {
        "nodes": nodes,
        "state": {str(k): v for k, v in proposals["state"].items() if _real_key(k)} if isinstance(proposals.get("state"), dict) else {},
        "threads_new": threads_new,
        "threads_resolved": [r for r in resolved_raw if isinstance(r, str)] if isinstance(resolved_raw, list) else [],
        "character_updates": updates,
        "reputation": rep,
    }


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

EXISTING CANON NODES — when an update concerns one of these, use its EXACT name below so it MERGES \
into that node instead of forking a near-duplicate. Only invent a NEW name for a genuinely new entity:
%s

Respond with ONE json object:
{
  "nodes":   [{"name": "...", "body": "markdown, may use [[links]]", "kind": "character|place|faction|event|lore", "fields": {"role": "(character only) who/what they are, short", "met": "(character only) when + where they were first met"}}],
  "state":   {"<a short snake_case fact name>": "<what is now true>"},
  "threads_new":      [{"question": "a NEW open dramatic question this session RAISED", "entities": ["canon names it involves"], "seed": "a subtle detail to foreshadow it later", "payoff": "what answering it might look like"}],
  "threads_resolved": ["<id of an open thread the session ANSWERED, if any>"],
  "character_updates": [{"name": "an existing character", "disposition": "how they now feel toward the player, ONLY if it clearly shifted this session", "location": "the place they are now, ONLY if they moved this session"}],
  "reputation": [{"who": "a faction, group, or notable person", "delta": -1, "because": "the DEED this session that moved their regard for the player (a small integer -3..3; negative = worse)"}],
  "summary": "one sentence on what changed"
}
Only open a thread for a genuine NEW dramatic question the session actually raised; only resolve \
one it truly closed. If none, use empty lists.

PLAY LOG:
%s
"""


# the server enforces json_schema as a token-level grammar (unlike json_object, a soft hint a wild RP
# model ignores) — so consolidation gets valid JSON from ANY model. Permissive by design: no `required`
# (the model omits empty sections), open `state`/`fields` maps, so the grammar shapes without starving.
_SCHEMA = {
    "type": "object",
    "properties": {
        "nodes": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "body": {"type": "string"},
            "kind": {"type": "string"}, "fields": {"type": "object"}}}},
        "state": {"type": "object"},
        "threads_new": {"type": "array", "items": {"type": "object", "properties": {
            "question": {"type": "string"}, "entities": {"type": "array", "items": {"type": "string"}},
            "seed": {"type": "string"}, "payoff": {"type": "string"}}}},
        "threads_resolved": {"type": "array", "items": {"type": "string"}},
        "character_updates": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "disposition": {"type": "string"}, "location": {"type": "string"}}}},
        "reputation": {"type": "array", "items": {"type": "object", "properties": {
            "who": {"type": "string"}, "delta": {"type": "integer"}, "because": {"type": "string"}}}},
        "summary": {"type": "string"},
    },
}


def propose(cfg: dict, session_lines: list[dict], existing_threads=None, world=None) -> dict:
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
    if cfg.get("consolidate_api_key"):
        ccfg["api_key"] = cfg["consolidate_api_key"]
    open_str = "\n".join(f"- [{t.id}] {t.question}" for t in (existing_threads or [])
                         if getattr(t, "status", "") != "resolved") or "(none yet)"
    roster_str = ("\n".join(f"- {n['name']} ({n['frontmatter'].get('kind', 'lore')})"
                            for n in canon.load_all(world)) or "(none yet)") if world is not None else "(none yet)"
    log_text = "\n".join(f"{e.get('role', '?')}: {e.get('text', '')}" for e in session_lines)
    raw = llm.complete(_PROMPT % (open_str, roster_str, log_text), ccfg, max_tokens=1400, temperature=0.2,
                       response_format={"type": "json_schema",             # token-level grammar (enforced)
                                        "json_schema": {"name": "consolidation", "schema": _SCHEMA}})
    m = _JSON_RE.search(raw)
    if not m:
        raise ValueError(f"no JSON object in consolidation output: {raw[:200]}")
    data = _loads_lenient(m.group(0))
    for key, default in (("nodes", []), ("state", {}), ("threads_new", []),
                         ("threads_resolved", []), ("character_updates", []), ("reputation", []), ("summary", "")):
        data.setdefault(key, default)
    return data


def apply(proposals: dict, world: Path, state_path: Path, approve) -> dict:
    """Write approved proposals to canon + state. `approve(kind, name, payload) -> bool` is
    called for EVERY change; nothing is written unless it returns True — the diode, the operator's
    hand between improv and canon.

    Model output is grammar-valid JSON but NOT shape-checked, so it is normalized to clean typed
    structures first (`_normalize`): a mistyped field is dropped, never crashed on mid-write, so a
    garbled reply can't leave half-written canon (propose→bless atomicity).
    """
    p = _normalize(proposals)
    written: dict[str, list] = {"nodes": [], "state": [], "threads": [], "resolved": [],
                                "dispositions": [], "locations": [], "reputation": []}
    for node in p["nodes"]:
        name, body, fields = node["name"], node["body"], node["fields"]
        if not approve("node", name, node):
            continue
        resolved = _resolve_existing(world, name)                # a near-miss the archivist invented
        existing = canon.read_node(world, resolved) if resolved else None
        if existing is None:                                      # genuinely new → create it
            canon.write_node(world, name, body, {"kind": node["kind"], **fields})
            written["nodes"].append(name)
            continue
        name = existing["name"]                                   # merge under the CANONICAL name, not the dup
        fm = dict(existing["frontmatter"])                        # preserve drives, voice, etc.
        new_body, touched = existing["body"], False
        if body and body not in existing["body"]:                 # append novel content
            new_body = existing["body"].rstrip() + "\n\n" + body
            touched = True
        for k, v in fields.items():                               # merge card fields
            if fm.get(k) != v:
                fm[k] = v
                touched = True
        if touched:
            canon.write_node(world, name, new_body, fm)
            written["nodes"].append(name)
    st = state.load(state_path)
    changed = False
    for key, val in p["state"].items():
        if approve("state", key, val):
            st[key] = val
            written["state"].append(key)
            changed = True
    # reputation: shift each blessed standing (the diode gates each deed) and log the deed that moved
    # it — stored in the same state under _rep so it commits atomically with the rest of the state
    rep = reputation.load(st)
    for r in p["reputation"]:
        if approve("reputation", r["who"], r):
            reputation.apply_delta(rep, r["who"], r["delta"], r["because"])
            written["reputation"].append(r["who"])
            changed = True
    if rep:
        st["_rep"] = rep
    if changed:
        state.save(state_path, st)

    # story threads: open new dramatic questions, resolve answered ones (the diode gates both)
    thpath = Path(state_path).parent / "threads.json"
    th = threads.load(thpath)
    by_id = {t.id: t for t in th}
    th_changed = False
    for nt in p["threads_new"]:
        q = nt["question"]
        tid = threads.make_id(q)
        if tid in by_id:                                 # dedup against existing
            continue
        if approve("thread", q, nt):
            new = threads.Thread(id=tid, question=q, kind="question", status="dormant",
                                 entities=nt["entities"], seed=nt["seed"], payoff=nt["payoff"])
            th.append(new)
            by_id[tid] = new
            written["threads"].append(q)
            th_changed = True
    for rid in p["threads_resolved"]:
        t = by_id.get(rid)
        if t and t.status != "resolved" and approve("resolve", rid, t.question):
            t.status = "resolved"
            written["resolved"].append(rid)
            th_changed = True
    if th_changed:
        threads.save(thpath, th)

    # a character's disposition toward the player, updated in place (relationship growth)
    for cu in p["character_updates"]:
        name = cu["name"]
        node = canon.read_node(world, name)
        if node is None or node["frontmatter"].get("kind") != "character":
            continue
        fm = dict(node["frontmatter"])
        touched = False
        # disposition (a feeling) and location (a MOVE) are DISTINCT changes — gate them separately
        # so a relocation is disclosed and independently refusable, not smuggled in under a feeling
        if cu["disposition"] and approve("disposition", name, cu["disposition"]):
            fm["disposition"] = cu["disposition"]
            written["dispositions"].append(name)
            touched = True
        if cu["location"] and approve("location", name, cu["location"]):
            fm["location"] = cu["location"]              # NPCs relocate over play → world-round groups shift
            written["locations"].append(name)
            touched = True
        if touched:
            canon.write_node(world, name, node["body"], fm)
    return written


# --- incremental consolidation: only fold in the turns SINCE the last pass, so the prompt stays
# bounded no matter how long the campaign runs (the fix for the long-session consolidate timeout) ---

def unconsolidated(tpath, spath):
    """(new transcript entries since the last consolidation, current total count). The watermark is
    `_consolidated` in state — how many transcript entries have already been folded in."""
    lines = transcript.read_all(tpath)
    wm = int(state.load(spath).get("_consolidated", 0) or 0)
    return lines[wm:], len(lines)


def mark_consolidated(spath, total: int) -> None:
    """Advance the watermark past everything consolidated so far (blessed or declined — either way
    those turns won't be re-proposed; they still live in the transcript + scene memory)."""
    state.set_fact(spath, "_consolidated", int(total))


def queue_pending(spath, nodes) -> None:
    """Park proposed canon-node updates in `_pending_canon` for the operator to bless later — the
    diode's holding pen. Auto consolidation applies the low-risk structured continuity itself but
    PARKS canon here instead of dropping it (the original bug: advancing the watermark past
    un-blessed nodes lost them forever, since those turns are never re-proposed). Dedup by name,
    latest proposal wins."""
    nodes = [n for n in (nodes or []) if isinstance(n, dict) and n.get("name")]
    if not nodes:
        return
    st = state.load(spath)
    q = st.get("_pending_canon")
    by_name = {n["name"]: n for n in (q if isinstance(q, list) else [])
               if isinstance(n, dict) and n.get("name")}
    for n in nodes:
        by_name[n["name"]] = n
    st["_pending_canon"] = list(by_name.values())
    state.save(spath, st)


def pending(spath):
    """The queued canon-node proposals awaiting the operator's bless (from auto consolidation)."""
    q = state.load(spath).get("_pending_canon")
    return [n for n in q if isinstance(n, dict) and n.get("name")] if isinstance(q, list) else []


def apply_pending(world: Path, spath, approve=None) -> dict:
    """Bless the queued canon into the world-bible, then empty the pen. `approve(kind, name, payload)`
    gates each node (default: bless all); a review pass is final — declined nodes are dropped from the
    queue too, so it never re-nags. Reuses the exact merge/dedup path a manual consolidate takes."""
    pend = pending(spath)
    if not pend:
        return {"nodes": []}
    if approve is None:
        approve = lambda *a: True
    written = apply({"nodes": pend, "state": {}, "threads_new": [], "threads_resolved": [],
                     "character_updates": [], "reputation": []}, world, spath,
                    lambda kind, name, p: kind == "node" and approve(kind, name, p))
    st = state.load(spath)
    st.pop("_pending_canon", None)
    state.save(spath, st)
    return written


def auto(cfg, tpath, world, spath, apply_canon: bool = False):
    """Automated consolidation: propose from the NEW turns and fold in the result. Returns a report.
    The DIODE: by default only the low-risk structured continuity (state facts, reputation, character
    disposition/location, thread ripening) is auto-applied; new/edited CANON NODES and thread
    RESOLUTION stay gated unless `apply_canon` is set — auto-authoring the world-bible unattended is
    the write→re-read collapse this wall exists to prevent. Gated canon is PARKED in `_pending_canon`
    (queue_pending), never dropped, so a later bless can still land it even though the watermark moved."""
    new_lines, total = unconsolidated(tpath, spath)
    if len([e for e in new_lines if e.get("role") == "player"]) < 1:
        return {"applied": {}, "pending_nodes": [], "summary": "", "new": len(new_lines)}
    existing = threads.load(spath.parent / "threads.json")
    try:
        proposals = propose(cfg, new_lines, existing, world=world)
    except Exception as e:
        return {"error": str(e), "new": len(new_lines)}

    # gate: canon nodes + thread-resolution only apply when apply_canon is explicitly chosen
    def approve(kind, name, payload):
        if kind in ("node", "resolve") and not apply_canon:
            return False
        return True

    written = apply(proposals, world, spath, approve)
    mark_consolidated(spath, total)
    pending_names = []
    if not apply_canon:
        norm_nodes = _normalize(proposals)["nodes"]
        if norm_nodes:
            queue_pending(spath, norm_nodes)          # PARK canon for bless — never drop it past the watermark
            pending_names = [n["name"] for n in norm_nodes]
    return {"applied": written, "pending_nodes": pending_names,
            "summary": proposals.get("summary", ""), "new": len(new_lines)}
