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
# Deliberately UNAMBIGUOUS: bare filler verbs ("i said", "recall", "mentioned", "told me", "the words")
# were dropped because they fire on ordinary forward play ("I said a prayer and step outside") AND the
# filler token then pollutes the BM25 query, injecting an irrelevant old turn as 'quote FAITHFULLY'.
_REF_CUES = (
    "what did", "what exactly did", "what had", "what were", "what was said", "what was her",
    "what was his", "what was their", "what happened when", "who said", "you said", "she said",
    "he said", "they said", "did she say", "did he say", "did they say", "said about",
    "remember when", "remember what", "do you remember", "last time", "when did", "when was",
    "back then", "earlier you", "you told", "we discussed", "we talked about", "remind me", "how did",
)


def recall_query(text: str):
    """If the player is asking about the past, return the SEARCH query with the cue phrase stripped
    (the cue is a trigger, not part of what to search for — leaving 'said'/'did' in pollutes BM25 and
    up-ranks any dialogue-heavy turn). Returns None when no cue fires, so recall costs nothing on an
    ordinary forward action."""
    low = (text or "").lower()
    fired = [c for c in _REF_CUES if c in low]
    if not fired:
        return None
    for c in fired:
        low = low.replace(c, " ")
    return low.strip() or (text or "").strip()          # if stripping emptied it, fall back to raw


def references_past(text: str) -> bool:
    """True when the player's input asks about the established past (so recall should run)."""
    return recall_query(text) is not None


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
