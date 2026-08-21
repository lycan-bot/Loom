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


def _thread_for(name, want, thread_list):
    """The NPC's own relational thread (its want as a ripening dramatic question), or None. Matches the
    id npc.relational_threads mints first, then falls back to any unresolved thread naming the NPC."""
    tid = _threads.make_id(f"{name} {want}")
    for t in thread_list:
        if getattr(t, "id", None) == tid:
            return t
    for t in thread_list:
        if getattr(t, "status", "") != "resolved" and name in (getattr(t, "entities", []) or []):
            return t
    return None


def pursuit(name, moral, thread_list, spath, rung) -> dict:
    """An NPC's pursuit state, composed from blessed signals — {} when it has no want or no personhood
    budget (rung 0). `remembers` is a BLESSED-only recall sized by rung (a goal read never sees improv)."""
    want = (getattr(moral, "want", "") or "").strip()
    if not want or float(rung or 0) <= 0:
        return {}
    thread = _thread_for(name, want, thread_list)
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
        "remembers": [str(e.get("what", "")).strip() for e in remembers],
    }


def line(name, moral, thread_list, spath, rung) -> str:
    """A prompt fragment: the NPC's goal, what opposes it, how ripe the pursuit is, and what they
    actually did toward it — so a world-round beat CONTINUES their arc instead of restarting it.
    '' when they have no agenda (no want, or rung 0). Blessed memory only (goal-safe)."""
    p = pursuit(name, moral, thread_list, spath, rung)
    if not p:
        return ""
    bits = [f"{p['name']} wants {p['goal']}"]
    if p["opposes"]:
        bits.append(f"held back by {p['opposes']}")
    out = "; ".join(bits) + f". Their pursuit is {p['status']}."
    if p["remembers"]:
        out += " Toward it they have: " + "; ".join(p["remembers"][:3]) + "."
    return out
