# loom

A sealed, standalone AI **story-narrator / game master**. You play; it narrates,
voices the world, and *remembers* — across sessions — inside a contained memory
vault that can never touch anything real.

Clean-room-extracted from the Sigilus/Primarch mind: it borrows the patterns and a
few pure helpers (the reasoning-block stripper, the frontmatter parser, the
BM25/cosine/RRF retrieval math) but drags **none** of the floor, config, or
sovereignty apparatus. Pure standard library — zero dependencies.

## The idea

A good DM needs four things generic chatbots lack: a **voice**, **continuity**,
**grounding**, and a **wall** between the fiction and reality. loom is those four:

```
        observe                 consolidate                 mutate
  ┌──────────────┐   sleep   ┌──────────────┐          ┌──────────────┐
  │  transcript  │ ────────▶ │    canon     │ ───────▶ │    state     │
  │ append-only  │           │ world-bible  │          │  continuity  │
  │   play log   │ ◀──audit  │  (markdown)  │ ──grounds│  (json facts)│
  └──────────────┘           └──────────────┘   turn   └──────────────┘
         ▲                          │
         │ writes each turn         │  the narrator reasons from CANON,
         └───────── narrator ◀──────┘  never from the raw log
```

**The one rule that matters:** the narrator narrates from *consolidated canon*, not
from the raw transcript. The transcript is the source and the audit trail;
consolidation (with your approval) is the only path from what-was-said to
what-is-true. That single diode is what keeps a 40-session campaign coherent
instead of drifting on its own improv.

## The wall

loom's entire safety model is a **filesystem seal**: every read/write stays inside
`campaigns/<name>/`, and `seal.py` scans canon + state for any leak of a real path
or the source project. Because it's contained and has no hands on anything real,
it gets to be *free* inside the wall — no floor, no gates.

## Sovereignty — its own model server

loom runs its **own** llama.cpp server (`./serve.sh`, port 8090) so the narrator is
never steered by another project's control vector or persona. It talks to any local
OpenAI-compatible endpoint, so swapping models is just a path:

```bash
MODEL=/path/to/rocinante-12b.Q4_K_M.gguf ./serve.sh
```

For a "true D&D" feel you want an *uncensored / roleplay* tune that stays in
character. And because a wild narrator is often bad at clean JSON, the `consolidate`
step can point at a separate, obedient **archivist** model (`consolidate_llm_url`).

## Layout

```
loom/
  config.py       settings + campaign paths
  llm.py          thin client for a local OpenAI-compatible server (llama-server)
  transcript.py   the append-only play log            (observe)
  canon.py        markdown world-bible + [[links]]    (consolidate)
  state.py        continuity facts                    (mutate)
  retrieve.py     BM25-lite + optional embeddings, RRF-fused
  consolidate.py  the diode: transcript → proposed nodes/threads → you bless → canon
  narrate.py      one turn: pace → direct → voice → narrate → append
  pacing.py       the governor of restraint (hold vs offer) + tension homeostat
  director.py     when a ripe thread becomes a beat (seed → ripen → payoff)
  threads.py      the plan — open dramatic questions + world-clocks
  npc.py          character drives → relational threads (moral tension)
  imagine.py      dream new threads by recombining canon (sealed until blessed)
  character.py    per-character voice + card
  guard.py        the continuity guard (read-only consistency checks)
  mechanics.py    the optional dice layer (default off)
  prompt_security.py · seal.py   the wall (in-prompt fence + filesystem seal)
serve.sh          loom's own sovereign model server (no shared control vector)
campaigns/<name>/ transcript.jsonl · world/ · state.json
```

## Quickstart

```bash
./serve.sh                     # loom's own model server on :8090 (no shared persona vector)
python -m loom web             # browser UI: story · world map · the plan · imagine (:8100)
python -m loom play            # narrate in the terminal
python -m loom consolidate     # fold the session into canon + threads (with approval)
python -m loom imagine         # dream new threads from the canon
python -m loom npcs            # sync character drives into relational threads
python -m loom check           # continuity guard  ·  seal-check audits the wall
python -m loom mechanics on    # toggle the optional dice layer
python -m loom worlds          # list campaigns  ·  use <name> to switch  ·  new <name> to create
```

Embeddings are optional (`use_embeddings`); lexical retrieval is the zero-dependency
default.

## Status

MVP scaffold — the loop, the three-tier vault, the diode, and the wall are real and
tested. Runs its own sovereign model server and a stdlib-only web UI (`python -m loom
web`) — story pane, force-graph world map, canon reader — proven live against a local
Mag-Mell 12B.

The **restraint architecture** is built (the answer to AI roleplay's relentless
conflict-injection): a player-led narrator that won't manufacture drama; a pacing
**governor** (`pacing.py` — holds by default, offers only on a genuine stall, *calm ≠
boredom*); an injection **fence** + output guard (`prompt_security.py`); and a
**director** (`director.py` over `threads.py`) that paces *planned, seeded* threads —
open dramatic questions + world-clocks that ripen as the player drifts near them — so
surprise is **seeded → ripened → paid off**, earned and never random. The player owns
escalation. Next: consolidation-authoring of threads, and per-character voice.
