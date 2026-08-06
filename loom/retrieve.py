"""loom.retrieve — grounding retrieval over CANON (with optional embeddings).

Lexical BM25-lite is the zero-dependency default; if config.use_embeddings and
the model server exposes /v1/embeddings, cosine results are fused in via RRF.
Cosine + reciprocal-rank-fusion are lifted from the Primarch search module.
"""
from __future__ import annotations
import math, re
from pathlib import Path
from . import canon, llm

_TOK_RE = re.compile(r"\w+", re.UNICODE)
_COS_FLOOR = 0.5          # cosine below this is fusion noise, not a genuine semantic match


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOK_RE.findall(text or "")]


# --- lexical BM25-lite over the (small) canon set ---
def _bm25(query: str, docs: list[dict], k1: float = 1.5, b: float = 0.75) -> list[tuple[str, float]]:
    q = set(_tokens(query))
    if not q or not docs:
        return []
    toks = [_tokens(d["name"] + "\n" + d["body"]) for d in docs]
    lengths = [len(t) for t in toks]
    avgdl = (sum(lengths) / len(lengths)) or 1.0
    N = len(docs)
    df: dict[str, int] = {}
    for t in toks:
        for w in set(t):
            if w in q:
                df[w] = df.get(w, 0) + 1
    scores = []
    for i, doc_toks in enumerate(toks):
        tf: dict[str, int] = {}
        for w in doc_toks:
            if w in q:
                tf[w] = tf.get(w, 0) + 1
        s = 0.0
        for w, f in tf.items():
            idf = math.log(1 + (N - df[w] + 0.5) / (df[w] + 0.5))
            s += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * lengths[i] / avgdl))
        if s > 0:
            scores.append((docs[i]["name"], s))
    return sorted(scores, key=lambda x: x[1], reverse=True)


# --- vendored from primarch/modules/search.py ---
def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _rrf(lists: list[list[tuple[str, float]]], k: int = 60) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranked in lists:
        for rank, (name, _) in enumerate(ranked):
            scores[name] = scores.get(name, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def retrieve(query: str, world: Path, cfg: dict, k: int | None = None) -> list[dict]:
    """Top-k canon nodes most relevant to `query`."""
    k = k or cfg["retrieve_k"]
    docs = canon.load_all(world)
    if not docs:
        return []
    by_name = {d["name"]: d for d in docs}
    lexical = _bm25(query, docs)

    ranked = lexical
    # a node is genuinely "near" only if it had a real signal — a lexical hit or a strong cosine.
    # RRF gives EVERY fused node a positive score, which would defeat narrate's `score>0` proximity
    # gate (ripening threads on vague input); so relevance is tracked separately from fusion rank.
    relevant = {name for name, s in lexical if s > 0}
    if cfg.get("use_embeddings"):
        vecs = llm.embed([query] + [d["body"] for d in docs], cfg)
        if vecs and len(vecs) == len(docs) + 1:      # shape guard: a short/reordered embed
            qv, dvs = vecs[0], vecs[1:]               # response must fall back to lexical, not crash
            cos = [(docs[i]["name"], _cosine(qv, dvs[i])) for i in range(len(docs))]
            vec_ranked = sorted(cos, key=lambda x: x[1], reverse=True)
            ranked = _rrf([lexical, vec_ranked])
            relevant |= {name for name, c in cos if c >= _COS_FLOOR}

    out = []
    for name, score in ranked[:k]:
        d = by_name.get(name)
        if d:
            out.append({**d, "score": score if name in relevant else 0.0})
    # never leave a turn ungrounded: if lexical found nothing, fall back to all nodes
    return out or [{**d, "score": 0.0} for d in docs[:k]]
