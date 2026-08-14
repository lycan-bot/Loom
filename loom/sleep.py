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
from pathlib import Path
from . import threads, canon, llm, state, npc, retrieve, episodic, transcript

_JSON_RE = re.compile(r"\{[\s\S]*\}")

_RECAP_PROMPT = """You are the chronicler of a story world. The player has been away. In their
absence, the world moved on its own:

%s

CANON (the world's established truth):
%s

Write a SHORT "meanwhile, while you were away" recap (2-4 sentences) of what happened — grounded
strictly in the items above and the canon, consistent with the world, understated. Characters act
IN CHARACTER, taking small concrete steps toward what they want; the world does NOT rearrange
itself around the absent player, and nothing hands them an advantage. A character's want is a goal
they are pursuing, NOT something that already happened — describe a step TOWARD it, and never invent
a past event, conversation, or testimony that is not grounded in the items and canon above.
Respond with ONE json object:
{"recap": "the prose recap", "resolved": ["<id of a thread the events fully spent, if any>"]}
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
    # only CLOCKS resolve during sleep — autonomous scheduled events. Question-threads ripen by
    # player-proximity and are player-facing beats; firing them here would pre-empt a live-play payoff.
    due = [t for t in th if t.status == "ready" and t.kind == "clock"]

    # the world's PEOPLE move too: a bounded, depth-scaled set of characters with a want each take a
    # small in-character step toward it while the player is away (grounded, propose-only, and — unlike
    # clocks — they do NOT resolve their relational thread; that dramatic payoff stays for live play).
    moves = []
    sm = float(cfg.get("sleep_moves", 2))
    if depth > 0 and sm > 0:                             # sleep_moves 0 → clocks-only sleep (off-switch)
        n = max(1, round(depth * sm))
        ds = npc.drives(world)
        ds.sort(key=lambda d: not d[1].tension)          # tensioned drives first (more dramatic); stable
        moves = [(name, m) for name, m, _e in ds[:n]]

    report = {"beats": beats, "due": [t.id for t in due], "moves": [name for name, _m in moves],
              "recap": "", "resolved": [], "threads": th, "pending": bool(due or moves)}
    if not report["pending"]:
        return report
    items = [f"- {t.question}" for t in due]
    items += [f"- {name}, who {m.because}, takes a small step toward it" for name, m in moves]
    items_text = "\n".join(items)
    # ground the recap in canon RELEVANT to who/what moved this sleep — not an alphabetical slice of
    # everything (the same 1500-char dump that let the world round free-associate false history)
    move_names = [name for name, _m in moves]
    query = " ".join([t.question for t in due] + move_names + [m.because for _n, m in moves])
    canon_text = retrieve.grounded_context(world, cfg, query, anchors=move_names) or "(no canon yet)"
    ccfg = dict(cfg)
    if cfg.get("consolidate_llm_url"):
        ccfg["llm_url"] = cfg["consolidate_llm_url"]
    if cfg.get("consolidate_model"):
        ccfg["llm_model"] = cfg["consolidate_model"]
    if cfg.get("consolidate_api_key"):
        ccfg["api_key"] = cfg["consolidate_api_key"]
    try:
        raw = llm.complete(_RECAP_PROMPT % (items_text, canon_text), ccfg, max_tokens=300,
                           temperature=0.4, response_format=llm.schema_format("sleep_recap", {
                               "type": "object", "properties": {
                                   "recap": {"type": "string"},
                                   "resolved": {"type": "array", "items": {"type": "string"}}}}))
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
    # the world moving while you slept is a timeline beat — record it (the 'while you were away' clock),
    # anchored just past the latest played entry so it sorts after the session it followed
    tpath = Path(state_path).parent / "transcript.jsonl"
    n_tx = len(transcript.read_all(tpath)) if tpath.exists() else 0
    episodic.record(state_path, [{"what": recap, "when": "while you were away"}],
                    entry_start=n_tx, entry_end=n_tx, source="sleep")
    return {"recap": recap, "resolved": resolved}
