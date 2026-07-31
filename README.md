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

## Layout

```
loom/
  config.py       settings + campaign paths
  llm.py          thin client for a local OpenAI-compatible server (llama-server)
  transcript.py   the append-only play log            (observe)
  canon.py        markdown world-bible + [[links]]    (consolidate)
  state.py        continuity facts                    (mutate)
  retrieve.py     BM25-lite + optional embeddings, RRF-fused
  consolidate.py  the diode: transcript → proposed nodes → you bless → canon
  narrate.py      one turn: retrieve canon → prompt → append
  seal.py         the wall
campaigns/<name>/ transcript.jsonl · world/ · state.json
```

## Quickstart

```bash
cp config.example.json config.json      # point llm_url at your llama-server
python -m loom status                    # show the live campaign
python -m loom play                      # narrate
python -m loom consolidate               # end of session: fold the log into canon
python -m loom seal-check                # audit the wall
python -m loom new mycampaign            # start a fresh world
```

Runs against any local OpenAI-compatible endpoint (llama-server, Ollama, LM
Studio). Embeddings are optional (`use_embeddings`); lexical retrieval is the
zero-dependency default.

## Status

MVP scaffold — the loop, the three-tier vault, the diode, and the wall are real and
tested (`python -m unittest discover -s tests`). Round-2 organs to pull from
Primarch (voice card, imagination + gate, pacing nerves, prompt-injection guard,
world-graph UI) are catalogued and not yet wired.
