"""loom.decay — forgetting: a salience × recency re-ranker over retrieval.

Retrieval ranks by relevance alone, so canon from eighty turns ago competes on equal footing with the
live scene, and a large campaign dumps a flat all-time slice into every beat. Decay adds FORGETTING:
a node's retrieval rank is modulated by how ALIVE it is right now —

  • RECENCY — how recently it was named in play (an exponential half-life over transcript position), and
  • SALIENCE — how structurally central it is (threads it sits in, graph degree, an agenda, reputation).

Hot, central nodes surface; cold, peripheral ones fade from the ambient context. It never BURIES the
strongest genuine match — that match always LEADS (a relevance-ranked carve-out), and a genuine match
never ranks below a non-match; decay only reorders which comparably-relevant nodes fill the tail. And
it writes nothing: recomputed per call from the transcript + canon, so an undo that truncates the
transcript re-derives the right weights (undo-transparent).

Deterministic signals only — the canon graph, threads, reputation, and the PLAYER's own input as the
recency anchor. The narrator's prose counts for recency too but is DISCOUNTED and capped below a player
mention, so the ranking can't self-amplify off the model's own output (the self-propagating collapse
the whole system refuses): only the human's engagement lifts a node to full heat.
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
_WINDOW = _HALF_LIFE * 12  # a mention older than this weighs < _UNSEEN anyway → bound the scan (perf: the
                           # cost is O(names × window), NOT O(names × whole-transcript) for the campaign's life
_NARRATOR_DISCOUNT = 0.5   # narrator prose lifts recency at most this far — only a PLAYER mention reaches 1.0


def _matcher(name):
    """A compiled matcher for a name, word-bounded only where the name's own edge is a word char (so
    'c++' / 'The Salt & Anchor' still match; re.escape never raises, so there is no substring fallback)."""
    low = (name or "").lower().strip()
    if not low:
        return None
    lb = r"\b" if (low[0].isalnum() or low[0] == "_") else ""
    rb = r"\b" if (low[-1].isalnum() or low[-1] == "_") else ""
    return re.compile(lb + re.escape(low) + rb)


def _recency(tpath, names) -> dict:
    """name -> recency in [_UNSEEN, 1]. A node the PLAYER named decays 0.5 ** (entries-since / half-life)
    at full weight; a node only the NARRATOR named is capped at _NARRATOR_DISCOUNT (so model prose can't
    ratchet a node to dominance without the human engaging it). Never-named → _UNSEEN. Scan is bounded to
    the last _WINDOW entries — older mentions weigh below the floor anyway."""
    entries = transcript.read_all(tpath) if tpath else []
    n = len(entries)
    lo = max(0, n - _WINDOW)
    texts = [str(entries[i].get("text", "")).lower() for i in range(lo, n)]   # windowed, absolute i = lo + j
    roles = [entries[i].get("role") for i in range(lo, n)]
    out = {}
    for name in names:
        pat = _matcher(name)
        if pat is None:
            out[name] = _UNSEEN
            continue
        last_player = last_any = None
        for j in range(len(texts) - 1, -1, -1):          # newest → oldest within the window
            if pat.search(texts[j]):
                if last_any is None:
                    last_any = lo + j
                if roles[j] == "player" and last_player is None:
                    last_player = lo + j
                    break                                 # the human anchor found — no need to look older
        p_rec = 0.5 ** (((n - 1) - last_player) / _HALF_LIFE) if last_player is not None else 0.0
        a_rec = _NARRATOR_DISCOUNT * (0.5 ** (((n - 1) - last_any) / _HALF_LIFE)) if last_any is not None else 0.0
        out[name] = max(p_rec, a_rec, _UNSEEN)
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


def rerank(ranked, prom, relevant=None):
    """Re-order (name, score) pairs by score × boost(prominence), under two invariants the top-k cut
    and the ambient grounding depend on:
      1. a GENUINE match (name in `relevant`) never ranks below a non-match — decay reorders within the
         relevant set and within the rest, never across the boundary (so noise can't evict signal), and
      2. the STRONGEST genuine match (highest RAW relevance = what pure relevance would lead with) is
         pinned to the front — decay reorders the tail, it never buries the single best hit past ranked[:k].
    Scores pass through unchanged (the zero/nonzero relevance flag downstream relies on is intact). With
    `relevant` omitted every node is treated as relevant (pure reorder, for callers that don't gate)."""
    if relevant is None:
        relevant = {ns[0] for ns in ranked}

    def eff(ns):
        return ns[1] * boost(prom.get(ns[0], 0.0))

    rel = sorted((ns for ns in ranked if ns[0] in relevant), key=eff, reverse=True)
    non = sorted((ns for ns in ranked if ns[0] not in relevant), key=eff, reverse=True)
    if rel:
        top_raw = max(ns[1] for ns in rel)               # the strongest genuine match leads, whatever its
        lead = max((ns for ns in rel if ns[1] == top_raw), key=eff)   # aliveness — but a genuine TIE for the
        rel = [lead] + [ns for ns in rel if ns[0] != lead[0]]         # top breaks toward the live node
    return rel + non


def by_prominence(names, prom):
    """Names ordered most-alive first — for the ungrounded fallback (no lexical match), so a turn with
    nothing relevant still grounds on the LIVE world, not an arbitrary alphabetical slice."""
    return sorted(names, key=lambda nm: prom.get(nm, 0.0), reverse=True)
