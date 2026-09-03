"""loom — a sealed, standalone AI story-narrator / game master.

Usage:
  python -m loom status                 show the live campaign
  python -m loom play                   interactive session
  python -m loom consolidate [--yes]    fold this session's log into canon (with approval)
  python -m loom seal-check             verify nothing has leaked past the wall
  python -m loom check                  continuity guard — flag canon/plan inconsistencies
  python -m loom new <name>             create a new campaign
  python -m loom generate [seed…]       roll a fresh world + starting cast (into the live campaign)
  python -m loom worlds                 list campaigns (the shelf)
  python -m loom use <name>             switch the active campaign
  python -m loom npcs                   sync character drives into relational threads
  python -m loom imagine [--yes]        dream new threads from the canon (imagination organ)
  python -m loom sleep [--yes]          advance the world between sessions (depth-gated)
  python -m loom world                  play one world round — major NPCs take their turns
  python -m loom world-show on|off      toggle showing the world round each turn during play
  python -m loom mechanics on|off       toggle the optional dice layer (impartial d20)
  python -m loom undo                    take back the last turn (also '/undo' while playing)
  python -m loom reputation              how the world regards you — standings + the deeds behind them
  python -m loom depth <0.0-1.0>        realness dial — 0 mirror (agrees) … 1 other (resists)
  python -m loom web [--port N]         browser UI (play + world map), default :8100
"""
from __future__ import annotations
import sys
from . import config, narrate, consolidate, seal, transcript, canon, state, llm, threads, npc, imagine, guard, sleep, worldturn, generate, undo, reputation, recall, extract, episodic, compact, provenance, character
from . import world as world_state    # aliased: `world` names the canon-dir Path throughout this module


def _paths(cfg):
    return config.transcript_path(cfg), config.world_dir(cfg), config.state_path(cfg)


def cmd_play(cfg):
    tpath, world, spath = _paths(cfg)
    print(f"— loom · campaign '{cfg['campaign']}' · {len(canon.load_all(world))} canon nodes —")
    print("  (type '/quit' to end, '/canon' to list nodes)\n")
    while True:
        try:
            line = input("you › ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("/quit", "/q"):
            break
        if line == "/canon":
            for n in canon.load_all(world):
                print(f"  [[{n['name']}]] — {n['frontmatter'].get('kind', 'lore')}")
            continue
        if line in ("/undo", "/u"):
            print("↩ last turn taken back.\n" if undo.undo(tpath, spath) else "nothing to undo.\n")
            continue
        try:
            print("\nnarrator ›", narrate.turn(line, cfg, tpath, world, spath), "\n")
            pulse = worldturn.maybe_round(cfg, world, spath)
            if pulse:
                print("— meanwhile, elsewhere —")
                for t in pulse:
                    who = ", ".join(t.get("who") or []) or "someone"
                    print(f"  [{t.get('where') or '…'}] {who}: {t['beat']}")
                print()
        except llm.LLMError as e:
            print(f"\n[!] {e}\n")
    print("session ended. run  python -m loom consolidate  to fold it into canon.")


def cmd_consolidate(cfg, auto):
    tpath, world, spath = _paths(cfg)
    lines, total = consolidate.unconsolidated(tpath, spath)   # only the NEW turns (incremental)
    if not lines:
        print("nothing new to consolidate.")
        return
    print(f"reading {len(lines)} new transcript entries…")
    existing = threads.load(spath.parent / "threads.json")
    try:
        proposals = consolidate.propose(cfg, lines, existing, world=world)
    except Exception as e:
        print(f"[!] consolidation failed ({e}); nothing written.")
        return
    print(f"proposed: {len(proposals['nodes'])} node(s), {len(proposals['state'])} state, "
          f"{len(proposals['threads_new'])} new thread(s), {len(proposals['threads_resolved'])} resolved, "
          f"{len(proposals['character_updates'])} character update(s), "
          f"{len(proposals.get('reputation') or [])} reputation shift(s)")
    if proposals.get("summary"):
        print(f"summary: {proposals['summary']}")
    print()

    def approve(kind, name, payload):
        desc = name
        if kind == "reputation" and isinstance(payload, dict):
            d = payload.get("delta", 0)
            desc = f"{name} ({'+' if d > 0 else ''}{d}: {payload.get('because', '')})"
        if auto:
            print(f"  + {kind}: {desc}")
            return True
        return input(f"  keep {kind} '{desc}'? [y/N] ").strip().lower() in ("y", "yes")

    written = consolidate.apply(proposals, world, spath, approve,   # deed-key + combined watermark save,
                                deed_window=(total - len(lines), total), watermark=total,   # matching the drain path
                                world_state=bool(cfg.get("world_state")),
                                npc_standing_on=bool(cfg.get("npc_standing")))
    print(f"\nwrote {len(written['nodes'])} node(s), {len(written['state'])} state, "
          f"{len(written['threads'])} thread(s), {len(written['resolved'])} resolved, "
          f"{len(written['dispositions'])} disposition(s), {len(written['locations'])} move(s), "
          f"{len(written.get('reputation') or [])} reputation shift(s).")
    if cfg.get("imagine_on_consolidate"):
        cands = imagine.propose(world, spath.parent / "threads.json", cfg, n=2)
        if cands:
            print(f"\nimagined {len(cands)} candidate thread(s) from the updated canon:")
            for c in cands:
                print(f"  ? {c.question}")

            def bless_approve(kind, q, c):
                return auto or input(f"  bless '{q[:50]}'? [y/N] ").strip().lower() in ("y", "yes")

            print(f"blessed {len(imagine.bless(spath.parent / 'threads.json', cands, bless_approve))} dreamed thread(s).")
    problems = seal.check_campaign(world, spath)
    if problems:
        print("[!] SEAL WARNING:", *problems, sep="\n  ")


def cmd_seal_check(cfg):
    _, world, spath = _paths(cfg)
    problems = seal.check_campaign(world, spath)
    if problems:
        print("SEAL BREACH:")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print("sealed ✓ — no real-world leakage in canon or state.")


def cmd_new(cfg, name):
    if not config.valid_campaign_name(name):
        print(f"bad campaign name {name!r} — no '/', '\\', or '..' (it must stay inside the campaigns dir).")
        return
    cdir = config.ROOT / cfg["campaigns_dir"] / name
    (cdir / "world").mkdir(parents=True, exist_ok=True)
    canon.write_node(cdir / "world", "The World",
                     "The opening premise of the story goes here.", {"kind": "lore"})
    state.save(cdir / "state.json", {})
    print(f"created campaign '{name}' at {cdir}")
    print(f'set "campaign": "{name}" in config.json to make it live.')


def cmd_worlds(cfg):
    base = config.ROOT / cfg["campaigns_dir"]
    names = sorted(p.name for p in base.iterdir() if (p / "world").is_dir()) if base.exists() else []
    if not names:
        print("no campaigns yet — 'loom new <name>' to create one.")
        return
    for n in names:
        print(f"  {'* ' if n == cfg['campaign'] else '  '}{n}")


def cmd_use(cfg, name):
    if not (config.ROOT / cfg["campaigns_dir"] / name / "world").is_dir():
        print(f"no such campaign '{name}'. 'loom worlds' to list, 'loom new {name}' to create.")
        return
    config.save({"campaign": name})
    print(f"switched to '{name}'.")


def cmd_status(cfg):
    tpath, world, spath = _paths(cfg)
    print(f"campaign  : {cfg['campaign']}")
    print(f"model     : {cfg['llm_url']}  (embeddings: {cfg['use_embeddings']})")
    print(f"mechanics : {'on' if cfg.get('mechanics') else 'off'}")
    print(f"depth     : {cfg.get('depth', 0.0)}  (0 mirror … 1 other)")
    print(f"transcript: {len(transcript.read_all(tpath))} lines")
    print(f"canon     : {len(canon.load_all(world))} nodes")
    print(f"state     : {len([k for k in state.load(spath) if not k.startswith('_')])} facts")
    print(f"threads   : {len([t for t in threads.load(spath.parent / 'threads.json') if t.status != 'resolved'])} pending")
    rep = reputation.load(state.load(spath))
    if rep:
        print("reputation:")
        for who, e in sorted(rep.items()):
            print(f"            {who}: {reputation.label(int(e.get('standing', 0) or 0))}")


def cmd_mechanics(cfg, arg):
    on = arg == "on"
    config.save({"mechanics": on})
    print(f"mechanics {'ON — an impartial d20 now decides uncertain actions' if on else 'off'}.")


def cmd_depth(cfg, arg):
    try:
        v = max(0.0, min(1.0, float(arg)))
    except ValueError:
        print("depth must be a number 0.0–1.0 (0 = mirror / agrees, 1 = other / resists).")
        return
    config.save({"depth": v})
    label = "mirror — the world agrees" if v == 0 else "other — the world resists" if v >= 0.8 else "in between"
    print(f"realness depth set to {v} ({label}).")


def cmd_check(cfg):
    tpath, world, spath = _paths(cfg)
    findings = guard.check(world, spath.parent / "threads.json", tpath=tpath, spath=spath)
    if not findings:
        print("continuity: clean ✓")
        return
    print(f"continuity — {len(findings)} finding(s):")
    for f in findings:
        print(f"  [{f.severity}] {f.kind}: {f.message}")


def cmd_imagine(cfg, auto=False):
    _, world, spath = _paths(cfg)
    thpath = spath.parent / "threads.json"
    print("dreaming…")
    cands = imagine.propose(world, thpath, cfg)
    if not cands:
        print("nothing coherent surfaced this time.")
        return
    print(f"imagined {len(cands)} candidate thread(s):")
    for c in cands:
        print(f"  ? {c.question}   [{', '.join(c.entities)}]")

    def approve(kind, q, c):
        if auto:
            print(f"  + {q[:70]}")
            return True
        return input(f"  bless '{q[:60]}'? [y/N] ").strip().lower() in ("y", "yes")

    added = imagine.bless(thpath, cands, approve)
    print(f"\nblessed {len(added)} into the plan as dormant thread(s).")


def cmd_sleep(cfg, auto=False):
    _, world, spath = _paths(cfg)
    thpath = spath.parent / "threads.json"
    if float(cfg.get("depth", 0) or 0) <= 0:
        print("the world doesn't move on its own at depth 0 — raise it ('loom depth 0.5') to let it live between sessions.")
        return
    print("the world turns while you're away…")
    report = sleep.advance(cfg, world, thpath)
    if report.get("recap"):
        print(f"\nwhile you were away ({report['beats']} beats of world-time passed):\n  {report['recap']}\n")

        def approve(kind, recap, rep):
            return auto or input("  fold this into the world? [y/N] ").strip().lower() in ("y", "yes")

        w = sleep.apply(report, thpath, spath, approve)
        print("folded — it will greet you when you return." if w["recap"] else "left as-is; the world un-moved.")
    elif report.get("pending"):
        # something happened (a clock fired or a character moved) but the recap couldn't be written —
        # don't persist the half-fired state; leaving threads.json untouched lets it re-fire next sleep
        print("the world stirred but the recap couldn't be written (model unreachable?) — try again in a moment.")
    else:
        threads.save(thpath, report["threads"])          # nothing due; time passed quietly, persist the ticks
        print("nothing came due; the world waits as you left it.")


def cmd_generate(cfg, seed="", n=3, auto=False):
    _, world, _ = _paths(cfg)
    existing = canon.load_all(world)
    print("rolling a world…" + (f"  (seed: {seed})" if seed else ""))
    try:
        wc = generate.world(cfg, seed)
    except llm.LLMError as e:
        print(f"[!] {e}  (is ./serve.sh running?)")
        return
    if not wc.get("name") and not wc.get("body"):
        print("the roll came up empty — try again.")
        return
    print(f"\n  ✦ {wc.get('name') or '(unnamed)'} — {wc.get('premise', '')}")
    for k in ("age", "tech", "magic", "peoples", "tone"):
        if wc.get(k):
            print(f"    · {k}: {wc[k]}")
    if wc.get("body"):
        print(f"\n  {wc['body']}")
    print("\nrolling a cast…")
    try:
        cast = generate.cast(cfg, wc, n)
    except llm.LLMError:
        cast = []
    for c in cast:
        loc = f"  @ {c['location']}" if c.get("location") else ""
        print(f"\n  • {c['name']} — {c.get('role', '')}{loc}")
        if c.get("wants"):
            print(f"      wants {c['wants']}" + (f", held by {c['bound']}" if c.get("bound") else ""))
        if c.get("description"):
            print(f"      {c['description']}")
    if existing:
        print(f"\n[!] campaign '{cfg['campaign']}' already holds {len(existing)} node(s) — "
              "writing will add this world alongside them ('loom new <name>' first for a clean slate).")
    ok = auto or input("\nwrite this world into the campaign? [y/N] ").strip().lower() in ("y", "yes")
    if not ok:
        print("discarded — nothing written.")
        return
    generate.write_world(world, wc, cast)
    print(f"wrote the world + {len(cast)} character(s) into '{cfg['campaign']}'. 'loom play' to begin.")


def cmd_world(cfg):
    _, world, _ = _paths(cfg)
    if float(cfg.get("depth", 0) or 0) <= 0:
        print("the world's people don't act on their own at depth 0 — raise depth ('loom depth 0.5') to let them.")
        return
    print("the world takes its turn…\n")
    report = worldturn.run(cfg, world)
    if not report["turns"]:
        if report["pending"]:
            print("the world stirred but the round couldn't be written (model unreachable?).")
        else:
            print("no one here has an agenda of their own yet — give a character a 'wants:' in their node.")
        return
    for t in report["turns"]:
        who = ", ".join(t.get("who") or []) or "someone"
        where = t.get("where") or "parts unknown"
        print(f"  [{where}] {who}: {t['beat']}")


def cmd_world_show(cfg, arg):
    on = arg == "on"
    config.save({"world_rounds": on})
    print(f"world rounds {'SHOWN each turn during play' if on else 'hidden (they still run in the background)'}.")


def cmd_facts(cfg):
    """The symbolic-object layer: the world's tracked concrete state — objects/places and what is true of
    them right now, grouped by subject. Pure read (the narrator grounds on this; only the diode writes it)."""
    _, _world, spath = _paths(cfg)
    facts = world_state.load(spath)
    if not facts:
        tip = "" if cfg.get("world_state") else "  (the layer is OFF — 'loom world-state on' to ground on it.)"
        print("no world facts tracked yet." + tip)
        return
    print("world state (true right now)")
    for grp in world_state.by_subject(facts):
        print(f"  {grp['subject']}:")
        for f in grp["facts"]:
            print(f"    · {f['attribute']}: {f['value']}")


def cmd_world_state(cfg, arg):
    on = arg == "on"
    config.save({"world_state": on})
    print("world-state grounding " + ("ON — the narrator now grounds on tracked object facts." if on else "OFF."))


def cmd_ablation(cfg):
    """The retrieval-miss report: canon entities the player named that retrieval didn't surface, per entity.
    The evidence base for the embeddings kill-criterion ('a node that mattered, twice')."""
    from . import ablation
    _, _world, spath = _paths(cfg)
    r = ablation.report(spath)
    if not cfg.get("retrieval_log"):
        print("retrieval logging is OFF — 'loom retrieval-log on' to gather evidence.\n")
    if not r["miss_turns"]:
        print("no retrieval misses logged — BM25 has surfaced every named entity so far "
              "(the evidence says embeddings aren't earning their cost yet).")
        return
    print(f"retrieval misses: {r['miss_turns']} turn(s), {r['distinct_missed']} distinct entit(ies)")
    for name, c in r["by_entity"].items():
        mark = "  ⚠ repeated" if c >= 2 else ""
        print(f"  {c}× {name}{mark}")
    if r["kill_criterion_met"]:
        print(f"\nkill-criterion MET — {', '.join(r['repeated_misses'])} missed 2×+; semantic retrieval is worth considering.")


def cmd_retrieval_log(cfg, arg):
    on = arg == "on"
    config.save({"retrieval_log": on})
    print("retrieval logging " + ("ON — misses accrue in ablation_log.jsonl ('loom ablation' to view)." if on else "OFF."))


def cmd_undo(cfg):
    tpath, _world, spath = _paths(cfg)
    print("↩ took back the last turn." if undo.undo(tpath, spath) else "nothing to undo.")


def cmd_reputation(cfg):
    _, _world, spath = _paths(cfg)
    rep = reputation.load(state.load(spath))
    if not rep:
        print("no reputation yet — the world hasn't formed an opinion of you. (it forms at consolidation.)")
        return
    print("how the world regards you:")
    for who, e in sorted(rep.items()):
        standing = int(e.get("standing", 0) or 0)
        print(f"\n  {who}: {reputation.label(standing)} ({standing:+d})")
        for deed in (e.get("log") or []):
            print(f"      {deed}")


def cmd_npcs(cfg):
    _, world, spath = _paths(cfg)
    ds = npc.drives(world)
    if not ds:
        print("no characters with a stated want (add 'wants:' to a character node's frontmatter).")
        return
    print("character drives:")
    for name, m, _ents in ds:
        print(f"  {name}: {m.because}" + ("   [in tension]" if m.tension else ""))
    added = npc.sync(world, spath.parent / "threads.json")
    print(f"\nsynced {len(added)} relational thread(s) into the plan"
          + ("".join(f"\n  + {q}" for q in added) if added else "."))


def cmd_recall(cfg, query):
    tpath, _world, spath = _paths(cfg)
    hits = recall.search(tpath, query, k=6)
    if not hits:
        print(f"nothing in the record matches {query!r}.")
        return
    print(f"the record, on {query!r}:")
    for h in hits:
        print(f"\n  [turn {h['turn']}] you: {h['player'][:100]}")
        print(f"           → {h['narrator'][:180]}")


def cmd_entities(cfg):
    tpath, world, _spath = _paths(cfg)
    em = extract.emergent(tpath, world)
    if not em:
        print("no unestablished names — the narrator is staying grounded in canon.")
        return
    print("names the narrator keeps using that AREN'T in canon (add to canon, or a confabulation to catch):")
    for e in em:
        print(f"  {e['name']}  — {e['count']} turns {e['turns']}")


def cmd_timeline(cfg, query=""):
    _, _world, spath = _paths(cfg)
    events = episodic.query(spath, query) if query else episodic.entries(spath)
    if not events:
        print(f"nothing on the timeline matches {query!r}." if query
              else "the timeline is empty — events are recorded at consolidation.")
        return
    print(f"the timeline{f' — {query!r}' if query else ''}:")
    for e in events:
        ts = e.get("entry_start")
        when = e.get("when") or (f"entries {ts}-{e.get('entry_end')}" if ts is not None else "?")
        print(f"  [{when}] {e['what']}")


def cmd_compact(cfg, name=""):
    _, world, _spath = _paths(cfg)
    if not name:
        cands = compact.oversized(world)
        if not cands:
            print("no bloated nodes — canon is tidy.")
            return
        print("bloated nodes (run 'loom compact <name>' to distill):")
        for n in cands:
            print(f"  {n['name']}  ({len(n['body'])} chars)")
        return
    node = canon.read_node(world, name)
    if not node:
        print(f"no such node: {name!r}")
        return
    print(f"distilling '{node['name']}' ({len(node['body'])} chars)…")
    try:
        distilled = compact.propose(node, cfg)
    except Exception as e:
        print(f"[!] failed: {e}")
        return
    ok, reason = compact.verify(node["body"], distilled)
    print(f"  -> {len(distilled)} chars; {'OK' if ok else 'REFUSED — ' + reason}")
    if not ok:
        return
    print("\n--- distilled body (review before blessing) ---\n" + distilled + "\n" + "-" * 48)
    if input("apply this rewrite? [y/N] ").strip().lower() in ("y", "yes"):
        compact.apply(world, node["name"], distilled)
        print("compacted.")


def cmd_npc(cfg, name):
    """A character's composed INTERIOR — personhood rung, mood, agenda, and what they remember (of the
    world and of you). The same read-view the /tron mind panel shows, in the terminal."""
    tpath, world, spath = _paths(cfg)
    node = canon.read_node(world, name) if name else None
    if not node or node["frontmatter"].get("kind") != "character":
        print(f"no such character: {name!r}")
        return
    d = character.interior(world, tpath, spath, cfg, node)
    print(f"{d['name']}  —  {d['tier']} · rung {d['rung']}" + ("  (interior projected for review)" if d["agenda_projected"] else ""))
    if d["mood"]:
        print(f"  mood     : {d['mood']}")
    ag = d["agenda"]
    if ag:
        print(f"  goal     : {ag.get('goal')}" + (f"  (held by {ag['opposes']})" if ag.get("opposes") else ""))
        print(f"  pursuit  : {ag.get('status')}")
    if d["remembers"]:
        print("  remembers: " + "; ".join(r["what"] for r in d["remembers"][:4]))
    if d["remembers_player"]:
        print("  of you   : " + "; ".join(r["what"] for r in d["remembers_player"][:4]))


def cmd_reversals(cfg, arg=""):
    """Contradiction-repair: the disposition FLIPS the auto-fold held for your decision (it never
    overwrites an established feeling on the archivist's say-so). `loom reversals` lists them;
    `loom reversals bless <name>` applies the flip; `loom reversals reject <name>` keeps the feeling."""
    _, world, spath = _paths(cfg)
    parts = arg.split()
    if len(parts) >= 2 and parts[0] in ("bless", "reject"):
        name = " ".join(parts[1:])
        ok = consolidate.apply_reversal(world, spath, name, "disposition",
                                        approve=(lambda *a: parts[0] == "bless"))
        print(("↩ flip applied — " if ok else ("✗ flip rejected; the feeling stands — " if parts[0] == "reject"
               else "no held reversal for ")) + name)
        return
    pen = consolidate.pending_reversals(spath)
    if not pen:
        print("no held reversals — no contradicting flips awaiting your decision.")
        return
    print("held reversals (a feeling FLIPPED sign; the auto-fold held it rather than overwrite it):")
    for r in pen:
        print(f"  {r['name']} {r['field']}: {r['old']!r} → {r['new']!r}")
    print("\n  decide: loom reversals bless <name>  |  loom reversals reject <name>")


def cmd_why(cfg, name):
    """The provenance trail: how a fact reached its current value — every recorded change old→new, when,
    and whether it was a contradiction (a reversal). 'how do I know this?' answered."""
    _, _world, spath = _paths(cfg)
    rows = provenance.history(spath, name=name) if name else provenance.entries(spath)[::-1]
    if not rows:
        print(f"no recorded changes for {name!r}." if name
              else "the ledger is empty — nothing has been reconciled yet.")
        return
    print(f"how {name!r} came to be" if name else "the change ledger (newest first)")
    for r in rows:
        ts = r.get("entry_start")
        when = f"entries {ts}-{r.get('entry_end')}" if ts is not None else "?"
        flag = "  ⚠ reversal" if r.get("reversal") else ""
        who = "" if name else f"{r.get('name')} "
        print(f"  [{when}] {who}{r.get('field')}: {r.get('old')!r} → {r.get('new')!r}{flag}")


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    cfg = config.load()
    cmd = argv[0] if argv else "status"
    if cmd == "play":
        cmd_play(cfg)
    elif cmd == "consolidate":
        cmd_consolidate(cfg, auto="--yes" in argv)
    elif cmd == "seal-check":
        cmd_seal_check(cfg)
    elif cmd == "check":
        cmd_check(cfg)
    elif cmd == "mechanics" and len(argv) > 1:
        cmd_mechanics(cfg, argv[1])
    elif cmd == "depth" and len(argv) > 1:
        cmd_depth(cfg, argv[1])
    elif cmd == "new" and len(argv) > 1:
        cmd_new(cfg, argv[1])
    elif cmd == "worlds":
        cmd_worlds(cfg)
    elif cmd == "use" and len(argv) > 1:
        cmd_use(cfg, argv[1])
    elif cmd == "status":
        cmd_status(cfg)
    elif cmd == "web":
        from . import web
        port = int(argv[argv.index("--port") + 1]) if "--port" in argv else 8100
        web.serve(cfg, port=port)
    elif cmd == "npcs":
        cmd_npcs(cfg)
    elif cmd == "imagine":
        cmd_imagine(cfg, auto="--yes" in argv)
    elif cmd == "sleep":
        cmd_sleep(cfg, auto="--yes" in argv)
    elif cmd == "generate":
        cmd_generate(cfg, seed=" ".join(a for a in argv[1:] if a != "--yes"), auto="--yes" in argv)
    elif cmd == "world":
        cmd_world(cfg)
    elif cmd == "world-show" and len(argv) > 1:
        cmd_world_show(cfg, argv[1])
    elif cmd == "facts":
        cmd_facts(cfg)
    elif cmd == "world-state" and len(argv) > 1:
        cmd_world_state(cfg, argv[1])
    elif cmd == "ablation":
        cmd_ablation(cfg)
    elif cmd == "retrieval-log" and len(argv) > 1:
        cmd_retrieval_log(cfg, argv[1])
    elif cmd == "undo":
        cmd_undo(cfg)
    elif cmd == "reputation":
        cmd_reputation(cfg)
    elif cmd == "recall" and len(argv) > 1:
        cmd_recall(cfg, " ".join(argv[1:]))
    elif cmd == "entities":
        cmd_entities(cfg)
    elif cmd == "timeline":
        cmd_timeline(cfg, " ".join(argv[1:]))
    elif cmd == "compact":
        cmd_compact(cfg, " ".join(argv[1:]))
    elif cmd == "why":
        cmd_why(cfg, " ".join(argv[1:]))
    elif cmd == "reversals":
        cmd_reversals(cfg, " ".join(argv[1:]))
    elif cmd == "npc" and len(argv) > 1:
        cmd_npc(cfg, " ".join(argv[1:]))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
