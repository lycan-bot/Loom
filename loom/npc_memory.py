"""loom.npc_memory — a per-NPC READ-VIEW over the blessed episodic timeline (NPC-agency P1).

An NPC's memory is NOT a diary it writes — that would be a write→re-read collapse surface. It is a
FILTER over the shared, append-only episodic log: the beats where this NPC acted or was named. Two
provenance classes matter, and keeping them apart is the whole point:

  • BLESSED — source in {play (the consolidation of PLAYED turns, through the diode), sleep (an
    operator-blessed 'while you were away' recap)}: what actually, verifiably happened. GOAL-affecting
    reads see ONLY these.
  • IMPROV — source == 'world': a prior world-round beat, model-generated and never blessed. It may
    feed PROSE-CONTINUITY (so beats don't contradict each other turn-to-turn) but NEVER a goal
    decision — letting an NPC read its OWN improvised beat back as remembered truth, and reinforce a
    goal from it, is the idée-fixe loop the floor forbids.

Every recalled row keeps its `source` so a caller can label blessed-vs-improv in the prompt. Pure
read; writes nothing; recomputed per call from the timeline (undo-transparent, like all loom memory).
"""
from __future__ import annotations
import re
from . import episodic

_BLESSED = ("play", "sleep")            # provenance classes an NPC may treat as remembered TRUTH


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", str(s).lower()).strip()


def _acts(row, name_norm) -> bool:
    """Did this NPC act in / get named by this beat? Structured `who` is authoritative; a legacy row
    with no `who` falls back to a whole-word name match in the beat text (so pre-tag rows still recall)."""
    who = row.get("who")
    if isinstance(who, list):
        return any(_norm(w) == name_norm for w in who)
    return re.search(r"\b" + re.escape(name_norm) + r"\b", _norm(row.get("what"))) is not None


def _rank(rows, q, k):
    """Newest-k, or BM25-ranked when `q` is given — the shared read logic for recall()/shared()."""
    if not rows:
        return []
    if q:
        from . import retrieve
        docs = [{"name": str(i), "body": (str(e.get("what", "")) + " " + str(e.get("when", ""))).strip()}
                for i, e in enumerate(rows)]
        by_i = {str(i): e for i, e in enumerate(rows)}
        return [by_i[nm] for nm, sc in retrieve._bm25(q, docs)[:k] if sc > 0 and nm in by_i]
    return rows[-k:]                                       # the k most recent (episodic is oldest-first)


def recall(spath, npc_name, q="", k=3, blessed_only=True) -> list[dict]:
    """The NPC's own memory: the beats it acted in — newest-first, or BM25-ranked when `q` is given.
    `blessed_only` (the default, and REQUIRED for goal-affecting reads) excludes source='world' improv,
    so an NPC can never reinforce a goal off its own imagined beat. Returns up to k rows, each carrying
    its `source` (so the caller can mark blessed vs improv in the prompt). Empty when nothing matches."""
    name = _norm(npc_name)
    if not name or k <= 0:
        return []
    rows = [e for e in episodic.entries(spath) if _acts(e, name)]
    if blessed_only:
        rows = [e for e in rows if e.get("source") in _BLESSED]
    return _rank(rows, q, k)


def shared(spath, npc_name, other_name, q="", k=3, blessed_only=True) -> list[dict]:
    """An NPC's memory of a SPECIFIC other (the player, or another NPC): the beats where BOTH acted /
    were named. This is how a character 'remembers you' — grounded in what actually passed between them.
    Blessed-only by default (goal-safe). Empty when they share no history."""
    a, b = _norm(npc_name), _norm(other_name)
    if not a or not b or a == b or k <= 0:
        return []
    rows = [e for e in episodic.entries(spath) if _acts(e, a) and _acts(e, b)]
    if blessed_only:
        rows = [e for e in rows if e.get("source") in _BLESSED]
    return _rank(rows, q, k)


def clause(spath, npc_name, q="", k=3, blessed_only=True) -> str:
    """A prompt-ready recap of what this NPC remembers doing — '' when it remembers nothing. Improv
    rows (only present when blessed_only=False) are marked '(unconfirmed)' so the model can't silently
    promote an imagined beat to established fact."""
    rows = recall(spath, npc_name, q=q, k=k, blessed_only=blessed_only)
    if not rows:
        return ""
    lines = []
    for e in rows:
        tag = "" if e.get("source") in _BLESSED else " (unconfirmed)"
        lines.append(f"- {str(e.get('what', '')).strip()}{tag}")
    return f"What {npc_name} remembers:\n" + "\n".join(lines)
