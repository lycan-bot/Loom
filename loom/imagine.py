"""loom.imagine — the imagination organ: INVENT candidate threads by recombining two
canon entities into a dramatic question the world could support but hasn't yet
established.

The generative complement to consolidation (which *extracts* threads from what was
played); this *dreams* them from the canon itself. Everything here is SEALED as
'imagined' and propose-only — it never writes to the plan. A candidate must pass the
gate (grounded in real canon, well-formed, novel vs what already exists) and then be
operator-blessed, at which point it sheds the imagined seal by becoming a real dormant
thread — the same diode as Primarch's dream→forge bridge (dream_recombination +
split_rail).
"""
from __future__ import annotations
import json
import random
import re
from . import canon, threads, llm

_JSON_RE = re.compile(r"\{[\s\S]*\}")

_PROMPT = """You are the dreaming imagination of a story world. Two things that exist in it:

A) {a}:
{a_body}

B) {b}:
{b_body}

Invent ONE hidden connection or dramatic question linking A and B — something NOT yet
established, but that this world could plausibly support and that would deepen it. Do not
contradict what is written above. Respond with ONE json object:
{{"question": "the dramatic question", "entities": ["{a}", "{b}"], "seed": "a subtle detail to foreshadow it", "payoff": "what following it might reveal"}}
"""


def _tokens(s):
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


def _too_similar(question, existing_questions, thresh=0.5) -> bool:
    q = _tokens(question)
    if not q:
        return True
    for e in existing_questions:
        et = _tokens(e)
        if et and len(q & et) / len(q | et) >= thresh:      # Jaccard overlap
            return True
    return False


def _pick_pair(nodes, rng):
    """Two canon nodes, preferring a pair NOT already linked — a novel juxtaposition."""
    if len(nodes) < 2:
        return None

    def links_of(n):
        return {l.split("|")[0].strip() for l in n["links"]}

    for _ in range(8):
        a, b = rng.sample(nodes, 2)
        if b["name"] not in links_of(a) and a["name"] not in links_of(b):
            return a, b
    return tuple(rng.sample(nodes, 2))


def imagine_one(world, cfg, existing_threads=None, rng=None):
    """Dream ONE candidate thread by recombining two canon entities. Returns a Thread with
    status 'imagined' (propose-only) if it passes the gate, else None."""
    rng = rng or random.Random()
    nodes = canon.load_all(world)
    names = {n["name"] for n in nodes}
    pair = _pick_pair(nodes, rng)
    if not pair:
        return None
    a, b = pair
    prompt = _PROMPT.format(a=a["name"], a_body=a["body"][:500],
                            b=b["name"], b_body=b["body"][:500])
    try:
        raw = llm.complete(prompt, cfg, max_tokens=400, temperature=1.0,
                           response_format=llm.schema_format("dream", {
                               "type": "object", "properties": {
                                   "question": {"type": "string"},
                                   "entities": {"type": "array", "items": {"type": "string"}},
                                   "seed": {"type": "string"}, "payoff": {"type": "string"}}}))
        data = json.loads(_JSON_RE.search(raw).group(0))
    except Exception:
        return None
    q = (data.get("question") or "").strip()
    ents = [e for e in (data.get("entities") or []) if e in names]    # keep only REAL canon
    # the gate: grounded (≥2 real entities), well-formed (a real question), novel
    existing_q = [t.question for t in (existing_threads or [])]
    if not q or len(ents) < 2 or _too_similar(q, existing_q):
        return None
    return threads.Thread(id=threads.make_id(q), question=q, kind="question",
                          status="imagined", entities=ents,
                          seed=(data.get("seed") or "").strip(),
                          payoff=(data.get("payoff") or "").strip())


def propose(world, threads_path, cfg, n=3, rng=None):
    """Dream up to `n` gate-passing candidates. Propose-only — writes nothing. Dedups
    against existing threads and each other."""
    rng = rng or random.Random()
    existing = threads.load(threads_path)
    seen = {t.id for t in existing}
    out = []
    for _ in range(n * 3):                       # a few tries per wanted candidate
        if len(out) >= n:
            break
        cand = imagine_one(world, cfg, existing + out, rng)
        if cand and cand.id not in seen:
            seen.add(cand.id)
            out.append(cand)
    return out


def bless(threads_path, candidates, approve=lambda *a: True):
    """Admit blessed candidates into the plan — shedding the 'imagined' seal by becoming
    real dormant threads."""
    th = threads.load(threads_path)
    by_id = {t.id for t in th}
    added = []
    for c in candidates:
        if c.id in by_id:
            continue
        if approve("imagined", c.question, c):
            th.append(threads.Thread(id=c.id, question=c.question, kind="question",
                                     status="dormant", entities=c.entities,
                                     seed=c.seed, payoff=c.payoff))   # seal shed → dormant
            by_id.add(c.id)
            added.append(c.question)
    if added:
        threads.save(threads_path, th)
    return added
