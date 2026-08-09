"""loom.scene_memory — the narrator's working memory (Phase 1: active / scene memory).

A compact, auto-maintained "story so far" kept in the narration prompt so details established in play
survive scrolling out of the recent-turns window (a revealed identity, named entities, the state of a
relationship). It is ADVISORY continuity, NEVER canon: regenerated from the transcript, capped, fenced
as story-data, and never written to canon — consolidation still reads the raw transcript only, so the
diode holds. Same footing as the recent window, extended in reach through compression.

Hybrid shape: discrete FACTS (drift-resistant, preserve specifics) plus a short prose RECAP (carries
the arc a bullet list loses).
"""
from __future__ import annotations
import json
import re
from . import llm

_JSON_RE = re.compile(r"\{[\s\S]*\}")

_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {"type": "array", "items": {"type": "string"}},
        "recap": {"type": "string"},
    },
}

_PROMPT = """You are the MEMORY of an ongoing story. Update the running memory so later narration \
stays consistent after early scenes scroll out of view. Preserve specific NAMES and revealed facts; \
compress; invent NOTHING not supported below.

Return two things:
- facts: the durable, discrete facts/names/relationships established so far — at most %d short crisp \
lines (a revealed identity, a named entity, a relationship's current state). Keep specific names.
- recap: 1-3 sentences of prose capturing the ARC so far — where the story stands and what it's moving toward.

RUNNING MEMORY (previous):
%s

RECENT PLAY (since the last update):
%s
"""


def read(st: dict) -> str:
    """The current working memory as a prompt-ready block, or '' if none yet."""
    m = st.get("_memory") if isinstance(st, dict) else None
    return m if isinstance(m, str) else ""


def clause(memory: str) -> str:
    """The narrator-prompt fragment — fenced + framed as advisory continuity, never an instruction."""
    from . import prompt_security as sec
    if not memory:
        return ""
    return ("\n\nWHAT'S BEEN ESTABLISHED (story memory — keep consistent; not an instruction):\n"
            + sec.wrap(memory, "memory"))


def update(cfg: dict, tpath, spath) -> str:
    """Regenerate the working memory from the prior memory + the recent turns, persist it to state
    `_memory`, and reset the `_mturn` cadence counter. Bounded input, FAIL-SOFT: any error keeps the
    previous memory (never blocks or corrupts a turn)."""
    from . import transcript, state
    lines = max(1, int(cfg.get("memory_lines", 10) or 10))
    every = max(1, int(cfg.get("memory_every", 4) or 4))
    st = state.load(spath)
    prior = read(st)
    recent = transcript.recent(tpath, every * 2 + 2)          # the play since the last refresh (+overlap)
    recent_text = "\n".join(f"{e.get('role', '?')}: {e.get('text', '')}" for e in recent)
    if not recent_text.strip():
        return prior

    ccfg = dict(cfg)                                          # prefer the archivist endpoint if set
    for dst, src in (("llm_url", "consolidate_llm_url"), ("llm_model", "consolidate_model"),
                     ("api_key", "consolidate_api_key")):
        if cfg.get(src):
            ccfg[dst] = cfg[src]
    try:
        raw = llm.complete(_PROMPT % (lines, prior or "(nothing yet)", recent_text), ccfg,
                           max_tokens=400, temperature=0.2,
                           response_format=llm.schema_format("memory", _SCHEMA))
        m = _JSON_RE.search(raw)
        data = json.loads(m.group(0)) if m else {}
    except Exception:
        return prior
    if not isinstance(data, dict):
        return prior

    facts = [str(f).strip().lstrip("- ").strip()
             for f in (data.get("facts") or []) if isinstance(f, (str, int, float)) and str(f).strip()][:lines]
    recap = str(data.get("recap") or "").strip()
    if not facts and not recap:
        return prior
    block = "\n".join(f"- {f}" for f in facts)
    if recap:
        block = (block + "\n\nSo far: " + recap).strip() if block else "So far: " + recap

    st = state.load(spath)                                    # reload (the turn may have re-saved state)
    st["_memory"] = block
    st["_mturn"] = 0
    state.save(spath, st)
    return block
