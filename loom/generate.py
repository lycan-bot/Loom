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
from . import llm, canon

_JSON_RE = re.compile(r"\{[\s\S]*\}")

_WORLD_KEYS = ("name", "premise", "age", "tech", "magic", "peoples", "tone", "body")
_CHAR_KEYS = ("name", "role", "description", "voice", "wants", "bound", "location")

_WORLD_PROMPT = """Invent a fresh, vivid setting for a story world%s. SURPRISE me — do not default to
generic high-fantasy unless the roll genuinely lands there; reach for the unexpected. Decide concretely:
- name: the world's name
- premise: a one-sentence hook
- age: the era (bronze-age, feudal, age-of-sail, industrial, modern, far-future, post-collapse, …)
- tech: the technology level and its flavor
- magic: "none", or how magic works if it exists
- peoples: "human only", or the peoples that walk it — humanoid AND/OR nonhumanoid, named
- tone: the mood (cozy, grim, wondrous, noir, mythic, …)
- body: two or three sentences of grounding setting prose

Respond with ONE json object having exactly those keys.
"""

_CAST_PROMPT = """Here is a story world:
%s

Invent %d distinct CHARACTERS who live in it — each fitting its age, tech, magic, and peoples. For
each decide: name, role (who/what they are, short), description (a sentence or two), voice (how they
speak), wants (what they are after), bound (a vow/fear/debt that holds them back), location (where
they are). Make them varied, and give them wants that could bring them into each other's paths.
Respond with ONE json object: {"characters": [{"name","role","description","voice","wants","bound","location"}, …]}
"""


def _s(x) -> str:
    """A model scalar coerced to a clean string — a bad type becomes '', never a crash."""
    return x.strip() if isinstance(x, str) else ""


def _ask(cfg, prompt, max_tokens, temperature):
    raw = llm.complete(prompt, cfg, max_tokens=max_tokens, temperature=temperature,
                       response_format={"type": "json_object"})
    m = _JSON_RE.search(raw)
    return json.loads(m.group(0)) if m else {}


def world(cfg, seed: str = "") -> dict:
    """Roll a world card (dict of _WORLD_KEYS). Writes nothing. A high-temp creative roll."""
    hint = f" from this seed — {seed}" if seed else ""
    data = _ask(cfg, _WORLD_PROMPT % hint, 500, 1.0)
    if not isinstance(data, dict):
        data = {}
    return {k: _s(data.get(k)) for k in _WORLD_KEYS}


def cast(cfg, world_card: dict, n: int = 3) -> list:
    """Roll n character cards that fit a world (list of dicts). Writes nothing."""
    desc = "\n".join(f"{k}: {v}" for k, v in world_card.items() if v)
    data = _ask(cfg, _CAST_PROMPT % (desc, max(1, int(n))), 900, 0.9)
    chars = data.get("characters") if isinstance(data, dict) else None
    out = []
    for c in (chars if isinstance(chars, list) else []):
        if not isinstance(c, dict):
            continue
        card = {k: _s(c.get(k)) for k in _CHAR_KEYS}
        if card["name"]:
            out.append(card)
    return out


def write_world(world_dir, world_card: dict, characters: list) -> None:
    """Write a generated world + cast into a campaign's canon (a lore node + character nodes)."""
    wc = world_card
    body = "\n\n".join(p for p in (wc.get("premise", ""), wc.get("body", "")) if p) or "A new world."
    canon.write_node(world_dir, wc.get("name") or "The World", body, {
        "kind": "lore",
        **{k: wc[k] for k in ("age", "tech", "magic", "peoples", "tone") if wc.get(k)}})
    for c in characters:
        fm = {"kind": "character"}
        for k in ("role", "voice", "wants", "bound", "location"):
            if c.get(k):
                fm[k] = c[k]
        canon.write_node(world_dir, c["name"], c.get("description") or c["name"], fm)
