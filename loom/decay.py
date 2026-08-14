"""loom.decay — forgetting: a salience × recency re-ranker over retrieval.

Retrieval ranks by relevance alone, so canon from eighty turns ago competes on equal footing with the
live scene, and a large campaign dumps a flat all-time slice into every beat. Decay adds FORGETTING:
a node's retrieval rank is modulated by how ALIVE it is right now —

  • RECENCY — how recently it was named in play (an exponential half-life over transcript position), and
  • SALIENCE — how structurally central it is (threads it sits in, graph degree, an agenda, reputation).

Hot, central nodes surface; cold, peripheral ones fade from the ambient context. It never BURIES a
genuine match — the boost floors at DECAY_FLOOR, so a strong lexical hit on a cold node still wins, and
direct recall is preserved. And it writes nothing: recomputed per call from the transcript + canon, so
an undo that truncates the transcript re-derives the right weights (undo-transparent).

Deterministic signals only — transcript positions, the canon graph, threads, reputation — NEVER the
model's own output re-read (the self-propagating collapse the whole system is built to refuse).
"""
from __future__ import annotations
import re
from pathlib import Path
from . import canon, transcript, salience

DECAY_FLOOR = 0.5          # a cold node's relevance is at worst halved, never zeroed → direct recall survives
_HALF_LIFE = 12            # transcript entries until a mention's recency weight halves (~6 turn-pairs)
_UNSEEN = 0.15             # base recency for a node never named in play (dormant canon, not dead)
_W_RECENCY = 0.6           # forgetting is primarily recency; salience is what RESISTS it
_W_SALIENCE = 0.4


def _recency(tpath, names) -> dict:
    """name -> 0.5 ** (entries-since-last-mention / half-life), in (0, 1]. Never-named → _UNSEEN.
    Word-boundary match, case-insensitive; a name that is a regex metacharacter degrades to substring."""
    entries = transcript.read_all(tpath) if tpath else []
    texts = [str(e.get("text", "")).lower() for e in entries]
    n = len(texts)
    out = {}
    for name in names:
        low = (name or "").lower().strip()
        if not low:
            out[name] = _UNSEEN
            continue
        try:
            pat = re.compile(r"\b" + re.escape(low) + r"\b")
            hit = lambda t: bool(pat.search(t))
        except re.error:
            hit = lambda t, s=low: s in t
        last = None
        for i in range(n - 1, -1, -1):
            if hit(texts[i]):
                last = i
                break
        out[name] = _UNSEEN if last is None else 0.5 ** (((n - 1) - last) / _HALF_LIFE)
    return out


def prominence(world, tpath, spath, nodes=None) -> dict:
    """name -> aliveness in [0, 1] = w_r·recency + w_s·salience_norm. Deterministic, per-call.
    `nodes` may be passed to avoid re-loading canon the caller already has."""
    if nodes is None:
        nodes = canon.load_all(world)
    names = [d["name"] for d in nodes]
    rec = _recency(tpath, names)
    sal = salience.scores(world, spath) if spath is not None else {}
    smax = max(sal.values()) if sal else 0
    out = {}
    for name in names:
        s = (sal.get(name, 0) / smax) if smax else 0.0
        out[name] = min(1.0, _W_RECENCY * rec.get(name, _UNSEEN) + _W_SALIENCE * s)
    return out


def boost(prom: float) -> float:
    """Map an aliveness in [0,1] to a relevance multiplier in [DECAY_FLOOR, 1]."""
    return DECAY_FLOOR + (1.0 - DECAY_FLOOR) * max(0.0, min(1.0, prom))


def rerank(ranked, prom):
    """Re-order (name, score) pairs by score × boost(prominence). ORDER only — the scores passed
    through are the original relevance, so the zero/nonzero flag downstream relies on is untouched.
    Stable within equal effective scores (Python sort), so ties keep their relevance order."""
    return sorted(ranked, key=lambda ns: ns[1] * boost(prom.get(ns[0], 0.0)), reverse=True)


def by_prominence(names, prom):
    """Names ordered most-alive first — for the ungrounded fallback (no lexical match), so a turn with
    nothing relevant still grounds on the LIVE world, not an arbitrary alphabetical slice."""
    return sorted(names, key=lambda nm: prom.get(nm, 0.0), reverse=True)
