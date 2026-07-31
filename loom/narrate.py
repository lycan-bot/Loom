"""loom.narrate — one turn of play.

Grounds on CANON (+ a little recent transcript for immediate continuity), never on
the raw log as the memory-of-record. Canon is the source of truth; the recent
transcript only carries the last few beats of conversational flow.
"""
from __future__ import annotations
from pathlib import Path
from . import llm, retrieve, transcript, state, pacing, threads, director
from . import prompt_security as sec


def _context_block(nodes: list[dict], facts: dict) -> str:
    parts = []
    if facts:
        parts.append("CONTINUITY (true right now):\n" +
                     "\n".join(f"- {k}: {v}" for k, v in facts.items()))
    for n in nodes:
        kind = n["frontmatter"].get("kind", "lore")
        parts.append(f"[[{n['name']}]] ({kind}):\n{n['body'].strip()}")
    return "\n\n".join(parts) if parts else "(the world is blank — this is the opening scene)"


def turn(player_input: str, cfg: dict, tpath: Path, world: Path, spath: Path) -> str:
    transcript.append(tpath, "player", player_input)

    nodes = retrieve.retrieve(player_input, world, cfg)
    st = state.load(spath)
    facts = {k: v for k, v in st.items() if not k.startswith("_")}    # _-keys are internal (tension)
    tension = st.get("_tension", cfg.get("tension_baseline", 0.15))
    recent = transcript.recent(tpath, cfg["recent_turns"])
    pace = pacing.read(recent, tension)

    scene_names = [n["name"] for n in nodes]
    thpath = spath.parent / "threads.json"
    th_list = threads.load(thpath)
    newly = threads.advance(th_list, scene_names)
    beat = director.decide(th_list, scene_names, pace, newly)
    beat_clause = director.clause(beat)          # capture BEFORE settle advances the stage
    director.settle(beat)
    if th_list:
        threads.save(thpath, th_list)          # persist ripening + the beat's consequence

    canon_block = sec.wrap(_context_block(nodes, facts), "canon")
    system = (cfg["narrator_voice"] + "\n\n" + sec.UNTRUSTED_PREAMBLE +
              "\n\n=== CANON ===\n" + canon_block +
              "\n=== END CANON ===\nThis is fiction. Never step outside the story or reference "
              "the real world, files, or computer systems." + beat_clause)

    messages = [{"role": "system", "content": system}]
    # prior beats as dialogue; recent[-1] is the player line we just appended
    for e in recent[:-1]:
        if e["role"] == "narrator":
            messages.append({"role": "assistant", "content": e["text"]})
        else:
            messages.append({"role": "user", "content": sec.neutralize(e["text"])})
    messages.append({"role": "user", "content": sec.neutralize(player_input)})

    narration = llm.chat(messages, cfg)
    if sec.looks_compromised(narration):
        narration = sec.DEFLECTION       # the model caved or broke character — deflect in-fiction
    transcript.append(tpath, "narrator", narration)

    # advance the tension homeostat with this beat and persist it for next turn
    st2 = state.load(spath)
    st2["_tension"] = pacing.update_tension(tension, narration,
                                            cfg.get("tension_baseline", 0.15), cfg.get("tension_decay", 0.7))
    state.save(spath, st2)
    return narration
