"""loom.extract — per-turn entity extraction + the confabulation signal (storyteller-memory Phase 3).

For each turn, deterministically records which canon entities appeared (name-match) and which
capitalized name-candidates in the NARRATOR's prose matched NO canon entity. A candidate that RECURS
across turns without ever being in canon is the signal: the narrator keeps invoking someone the
world-bible never established — either a continuity leak to catch, or an emergent character worth
adding to canon. Deterministic (regex + name-match), no model call.

On-demand from the transcript (like recall) — a turn taken back with undo is transparently gone, no
stale index to reconcile. Later phases (consistency, timeline) build on this per-turn presence map.
"""
from __future__ import annotations
import re
from . import canon, player, recall

# titles/honorifics are not distinctive name tokens ('Professor Finch' is keyed on 'finch')
_TITLES = {"the", "a", "an", "inquisitor", "professor", "headmaster", "instructor", "master",
           "mistress", "lord", "lady", "sir", "dame", "captain", "doctor", "dr", "mr", "mrs", "ms"}

# common capitalized-at-sentence-start / pronoun / filler words that are NOT names (noise floor)
_NAME_STOP = {
    "i", "the", "a", "an", "he", "she", "it", "they", "you", "we", "his", "her", "hers", "their",
    "them", "my", "your", "our", "this", "that", "these", "those", "but", "and", "so", "then", "as",
    "when", "where", "while", "with", "for", "from", "yet", "still", "now", "here", "there", "if",
    "or", "nor", "because", "though", "although", "perhaps", "maybe", "yes", "no", "not", "of", "to",
    "in", "on", "at", "by", "up", "down", "out", "over", "under", "after", "before", "one", "two",
    "three", "first", "last", "next", "some", "any", "all", "every", "each", "only", "even", "just",
    "like", "her", "his", "its", "how", "why", "what", "who", "would", "could", "should", "will",
    "may", "might", "must", "do", "does", "did", "is", "are", "was", "were", "be", "been", "being",
}

# a proper-noun phrase, but only MID-SENTENCE (preceded by a lowercase letter or a comma). Sentence-
# INITIAL capitals ('Together', 'Around', 'Then', 'You') are the dominant false positives, and a real
# name recurs mid-sentence somewhere anyway — so this trades a little recall for a lot of precision.
_MID_NAME_RE = re.compile(r"[a-z,]\s+([A-Z][A-Za-z]+(?:'[a-z]+)?(?:\s+(?:of|the|[A-Z][A-Za-z]+(?:'[a-z]+)?)*)*)")
_APOS = re.compile(r"'[a-z]+\b")                    # strip possessive/contraction suffix ('s, 're, 'll, 'm…)


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", str(s).lower()).strip()


def _tokens(s) -> set:
    return {t for t in re.findall(r"[\w']+", (s or "").lower()) if t not in _TITLES and len(t) > 2}


def _canon_entities(world):
    """(canonical name, distinctive-token-set) for every named canon node."""
    out = []
    for n in canon.load_all(world):
        toks = _tokens(n["name"])
        if toks:
            out.append((n["name"], toks))
    return out


def present(text, world) -> list:
    """Canon entity names whose distinctive token appears in `text`."""
    toks = set(re.findall(r"[\w']+", (text or "").lower()))
    return [name for name, nt in _canon_entities(world) if nt & toks]


def candidates(text) -> list:
    """Mid-sentence capitalized proper-noun phrases in `text` (potential named entities). Possessive/
    contraction suffixes are stripped ('Wren's'→'Wren', 'You're'→'You'), then anything that reduces to
    stopwords is dropped — so contractions collapse to pronouns and fall out."""
    out = []
    for m in _MID_NAME_RE.finditer(text or ""):
        phrase = _APOS.sub("", m.group(1)).strip()
        toks = _tokens(phrase)                          # drops titles + <=2 chars
        if not toks or all(t in _NAME_STOP for t in toks):
            continue
        out.append(phrase)
    return out


def per_turn(tpath, world) -> list:
    """[{turn, present, candidates}] per turn-pair — who/what was in each turn (present from the whole
    pair; name-candidates from the NARRATOR's prose, where confabulation happens)."""
    ents = _canon_entities(world)
    out = []
    for p in recall.pairs(tpath):
        toks = set(re.findall(r"[\w']+", p["text"].lower()))
        out.append({"turn": p["turn"],
                    "present": [name for name, nt in ents if nt & toks],
                    "candidates": candidates(p["narrator"])})
    return out


def emergent(tpath, world, min_turns: int = 2) -> list:
    """Capitalized names the narrator used across >= min_turns turns that match NO canon entity and
    aren't the player — suspected confabulations or emergent entities worth reviewing. Recurrence is
    the precision filter: a one-off sentence-start capital doesn't repeat; a real invented name does."""
    canon_toks = set()
    for _n, t in _canon_entities(world):
        canon_toks |= t
    pc = player.get(world)
    player_toks = _tokens(pc.get("name", "")) if pc else set()
    seen = {}
    for row in per_turn(tpath, world):
        for cand in row["candidates"]:
            ctoks = _tokens(cand)
            if not ctoks or (ctoks & canon_toks) or (ctoks & player_toks):
                continue                                  # empty / already-canon / the player → not a miss
            key = _norm(cand)
            if key:
                seen.setdefault(key, {"name": cand, "turns": set()})["turns"].add(row["turn"])
    return sorted(({"name": e["name"], "count": len(e["turns"]), "turns": sorted(e["turns"])}
                   for e in seen.values() if len(e["turns"]) >= min_turns),
                  key=lambda x: -x["count"])
