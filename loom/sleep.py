"""loom.sleep — the world lives between sessions.

Between play, the world advances along its OWN pending logic — clocks tick, come-due threads
fire — and proposes what happened while the player was away. Propose-only and blessable (the
diode): nothing is written until you approve it. Events come from what was already SEEDED
(clocks, ripe threads), so the world moves *coherently*, not randomly.

Gated by `depth`: a mirror world pauses when you leave; an other world keeps moving (more
time passes the deeper the realness).
"""
from __future__ import annotations
import json
import re
from . import threads, canon, llm, state

_JSON_RE = re.compile(r"\{[\s\S]*\}")

_RECAP_PROMPT = """You are the chronicler of a story world. The player has been away. In their
absence, these pending things have come due:

%s

CANON (the world's established truth):
%s

Write a SHORT "meanwhile, while you were away" recap (2-4 sentences) of what happened — grounded
strictly in the pending events and the canon above, consistent with the world, understated. The
player was ABSENT: do not involve them. Respond with ONE json object:
{"recap": "the prose recap", "resolved": ["<id of any thread now fully spent, if any>"]}
"""


def advance(cfg, world, threads_path):
    """Tick the world forward one sleep and propose what happened. Returns a propose-only
    report; writes nothing. Gated by depth (beats = 0 at depth 0)."""
    depth = float(cfg.get("depth", 0) or 0)
    beats = 0 if depth <= 0 else max(1, round(depth * float(cfg.get("sleep_beats", 4))))
    th = threads.load(threads_path)
    for _ in range(beats):
        for t in th:
            if t.kind == "clock" and t.status not in ("resolved", "ready") and t.clock is not None:
                t.clock -= 1
                if t.clock <= 0:
                    t.status = "ready"
    # only CLOCKS move the world during sleep — autonomous, scheduled events. Question-threads
    # ripen by player-proximity and are player-facing beats; firing them here would pre-empt a
    # payoff meant for live play. (NPC drives making moves during sleep is a later rung.)
    due = [t for t in th if t.status == "ready" and t.kind == "clock"]
    report = {"beats": beats, "due": [t.id for t in due], "recap": "", "resolved": [], "threads": th}
    if not due:
        return report
    due_text = "\n".join(f"- {t.question}" for t in due)
    canon_text = "\n".join(f"{n['name']}: {n['body'][:150]}" for n in canon.load_all(world))[:1500]
    ccfg = dict(cfg)
    if cfg.get("consolidate_llm_url"):
        ccfg["llm_url"] = cfg["consolidate_llm_url"]
    if cfg.get("consolidate_model"):
        ccfg["llm_model"] = cfg["consolidate_model"]
    if cfg.get("consolidate_api_key"):
        ccfg["api_key"] = cfg["consolidate_api_key"]
    try:
        raw = llm.complete(_RECAP_PROMPT % (due_text, canon_text), ccfg, max_tokens=300,
                           temperature=0.4, response_format={"type": "json_object"})
        m = _JSON_RE.search(raw)
        data = json.loads(m.group(0)) if m else {}
    except Exception:
        data = {}
    report["recap"] = (data.get("recap") or "").strip()
    report["resolved"] = [r for r in (data.get("resolved") or []) if isinstance(r, str)]
    return report


def apply(report, threads_path, state_path, approve=lambda *a: True):
    """Bless a sleep report (the diode): persist the advanced clocks, resolve spent threads,
    and stash the recap so the next session opens with 'while you were away…'."""
    th = report.get("threads") or []
    recap = report.get("recap") or ""
    if not recap or not approve("sleep", recap, report):
        return {"recap": "", "resolved": []}
    by_id = {t.id: t for t in th}
    # ONLY fired clocks resolve during sleep — never a thread the recap model named. The model's
    # `resolved` list is untrusted output; honoring it would let sleep silently spend a live
    # player-facing question-thread's payoff (a diode leak). `due` is clocks-only (see advance).
    resolved = []
    for tid in report.get("due", []):
        t = by_id.get(tid)
        if t and t.kind == "clock":
            t.status = "resolved"            # a scheduled event, once recapped, has happened
            resolved.append(tid)
    threads.save(threads_path, th)
    st = state.load(state_path)
    prior = st.get("_recap", "")                      # don't clobber a recap the player hasn't read
    st["_recap"] = (prior + "\n\n" + recap).strip() if prior else recap
    state.save(state_path, st)
    return {"recap": recap, "resolved": resolved}
