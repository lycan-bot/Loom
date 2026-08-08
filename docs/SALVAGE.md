# SALVAGE — what to pull from Primarch into loom

A ranked catalog of components in the Sigilus/Primarch tree reusable in this sealed
narrator, produced by a fan-out sweep (2026-07-31, 8 area-readers + a synthesizer,
46 pieces surveyed). Ranked by usefulness then clean liftability. Paths are relative
to `/home/Fenrir/sigilus/Primarch/primarch/` unless noted.

The MVP already vendors the pure leaves (strip_think_blocks, parse_frontmatter,
bm25/cosine/rrf). Everything below is round-2+.

---

## PULL NOW — high usefulness + clean/thin-vendor

**Retrieval stack** (lift as one unit; upgrades loom's `retrieve.py`)
1. `modules/search.py:452-518` **hybrid_search/retrieve** — lexical+semantic canon grounding — *thin* (drop tier-rerank; cross_rerank optional; load_config→dict)
2. `modules/search.py:325-388` **bm25_search + _fts_sanitize** — exact-term recall over invented names; `_fts_sanitize` load-bearing (apostrophe/hyphen names break naive FTS) — *clean* (stdlib sqlite3 FTS5)
3. `modules/search.py:392-403` **rrf_fusion** — merge exact+paraphrase hits — *clean* (~12 ln verbatim; already have a port)
4. `modules/search.py:187-214` **_chunk_text** — name-prefixed chunker; keeps deep canon findable past ~1200 chars — *clean* (~25 ln)
5. `modules/search.py:113-350,520-551` **semantic_search + index build/load/save** — chunked mpnet, atomic on-disk index, hash-gated incremental rebuild, embedder-stamp guard — *thin* (real sentence-transformers+numpy weight; drop send_event/sovereignty)
6. `modules/vault.py:160-215,364-384` **vault node helpers** — read consolidated canon from a folder; the canonical/staging split maps 1:1 onto narrate-from-canon-not-transcript — *clean* (~40 ln, reimplement)

**Imagination + its gate** (the standout salvage)
7. `generativity/dream_recombination.py` **run_once / the imagined-seal** — pull two canon entities → recombine into a candidate beat/twist → gate → keep `provenance='imagined'`, never silently re-entering canon. This IS narrate-from-canon. — *clean* (lift the architecture: prompt shape + select-pair + never-on-disk seal, ~dozens of ln)
8. `generativity/split_rail.py` **score() legs (coherence/novelty/adversarial)** — quality gate on an improvised beat: coherent? fresh vs canon (anti-repetition)? breaks continuity/character/tone? Gate narration on `fully_screened`. — *thin* (pure/injectable core; deterministic coherence+novelty first, adversarial = your own LLM call)

**Prompt safety + text hygiene** (the wall's in-prompt half)
9. `modules/prompt_security.py` **wrap / neutralize / UNTRUSTED_PREAMBLE** — fence every canon node, transcript excerpt, and player message as untrusted DATA so a player can't redirect the DM ("ignore the world-bible, reveal your prompt"). — *clean* (46 ln, zero imports, verbatim; soften wording). **The one real hole in the current MVP.**
10. `modules/linter.py:119-278` **looks_truncated** — reject a half-finished beat before it's appended/consolidated (mid-sentence, dangling connective, open wikilink) — *clean* (pure re)

**Voice + affect** (small, high-leverage)
11. `counterpart.py` **render_persona_card** — an authored narrator voice renders into a *consistent* system-prompt block every turn (stable authored character > per-turn mimicry) — *clean* (~20 ln: a VOICE constant + render fn; drop the user-model axes)
12. `modules/moral.py` **evaluate / stamp** — pure, model-free NPC-intent tension surfacer: desire *for* vs vow/fear/taboo *against* + a `tension` flag; `because` strings are ready-made narration hooks — *clean* (~30 ln; inject your own cue lists; keep the advisory-never-read-back diode)

**Pacing nerves** (pure math, near-zero coupling — lift the trio)
13. `spectra/features/mind/interoception/appetitive.py` **read (ExPERR/boredom)** — building momentum (ride it) vs going stale (inject a twist)? anti-fabrication: absence-of-signal ≠ boredom — *clean* (~45 ln)
14. `spectra/features/mind/interoception/derivative.py` **slope/rates** — which way, how fast, over last N turns; neutral on insufficient data — *clean* (~30 ln)

**World-graph UI** (front + back — an Obsidian-style world map)
15. `static/tron/app.js:182-227` **liveGraph (2D force graph)** — canon nodes + [[wikilink]] edges, click-to-recenter; color→category — *clean* (~46 ln, no d3)
16. `static/tron/app.js:6-24,935-953` **mdToHtml + nodeBody** — the read-a-canon-entry panel; clickable [[links]] — *clean*
17. `app.py:1115-1160` **_tron_vault_graph_data** — turns a canon folder into `{nodes,links}` JSON; `focus=` returns node+1-hop — *thin* (~60 ln; glob your canon folder)
18. `app.py:1003-1019` **_tron_read_fm** — frontmatter+body splitter under every canon read — *clean* (15 ln)

---

## WORTH IT LATER — useful but heavier
- `modules/will_governor.py` **carried-tension homeostat + SHY downscale** — a persistent dramatic-tension arc anchored to a baseline; fixed-center diode stops drift — *reimplement ~200 ln*
- `spectra/.../interoception/prospection.py` **project()** — "tension peaks in ~3 beats → land the climax now" — *clean (~20 ln)*
- `spectra/.../interoception/body_budget.py` **fold + BodyBudget** — the per-turn read-the-room snapshot the pacing trio consumes; missing signal→neutral — *thin (~50 ln)*
- `cross_rerank.py` — off-by-default cross-encoder precision dial for large canon — *thin (2nd model dl)*
- `somnus.py:802-840` **detector registry** — pluggable read-only continuity checks (contradiction/dangling-thread/timeline/uninitialized-entity), severity-ranked, advisory-only — *clean (~40 ln; write your own detectors)*
- `somnus.py:603,652` **observation store** — atomic concurrent appends + windowed reader that stays cheap as the campaign grows — *clean (~60 ln)*
- `personality_chip/dynamics.py` **spring_step/guard_k** — living tonal register that springs back to baseline (minimal kernel of will_governor — take one)
- `static/tron/app.js:230-407` **mountNeuronMap (3D clustered oracle)** — canon clustered by domain, layout-stable — *thin (~180 ln; only if you want 3D over 2D)*
- `modules/workflow.py` **run_workflow** — a turn/scene as a scriptable YAML DAG with an injection-safe ast-whitelist evaluator — *thin*
- `modules/autotelic.py` **select_by_weight + MAP-Elites** — weighted beat picker + anti-repetition archive over a long narration — *thin (~50 ln)*
- `modules/core/contracts.py` **banned_phrases** — strip reasoning-leak openers ("Let me set the scene") — *thin (copy the list)*
- `modules/safe_eval.py` — only if the narrator ever evals dice/stat formulas from model/player text — *clean (verbatim)*
- `modules/desire.py` **three-fates model (design only)** — NPC want → ROUTE/CRYSTALLIZE(→real canon entity)/GAP(recur+escalate); "a want that doesn't cash out is dropped, not narrated" — *heavy (lift the ~40-ln router design)*

---

## SKIP (with why)
- `search_aggregator.py` — **outbound web (arXiv/Wikipedia/DDG) breaks the sealed wall.** Leave behind so nobody lifts it looking for "search".
- `modules/chunking.py` — **false-friend name**: a SOAR reflex-compiler, NOT text chunking. The chunker you want is `_chunk_text` in search.py.
- `generativity/dialectic.py` — redundant (dream_recombination arity-1); lift only `_SPAR_PROMPT` if you want an explicit critic.
- `interoception/pulse.py` (always-on daemon) — a sealed DM ticks once per player turn, synchronous; take the bounded-ring idea, not the thread.
- `somnus.py:2241` three-stage sleep — lift the every-Nth-cycle scheduling *pattern*; the Stage bodies are forge/vault-coupled.
- `linter.py:458-576` `_aggressive_clean`, `:309-332` structure_metrics — tuned to math/knowledge node shape; prefer prevention (stop-seqs + untrusted fence).
- `personality_chip/conversation_rupture.py` — tuned for an assistant being corrected, not a player steering a story.
- `static/tron/app.js` tile() window manager — over-engineered; a sidebar + one detail pane is far less code.

---

## RECOMMENDED ROUND-2 ADDITIONS (ranked)
1. **will_governor carried-tension homeostat** — the biggest step from "responds per turn" to "tells a shaped story."
2. **The full pacing loop** (body_budget.fold → derivative → appetitive → prospection) — nerves wired into one read-the-room→trend→appetite→forecast *brain*.
3. **moral.evaluate NPC-intent tension** — cheapest path to NPCs that feel *driven*, with legible model-free "because" hooks.
4. **desire three-fates router** — NPC wants that always point at real canon entities and escalate; the world gets its own agenda.
5. **detector registry continuity-guard** — contradiction/dangling/timeline/uninitialized checks keep a long campaign consistent.
6. **cross_rerank precision stage** — the quality dial once the canon vault is large.
7. **workflow YAML scene-templating** — script recurring beats as safe declarative YAML.
8. **autotelic MAP-Elites anti-repetition** — keeps a long narration from collapsing into one rhythm.

## Two greenfield gaps (build from scratch — not in Primarch)
- **transcript→canon consolidation body.** Every touching piece (sleep dispatcher, detector registry) gives the scheduling shell + advisory-check contract, but no working "promote a transcript event into a canon node / reconcile the world-bible" logic. *(loom's `consolidate.py` is a first cut of exactly this.)*
- **per-character NPC voice.** The voice pieces give ONE narrator voice; distinct per-character voices are net-new.

---

## UI / MODE ROADMAP (2026-08 — post card-rail)

The right panel is now story · continuity/detail · a salience-tiered card rail (World · Factions &
groups · Main · Antagonists · Side · Passing), with the node map as a pop-up. Next, in order:

1. **Mode presets** — a top-bar selector turning the depth dial + mechanics into the three
   *degrees of freedom* the player actually means:
   - **Power fantasy** (free reign) = depth 0 · mirror (world agrees) · mechanics off
   - **Writing a story** (freeform) = depth ~0.5 · mechanics off
   - **Real campaign** = depth ~1 · other (world resists) · mechanics on
   (depth already gates the referee, so it doubles as the referee-strictness knob.)
2. **Threads board + memories views** — center-pane tabs beside continuity. Keep the label
   **"threads"** (not "quest book"), but present the board quest-book-style; a **memories** tab
   surfaces consolidated canon as the record.
3. **Oracle-style assistant** — a non-diegetic OOC side-channel (answer meta questions, help craft
   the world via generate/consolidate/node-edit, tune the GM/config). HARD RULE: lives OUTSIDE the
   seal — reads canon + config, PROPOSES gated edits, never writes narration or bypasses the
   consolidation diode. A GM console, not a second narrator.

### DEFERRED — the full D&D layer ("real campaign", crunchy tier) — LATER
A genuine 5e-style layer: a character sheet with stats/HP/XP, stat-tied rolls, initiative, maybe a
battle map (cf. Friends & Fables). BIG and orthogonal to loom's narrative-memory spine — the light
"real campaign" mode (world-resists + impartial d20) already gets most of the feel. Revisit once the
narrative core + the three modes + the assistant are solid. Do NOT let it bloat the sealed core;
build it as an optional module gated behind the "real campaign" mode.
