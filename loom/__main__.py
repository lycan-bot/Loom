"""loom — a sealed, standalone AI story-narrator / game master.

Usage:
  python -m loom status                 show the live campaign
  python -m loom play                   interactive session
  python -m loom consolidate [--yes]    fold this session's log into canon (with approval)
  python -m loom seal-check             verify nothing has leaked past the wall
  python -m loom check                  continuity guard — flag canon/plan inconsistencies
  python -m loom new <name>             create a new campaign
  python -m loom worlds                 list campaigns (the shelf)
  python -m loom use <name>             switch the active campaign
  python -m loom npcs                   sync character drives into relational threads
  python -m loom imagine [--yes]        dream new threads from the canon (imagination organ)
  python -m loom sleep [--yes]          advance the world between sessions (depth-gated)
  python -m loom mechanics on|off       toggle the optional dice layer (impartial d20)
  python -m loom depth <0.0-1.0>        realness dial — 0 mirror (agrees) … 1 other (resists)
  python -m loom web [--port N]         browser UI (play + world map), default :8100
"""
from __future__ import annotations
import sys
from . import config, narrate, consolidate, seal, transcript, canon, state, llm, threads, npc, imagine, guard, sleep


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
        try:
            print("\nnarrator ›", narrate.turn(line, cfg, tpath, world, spath), "\n")
        except llm.LLMError as e:
            print(f"\n[!] {e}\n")
    print("session ended. run  python -m loom consolidate  to fold it into canon.")


def cmd_consolidate(cfg, auto):
    tpath, world, spath = _paths(cfg)
    lines = transcript.read_all(tpath)
    if not lines:
        print("nothing to consolidate.")
        return
    print("reading the session log…")
    existing = threads.load(spath.parent / "threads.json")
    try:
        proposals = consolidate.propose(cfg, lines, existing)
    except Exception as e:
        print(f"[!] consolidation failed ({e}); nothing written.")
        return
    print(f"proposed: {len(proposals['nodes'])} node(s), {len(proposals['state'])} state, "
          f"{len(proposals['threads_new'])} new thread(s), {len(proposals['threads_resolved'])} resolved, "
          f"{len(proposals['character_updates'])} disposition(s)")
    if proposals.get("summary"):
        print(f"summary: {proposals['summary']}")
    print()

    def approve(kind, name, payload):
        if auto:
            print(f"  + {kind}: {name}")
            return True
        return input(f"  keep {kind} '{name}'? [y/N] ").strip().lower() in ("y", "yes")

    written = consolidate.apply(proposals, world, spath, approve)
    print(f"\nwrote {len(written['nodes'])} node(s), {len(written['state'])} state, "
          f"{len(written['threads'])} thread(s), {len(written['resolved'])} resolved, "
          f"{len(written['dispositions'])} disposition(s).")
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
    _, world, spath = _paths(cfg)
    findings = guard.check(world, spath.parent / "threads.json")
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
    if not report.get("recap"):
        threads.save(thpath, report["threads"])          # time passed quietly; persist the clock ticks
        print("nothing came due; the world waits as you left it.")
        return
    print(f"\nwhile you were away ({report['beats']} beats of world-time passed):\n  {report['recap']}\n")

    def approve(kind, recap, rep):
        return auto or input("  fold this into the world? [y/N] ").strip().lower() in ("y", "yes")

    w = sleep.apply(report, thpath, spath, approve)
    print("folded — it will greet you when you return." if w["recap"] else "left as-is; the world un-moved.")


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
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
