"""loom.retrieve — grounding retrieval over CANON (with optional embeddings).

Lexical BM25-lite is the zero-dependency default; if config.use_embeddings and
the model server exposes /v1/embeddings, cosine results are fused in via RRF.
Cosine + reciprocal-rank-fusion are lifted from the Primarch search module.
"""
from __future__ import annotations
import math, re
from pathlib import Path
from . import canon, llm, decay

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


def retrieve(query: str, world: Path, cfg: dict, k: int | None = None,
             tpath: Path | None = None, spath: Path | None = None) -> list[dict]:
    """Top-k canon nodes most relevant to `query`. When cfg['salience_decay'] is on AND the transcript
    + state paths are supplied, results are re-ranked by FORGETTING (recency × salience, see loom.decay)
    so the live scene surfaces over stale canon — a modulation that never buries a genuine match. With
    the flag off or the paths absent, behaviour is byte-identical to pure relevance."""
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

    # FORGETTING: re-rank by aliveness (recency × salience), preserving the relevance flag. Gated +
    # needs the transcript/state; off or absent → the pure-relevance order above stands unchanged.
    decay_on = bool(cfg.get("salience_decay")) and tpath is not None and spath is not None
    prom = decay.prominence(world, tpath, spath, nodes=docs) if decay_on else None
    if decay_on:
        ranked = decay.rerank(ranked, prom)

    out = []
    for name, score in ranked[:k]:
        d = by_name.get(name)
        if d:
            out.append({**d, "score": score if name in relevant else 0.0})
    if out:
        return out
    # never leave a turn ungrounded: fall back to canon — most-ALIVE first when decay is on, else the
    # legacy alphabetical slice.
    if decay_on:
        order = decay.by_prominence([d["name"] for d in docs], prom)[:k]
        return [{**by_name[nm], "score": 0.0} for nm in order]
    return [{**d, "score": 0.0} for d in docs[:k]]


def grounded_context(world: Path, cfg: dict, query: str, anchors=(), k: int | None = None,
                     body_chars: int = 200, tpath: Path | None = None, spath: Path | None = None) -> str:
    """A canon context block GROUNDED in retrieval for `query`, not an arbitrary alphabetical slice.
    The world-round / sleep confabulation ('Fáelán's testimony') came from the model free-associating
    over a fixed 1500-char dump of ALL canon; this instead grounds the beat in what's actually
    relevant to its actors. `anchors` (names) are always included first — the characters the round is
    ABOUT — then the highest-scored genuine matches, capped at k. '' when the world has no canon."""
    k = k or cfg.get("retrieve_k", 8)
    by_name = {d["name"]: d for d in canon.load_all(world)}
    if not by_name:
        return ""
    picked, seen = [], set()
    for name in anchors:                                  # the actors are always in-context
        d = by_name.get(name)
        if d and name not in seen:
            seen.add(name)
            picked.append(d)
    for d in retrieve(query, world, cfg, k=k, tpath=tpath, spath=spath):   # + genuine matches, decay-ordered
        if d["name"] not in seen and d.get("score", 0.0) > 0:
            seen.add(d["name"])
            picked.append(d)
    return "\n".join(f"{d['name']}: {(d.get('body') or '')[:body_chars]}" for d in picked[:k])
