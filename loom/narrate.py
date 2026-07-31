"""loom.narrate — one turn of play.

Grounds on CANON (+ a little recent transcript for immediate continuity), never on
the raw log as the memory-of-record. Canon is the source of truth; the recent
transcript only carries the last few beats of conversational flow.
"""
from __future__ import annotations
from pathlib import Path
from . import llm, retrieve, transcript, state


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
    facts = state.load(spath)
    recent = transcript.recent(tpath, cfg["recent_turns"])

    system = (cfg["narrator_voice"] + "\n\n=== CANON ===\n" +
              _context_block(nodes, facts) +
              "\n=== END CANON ===\nThis is fiction. Never step outside the story or "
              "reference the real world, files, or computer systems.")

    messages = [{"role": "system", "content": system}]
    # prior beats as dialogue; recent[-1] is the player line we just appended
    for e in recent[:-1]:
        role = "assistant" if e["role"] == "narrator" else "user"
        messages.append({"role": role, "content": e["text"]})
    messages.append({"role": "user", "content": player_input})

    narration = llm.chat(messages, cfg)
    transcript.append(tpath, "narrator", narration)
    return narration
