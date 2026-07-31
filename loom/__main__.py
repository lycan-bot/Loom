"""loom — a sealed, standalone AI story-narrator / game master.

Usage:
  python -m loom status                 show the live campaign
  python -m loom play                   interactive session
  python -m loom consolidate [--yes]    fold this session's log into canon (with approval)
  python -m loom seal-check             verify nothing has leaked past the wall
  python -m loom new <name>             create a new campaign
  python -m loom web [--port N]         browser UI (play + world map), default :8100
"""
from __future__ import annotations
import sys
from . import config, narrate, consolidate, seal, transcript, canon, state, llm, threads


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
    proposals = consolidate.propose(cfg, lines)
    print(f"proposed: {len(proposals['nodes'])} node(s), {len(proposals['state'])} state change(s)")
    if proposals.get("summary"):
        print(f"summary: {proposals['summary']}")
    print()

    def approve(kind, name, payload):
        if auto:
            print(f"  + {kind}: {name}")
            return True
        return input(f"  keep {kind} '{name}'? [y/N] ").strip().lower() in ("y", "yes")

    written = consolidate.apply(proposals, world, spath, approve)
    print(f"\nwrote {len(written['nodes'])} node(s), {len(written['state'])} state key(s) to canon.")
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


def cmd_status(cfg):
    tpath, world, spath = _paths(cfg)
    print(f"campaign  : {cfg['campaign']}")
    print(f"model     : {cfg['llm_url']}  (embeddings: {cfg['use_embeddings']})")
    print(f"transcript: {len(transcript.read_all(tpath))} lines")
    print(f"canon     : {len(canon.load_all(world))} nodes")
    print(f"state     : {len(state.load(spath))} facts")
    print(f"threads   : {len([t for t in threads.load(spath.parent / 'threads.json') if t.status != 'resolved'])} pending")


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
    elif cmd == "new" and len(argv) > 1:
        cmd_new(cfg, argv[1])
    elif cmd == "status":
        cmd_status(cfg)
    elif cmd == "web":
        from . import web
        port = int(argv[argv.index("--port") + 1]) if "--port" in argv else 8100
        web.serve(cfg, port=port)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
