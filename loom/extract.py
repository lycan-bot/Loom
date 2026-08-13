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

# a common-English-word floor: a capitalized COMMON word (sentence-start 'Together'/'Then', a proper
# adjective 'English'/'Roman', a weekday/month) is not a name — real names aren't common words. This
# is what lets candidates() match a name ANYWHERE (incl. sentence start, where narrators introduce
# characters) without drowning in 'Then'/'You' noise — the recall my earlier mid-sentence-only regex
# threw away. A real name that's also a common word (Grace, Hope, Dawn) is the accepted rare miss.
_COMMON = frozenset("""
the a an and or but so yet for nor of to in on at by up down out off over under above below from with
without within into onto upon about across after before behind between beyond during through against
toward towards near far here there where when while why how what who whom whose which that this these
those it its it's he she they them we us you your yours his her hers their theirs my mine our ours me him
i as is are was were be been being am do does did done doing have has had having will would shall should
can could may might must not no yes maybe perhaps still now then once again ever never always often
sometimes soon later early late all any some none each every both few many much more most less least own
same other another such only just even also too very quite rather almost enough one two three four five
six seven eight nine ten first second third last next new old good bad great little big small long short
high low right left true false yes well oh ah hey ok okay please thanks thank sorry hello goodbye come
came go went get got give gave take took make made see saw look looked say said tell told ask asked
know knew think thought feel felt want wanted need needed find found keep kept hold held turn turned
move moved walk walked run ran stand stood sit sat wait waited stop stopped start started open close
english british american roman greek latin french german italian spanish russian chinese japanese indian
african european asian northern southern eastern western january february march april may june july august
september october november december monday tuesday wednesday thursday friday saturday sunday god lord lady
sir madam mister missus christmas easter today tonight tomorrow yesterday morning evening night day week
month year time way thing things something nothing anything everything someone anyone everyone nobody
together around let like listen however indeed whatever trust stay step face watch hurry hush behold
alas thus hence therefore moreover meanwhile suddenly finally eventually certainly surely truly honestly
frankly clearly obviously apparently seemingly instead otherwise anyway anyhow besides likewise similarly
consequently accordingly nevertheless nonetheless regardless whereas whenever wherever whoever whatever
whichever either neither whether unless until since though although despite whilst amid among beneath
beside throughout underneath alongside forward backward onward inward outward upward downward hmm ah oh
nay aye lo forth away back down along past round about speak remember forget continue
""".split())

# a name word: capitalized, with an optional internal/trailing apostrophe group ("O'Brien", "Wren's")
_WORD = r"[A-Z][a-zA-Z]*(?:'[a-zA-Z]+)?"
# a proper-noun PHRASE, anywhere in the text (not restricted to mid-sentence — the common-word floor is
# the precision mechanism now, so a name introduced at a sentence boundary is no longer invisible). Each
# step consumes a whole word, so there is no nested-quantifier backtracking.
_NAME_RE = re.compile(rf"{_WORD}(?:\s+(?:of\s+|the\s+|de\s+|van\s+|von\s+)?{_WORD})*")
_CONTRACTION = re.compile(r"'(?:s|re|ll|m|ve|d)$", re.I)   # possessive/contraction — NOT 't ('Don't' stays whole)


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
    """Capitalized proper-noun phrases anywhere in `text` (potential named entities). A phrase whose
    words are ALL common words is dropped (a sentence-start 'Then', a proper adjective 'English'); a
    trailing possessive/contraction is stripped ('Wren's'→'Wren', 'You're'→'You'→dropped as common)."""
    out = []
    for m in _NAME_RE.finditer(text or ""):
        phrase = _CONTRACTION.sub("", m.group(0)).strip()
        words = [w for w in phrase.split() if w]
        if words and not all(w.lower() in _COMMON for w in words):
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


def lower_vocab(tpath) -> set:
    """Tokens that appear as an ALL-LOWERCASE word somewhere in the story. A capitalized candidate whose
    every token shows up here is a common word (capitalized only at a sentence start — 'Together', and
    lowercase 'together' elsewhere), not a name (a proper noun is capitalized every time it appears).
    This is the word-list-free precision floor that separates real names from sentence-start noise."""
    vocab = set()
    for p in recall.pairs(tpath):
        vocab |= set(re.findall(r"\b[a-z][a-z']{2,}\b", p["text"]))
    return vocab


def emergent(tpath, world, min_turns: int = 2) -> list:
    """Capitalized names the narrator used across >= min_turns turns that name NO canon entity and
    aren't the player — suspected confabulations or emergent entities. Two precision filters, no word
    list: (1) every token appears lowercase elsewhere → a common word, dropped; (2) recurrence. A
    candidate is excluded as canon only when it NAMES a specific entity (token SUBSET: 'Finch' ⊆
    'Professor Ysolde Finch'), NOT when it merely shares one word ('Grand Vizier' survives 'The Grand
    Library')."""
    exclude = [t for _n, t in _canon_entities(world)]
    pc = player.get(world)
    if pc:
        pt = _tokens(pc.get("name", ""))
        if pt:
            exclude.append(pt)
    lower = lower_vocab(tpath)
    seen = {}
    for row in per_turn(tpath, world):
        for cand in row["candidates"]:
            ctoks = _tokens(cand)
            if not ctoks or all(t in lower for t in ctoks):
                continue                                  # empty / every token appears lowercase → common word
            if any(ctoks <= es for es in exclude):
                continue                                  # names a specific canon entity or the player
            key = _norm(cand)
            if key:
                seen.setdefault(key, {"name": cand, "turns": set()})["turns"].add(row["turn"])
    return sorted(({"name": e["name"], "count": len(e["turns"]), "turns": sorted(e["turns"])}
                   for e in seen.values() if len(e["turns"]) >= min_turns),
                  key=lambda x: -x["count"])
