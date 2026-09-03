"""loom.agenda — an NPC's goal in MOTION, as a READ-VIEW (NPC-agency P2).

An NPC's want (blessed canon `wants:`) is a static desire. Its AGENDA is that want SEEN IN CONTEXT of
where the pursuit stands — COMPOSED at read time, never stored:
  • GOAL      = the canon want (blessed; never minted or mutated by a beat),
  • OPPOSES   = the canon `bound:` (what holds them back),
  • STATUS    = how ripe the pursuit is, read off its relational THREAD's readiness — which the director
               ripens from BLESSED play, not from improv,
  • REMEMBERS = what the NPC actually did toward it (npc_memory, BLESSED-only — a goal read never sees
               the NPC's own world-round improv, so it can't reinforce a goal off its own output).

This is deliberately NOT a writable goal store. A persisted, model-advanced goal would be the exact
self-propagation surface the floor forbids (goal→beat→re-read→reinforced goal = idée-fixe). By
composing only BLESSED signals at read time there is no write surface to collapse — the same
"memory is a read-view, not a diary" discipline, applied to purpose. Sized by char_rung, so only a
character the story affords personhood carries a felt agenda.
"""
from __future__ import annotations
from . import threads as _threads, npc_memory, salience


def _status(thread) -> str:
    """The felt state of a pursuit, from its relational thread's ripening (director-advanced, blessed)."""
    if thread is None:
        return "a private wish, not yet stirring"
    st = getattr(thread, "status", "dormant")
    r = float(getattr(thread, "readiness", 0.0) or 0.0)
    if st == "resolved":
        return "reached — the moment has passed"
    if st == "ready" or r >= _threads.READY:
        return "at a head — they are ready to move on it"
    if st == "ripening" or r >= 0.35:
        return "pressing — the pull is building"
    if st == "seeded" or r > 0:
        return "stirring — a first step taken"
    return "latent — held in check for now"


def _thread_for(name, want, thread_list, own_only=False):
    """The NPC's own relational thread (its want as a ripening dramatic question), or None. Matches the
    id npc.relational_threads mints first, then falls back to any unresolved thread merely NAMING the NPC.

    That name-entity fallback is fine for world-round casting, but it lets a character with NO live
    want-thread of its own borrow the readiness/status of a thread it only co-stars in — so a dormant
    'private wish' can read as ripe. `own_only=True` drops the fallback (id-match only), for a consumer
    that must judge the NPC's OWN pursuit and nothing borrowed (the player-facing live-pursuit read)."""
    tid = _threads.make_id(f"{name} {want}")
    for t in thread_list:
        if getattr(t, "id", None) == tid:
            return t
    if own_only:
        return None
    for t in thread_list:
        if getattr(t, "status", "") != "resolved" and name in (getattr(t, "entities", []) or []):
            return t
    return None


def pursuit(name, moral, thread_list, spath, rung, own_only=False) -> dict:
    """An NPC's pursuit state, composed from blessed signals — {} when it has no want or no personhood
    budget (rung 0). `remembers` is a BLESSED-only recall sized by rung (a goal read never sees improv).
    `own_only` (see _thread_for) forbids borrowing a co-star's thread — the pursuit must be the NPC's own."""
    want = (getattr(moral, "want", "") or "").strip()
    if not want or float(rung or 0) <= 0:
        return {}
    thread = _thread_for(name, want, thread_list, own_only=own_only)
    # a staged thread carries an ARC (successive payoff beats); the CURRENT step is the goal in front of the
    # NPC right now, so a multi-step pursuit reads "wants X … the step in front: bribe the gatekeeper" rather
    # than restating the whole want every beat. Director-advanced (blessed), so it's not self-propagating.
    # The step is read ONLY off the NPC's OWN (id-matched) thread — never a co-star's thread borrowed via the
    # name-entity fallback — else a world-round/sleep read grafts another NPC's concrete plan onto this goal.
    step = ""
    own = thread is not None and getattr(thread, "id", None) == _threads.make_id(f"{name} {want}")
    # a HIDDEN thread's concrete staged step is director-only — never surfaced in the pursuit line (which
    # reaches the player via _pursues_clause); the abstract status may show, the secret plan may not.
    stages = getattr(thread, "stages", None) if (own and not getattr(thread, "hidden", False)) else None
    if isinstance(stages, list) and stages:
        idx = int(getattr(thread, "stage", 0) or 0)
        if 0 <= idx < len(stages) and isinstance(stages[idx], str):
            step = stages[idx].strip()
    k = salience.recall_k(rung)
    # the NPC's RECENT blessed beats — what it actually, verifiably did (its pursuit history). Recent
    # rather than BM25-on-the-want: the NPC acts on its goal, so its latest acts ARE the pursuit, and
    # this needs no lexical overlap with the want string to surface them.
    remembers = npc_memory.recall(spath, name, k=k, blessed_only=True) if k else []
    return {
        "name": name,
        "goal": want,
        "opposes": (getattr(moral, "against", "") or "").strip(),
        "status": _status(thread),
        "readiness": round(float(getattr(thread, "readiness", 0.0) or 0.0), 2) if thread else 0.0,
        "step": step,
        "remembers": [str(e.get("what", "")).strip() for e in remembers],
    }


def line(name, moral, thread_list, spath, rung) -> str:
    """A prompt fragment for the NPC's pursuit — see line_of(). Computes the pursuit and formats it."""
    return line_of(pursuit(name, moral, thread_list, spath, rung))


def line_of(p) -> str:
    """Format a pursuit dict (from pursuit()): the NPC's goal, what opposes it, how ripe the pursuit is,
    and what they actually did toward it — so a world-round beat CONTINUES their arc instead of
    restarting it. '' for an empty pursuit (no want / rung 0). Lets a caller reuse ONE pursuit() call."""
    if not p:
        return ""
    bits = [f"{p['name']} wants {p['goal']}"]
    if p["opposes"]:
        bits.append(f"held back by {p['opposes']}")
    out = "; ".join(bits) + f". Their pursuit is {p['status']}."
    if p.get("step"):
        out += f" The step in front of them: {p['step']}."
    if p["remembers"]:
        out += " Toward it they have: " + "; ".join(p["remembers"][:3]) + "."
    return out
