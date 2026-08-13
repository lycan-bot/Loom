"""loom.recall — episodic memory: search the story's OWN past and quote it back verbatim.

Scene memory holds a rolling 'story so far' gist; canon holds curated truth. Neither can answer
"what EXACTLY did the innkeeper say three sessions ago?" — the literal words are only in the
transcript, unsearchable. recall indexes the transcript as turn-pairs (a player action + the
narrator's reply) and retrieves the ones a later turn references, so the narrator can quote the
real line instead of confabulating a plausible-but-different one.

Built ON-DEMAND from the transcript (no separate index file): a turn taken back with undo/retry is
transparently gone from recall too, with no stale-entry bookkeeping. Lexical (BM25) for now, reusing
retrieve.py's ranker; a vector cache rides on top once embeddings land (storyteller-memory Phase 0).
"""
from __future__ import annotations
from . import transcript, retrieve

# retrospective cues — the player is asking about the ESTABLISHED past, not narrating a new action.
# Deliberately specific: recall only fires on a clear back-reference, so it's not a per-turn cost.
_REF_CUES = (
    "what did", "what exactly", "what had", "what were", "what was said", "who said", "you said",
    "she said", "he said", "they said", "we said", "i said", "did she say", "did he say",
    "mentioned", "told me", "told you", "told us", "said about", "said to", "remember when",
    "remember what", "recall", "last time", "when did", "when was", "back then", "earlier you",
    "you told", "already said", "we discussed", "we talked about", "the words", "verbatim",
)


def references_past(text: str) -> bool:
    """True when the player's input asks about the established past (so recall should run). A keyword
    prefilter — a clear back-reference cue — so recall costs nothing on an ordinary forward action."""
    low = (text or "").lower()
    return any(c in low for c in _REF_CUES)


def pairs(tpath) -> list[dict]:
    """The transcript as turn-pairs: each player line joined to the narrator reply that answered it,
    numbered in order. The in-progress turn (a player line with no reply yet) is naturally excluded."""
    out, turn, pending = [], 0, None
    for e in transcript.read_all(tpath):
        role, text = e.get("role"), e.get("text", "")
        if role == "player":
            pending = text
        elif role == "narrator" and pending is not None:
            turn += 1
            out.append({"turn": turn, "player": pending, "narrator": text,
                        "text": f"{pending}\n{text}"})
            pending = None
    return out


def search(tpath, query: str, k: int = 2) -> list[dict]:
    """The k turn-pairs most relevant to `query` (BM25 over player+narrator text). Only genuine
    matches (score>0) — an unmatched query returns [], so recall never injects noise."""
    prs = pairs(tpath)
    if not prs or not (query or "").strip():
        return []
    docs = [{"name": str(p["turn"]), "body": p["text"]} for p in prs]
    by_turn = {str(p["turn"]): p for p in prs}
    out = []
    for name, score in retrieve._bm25(query, docs)[:k]:
        if score > 0 and name in by_turn:
            out.append({**by_turn[name], "score": score})
    return out
