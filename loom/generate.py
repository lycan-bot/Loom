"""loom.generate — roll a fresh world (and its first faces) from nothing or a seed.

The model invents a WORLD CARD — name, premise, age, tech, magic, peoples, tone — and a starting
CAST of character cards that fit it. Written into a campaign as canon (a lore 'world' node + one
character node each), operator-confirmed.

This is the CREATIVE front door, not the self-loop: a high-temperature roll is exactly what's wanted
here, and nothing is re-read as inferred ground truth — the operator adopts what it makes. Model
output is grammar-valid JSON but still sanitized (a bad field is dropped, never crashed on).
"""
from __future__ import annotations
import json
import re
from . import llm, canon, consolidate

_JSON_RE = re.compile(r"\{[\s\S]*\}")

_WORLD_KEYS = ("name", "premise", "genre", "age", "tech", "magic", "peoples", "tone", "body")
_CHAR_KEYS = ("name", "role", "description", "voice", "wants", "bound", "location")
_WORLD_SCHEMA = {"type": "object", "properties": {k: {"type": "string"} for k in _WORLD_KEYS}}
_CHAR_SCHEMA = {"type": "object", "properties": {k: {"type": "string"} for k in _CHAR_KEYS}}

_WORLD_PROMPT = """Invent a fresh, vivid setting for a story world%s. SURPRISE me — do not default to
generic high-fantasy unless the roll genuinely lands there; reach for the unexpected. Decide concretely:
- name: the world's name
- premise: a one-sentence hook
- genre: the story's genre / register (cosmic horror, noir, high fantasy, space opera, cyberpunk, mythic, cozy slice-of-life, …)
- age: the era (bronze-age, feudal, age-of-sail, industrial, modern, far-future, post-collapse, …)
- tech: the technology level and its flavor
- magic: "none", or how magic works if it exists
- peoples: "human only", or the peoples that walk it — humanoid AND/OR nonhumanoid, named
- tone: the mood (cozy, grim, wondrous, noir, mythic, …)
- body: two or three sentences of grounding setting prose

Respond with ONE json object having exactly those keys.
"""

_CHAR_PROMPT = """Here is a story world:
%s
%s
Invent ONE character who lives in it, fitting its age, tech, magic, and peoples. Decide: name, role
(who/what they are, short), description (a sentence or two), voice (how they speak), wants (what they
are after), bound (a vow/fear/debt that holds them back), location (where they are). Respond with ONE
json object with exactly those keys.
"""


def _s(x) -> str:
    """A model scalar coerced to a clean string — a bad type becomes '', never a crash."""
    return x.strip() if isinstance(x, str) else ""


def _ask(cfg, prompt, max_tokens, temperature, schema=None) -> dict:
    """One JSON round-trip, FAIL-SOFT. With a schema it uses the ENFORCED json_schema grammar (valid
    JSON from any model); the lenient repair + degrade-to-{} stays as a belt for truncation etc."""
    rf = llm.schema_format("card", schema) if schema else {"type": "json_object"}
    raw = llm.complete(prompt, cfg, max_tokens=max_tokens, temperature=temperature, response_format=rf)
    m = _JSON_RE.search(raw)
    if not m:
        return {}
    try:
        data = consolidate._loads_lenient(m.group(0))     # repairs a truncated object
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}                                          # unrepairable garble → empty, retry


def world(cfg, seed: str = "") -> dict:
    """Roll a world card (dict of _WORLD_KEYS). Writes nothing. A high-temp creative roll."""
    hint = f" from this seed — {seed}" if seed else ""
    data = _ask(cfg, _WORLD_PROMPT % hint, 500, 1.0, _WORLD_SCHEMA)
    if not isinstance(data, dict):
        data = {}
    return {k: _s(data.get(k)) for k in _WORLD_KEYS}


def cast(cfg, world_card: dict, n: int = 3) -> list:
    """Roll n character cards that fit a world (list of dicts). Writes nothing.

    ONE character per call: a small object parses reliably from a wild model, where a big
    all-at-once cast JSON keeps malforming. Each call is told who's already been made, for variety."""
    desc = "\n".join(f"{k}: {v}" for k, v in world_card.items() if v)
    out, seen = [], set()
    for _ in range(max(1, int(n))):
        avoid = (f"(Already in the story, do not reuse: {', '.join(sorted(seen))}.)\n" if seen else "")
        card = {k: _s(v) for k, v in _ask(cfg, _CHAR_PROMPT % (desc, avoid), 400, 0.9, _CHAR_SCHEMA).items()}
        card = {k: card.get(k, "") for k in _CHAR_KEYS}
        if card["name"] and card["name"].lower() not in seen:
            seen.add(card["name"].lower())
            out.append(card)
    return out


def write_world(world_dir, world_card: dict, characters: list) -> None:
    """Write a generated world + cast into a campaign's canon (a lore node + character nodes)."""
    wc = world_card
    body = "\n\n".join(p for p in (wc.get("premise", ""), wc.get("body", "")) if p) or "A new world."
    canon.write_node(world_dir, wc.get("name") or "The World", body, {
        "kind": "lore", "setting": "true",         # the world card — the register the narrator writes in
        **{k: wc[k] for k in ("genre", "age", "tech", "magic", "peoples", "tone") if wc.get(k)}})
    for c in characters:
        fm = {"kind": "character"}
        for k in ("role", "voice", "wants", "bound", "location"):
            if c.get(k):
                fm[k] = c[k]
        canon.write_node(world_dir, c["name"], c.get("description") or c["name"], fm)
