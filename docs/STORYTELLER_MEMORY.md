# Loom — The True Storyteller Memory Map

*One consistent canon, remembered and accurately referenced. General ideas held longest; word-for-word not held in the head — but the pages are all still there, and any reference can be looked back on and retrieved exactly. No repetition, no confabulation, the whole story held consistent moving forward.*

Synthesized from ten mapped dimensions, checked against loom's real files (`loom/*.py`, `serve.sh`, `campaigns/`). Every load-bearing claim verified: dead embed branch (`use_embeddings:False`, no `--embedding` in serve.sh, `retrieve.py:80` re-embeds all docs per call), the 1500-char world-round dump (`worldturn.py:99`), the brittle `where`/`_location` string compare (`worldturn.py:153`), the diode chokepoint (`consolidate.approve`), `transcript.append(**extra)`, guard's `DETECTORS` registry, and real scale (5-20 nodes / 23-40 lines per campaign). Diode-respecting throughout.

---

## 1. Architecture — the tiered memory model

Loom is a **human writer's memory**, not a RAG stack: hold the arc in your head, let exact wording fade, keep every page on the shelf to look up when a detail matters. Loom has both ends of that curve; the middle and the shelf-index are the gap.

**Five tiers (handoff order):**

| Tier | Store (real file) | Lifespan | Trust | State today |
|---|---|---|---|---|
| **0. Pages** | `transcript.jsonl` | forever, verbatim | ground-truth record (not narrated from) | written; **read only as a 16-line tail** — unindexed |
| **1. Episodic index** | *NEW* | forever, derived | advisory, retrieval-only | **does not exist** — the missing rung |
| **2. Working memory** | `state.json._memory` | rolling, regenerated | advisory (= recent window) | built: 10 facts + recap, every 4 turns |
| **3. Canon** | `canon/*.md` | permanent, **operator-gated** | the one narrated truth | built; grows unbounded, never re-compressed |
| **4. Structured facts** | `state.json`, `threads.json`, `_rep` | permanent | canonical predicates | thin: no turn index, no `_facts` slots, no event ledger |

**Turn flow:** player input → `retrieve.py` grounds in canon (+ semantic when armed), plus `scene_memory` recap + 16-turn window; **[NEW]** a reference cue ("as X said", "remember when") triggers a **verbatim** recall from the episodic index, fenced as advisory. `narrate.py` assembles — canon is truth, everything else is separately fenced, "not an instruction." The 12B turn is appended (the page is kept), deterministically extracted (entities/events/turn#), and checked (anti-repetition/support). Then **the diode**: `loom consolidate` — the operator blesses each proposal into canon.

**The diode is the spine and already holds.** The rule every phase obeys: raw transcript retrieval is advisory-tier — surfaced verbatim on explicit reference, never auto-injected every turn, never promoted to canon except through `consolidate.approve()`. A verbatim quote of an actual past turn is categorically safe; preferring the model's own *summaries* over the record is the collapse case.

---

## 2. Phased roadmap

- **Phase 0 — Turn on what's built [S]** · *no deps.* Flip `use_embeddings`; stand up a **second CPU-only embed server** on its own port; **fix `embed_url`** (defaults to the narrator's `:8090` — silently wrong); add a **doc-vector cache** (content-hash keyed, so `retrieve()` embeds only the query, not all canon, per turn); add a **reachability probe** (logs "degraded to lexical" once instead of swallowing per turn). *Felt:* synonym callbacks work; per-turn re-embed stops. *Guard:* don't flip embeddings on without the cache.

- **Phase 1 — Ground the world-round [S]** · ⭐ **MVP.** Replace `worldturn.py:99`'s 1500-char dump with **per-group `retrieve()`** (query = names + `because` + location); same fix to `sleep.py`. Add a *"`wants` is not an event"* prompt line. Fix the co-location bug (`worldturn.py:153` raw string compare): **enum-constrain** the `where` output + route both sides through a place normalizer (`consolidate._norm`). *Felt:* the "Fáelán's testimony" class of confabulation closes. Needs no new files, no model call, not even Phase 0.

- **Phase 2 — Episodic index [M]** · ⭐ **MVP keystone** · *deps: P0 for embeddings.* Add a `_turn` **monotonic counter** (absent today; the load-bearing primitive). Build a **transcript index** (`recall.py`, one entry per **turn-pair**, at write time, reusing `retrieve.py`'s `_bm25`/`_rrf`/`_cosine`). Expose **`/api/recall` + `loom recall`** + a **`loom reindex`** backfill. Wire **retrieve-on-reference** into `narrate` behind a keyword prefilter, injecting top 1-2 verbatim passages **separately fenced**. *Felt:* "what exactly did the innkeeper say?" returns the actual line.

- **Phase 3 — Per-turn extraction [M]** · *deps: P2.* `entities.jsonl` (deterministic — hoist `salience.py`'s per-name regex to run once/turn) + `events.jsonl` (byproduct plumbing). Hoist `salience.classify` off its full-file scan. Model-judgment items **ride `scene_memory`'s existing cadence call** — no third per-turn model call. *Felt:* the system knows who/what per turn; recurring `canon_misses` become a confabulation signal.

- **Phase 4 — Consistency [M]** · *deps: P3.* A `_facts` structured frontmatter layer (diffable truth). New `guard.py` detectors (`dead_but_active`, `location_conflict`, `disposition_reversal`, `stated_vs_established`). A `_facts_log.jsonl` provenance trail. **Old-vs-new reconciliation** at `consolidate.approve()` (kill the silent `fm[k]=v`). A `contradicted_canon` verdict in `referee.py`. *Felt:* the "held consistent" half of the vision.

- **Phase 5 — Anti-repetition [S–M]** · *deps: P2 for the novelty ceiling only.* `repetition.py` (n-gram + imagery Jaccard vs. last ~6-10 turns, transplant `imagine._too_similar`); a **gentle** negative clause (aggressive ones cause STEERING.md's `11 11 1 1` collapse); **exclude canon names** (recurrence is continuity, not repetition); a `director.py` beat-history tie-break. *Felt:* no motif/beat loops.

- **Phase 6 — Timeline spine [M]** · *deps: P2, P3.* An `events` sibling in `consolidate`'s schema (turn-range-validated) → `episodic.jsonl`; optional `story_time` axis (best-effort, never forced); an `episodic.query()` helper + `timeline` detector; a **sleep/world-round hook** (off-transcript events). *Felt:* "when was that?" always resolvable, on two clocks.

- **Phase 7 — Compression [M–L]** · ⭐ **culmination** · *deps: P2, P6.* **Node compaction** (fail-closed, gated). **Hot/cold canon split** (per-turn cost tracks *active*-story size). **Salience-weighted distillation**. *Felt:* a 500-turn campaign stays as fast/coherent as a 5-turn one — the full loop composed, still diode-safe.

**MVP = Phase 1 + Phase 2** (grounded generation + retrievable pages). **Culmination = Phase 7.**

---

## 3. Build list by phase

- **P0:** embeddings flip + CPU embed server (S) · `embed_url` fix (S) · doc-vector cache (S) · reachability probe (S)
- **P1:** per-group `retrieve()` in worldturn+sleep (S) · `wants`-guardrail (S) · co-location enum+normalizer (S)
- **P2:** `_turn` counter (S) · transcript index `recall.py` (M) · `loom recall`/`/api/recall`/`reindex` (M) · retrieve-on-reference (M)
- **P3:** `entities.jsonl` extractor (M) · `events.jsonl` (S) · salience hoist (S) · cadence enrichment (S)
- **P4:** `_facts` frontmatter (M) · contradiction detectors (M) · `_facts_log.jsonl` (S) · reconciliation payload (M) · `contradicted_canon` (S) · `loom guard` CLI (S)
- **P5:** `repetition.py` (S) · avoid-clause (S) · beat-history (S) · motif ledger (M) · *deferred* `novelty()` (L)
- **P6:** `events` schema + validation (M) · `episodic.jsonl` (S) · `story_time` (M) · `query()` (S) · `timeline` detector (S) · off-transcript hook (S)
- **P7:** `compact_node` (M) · hot/cold split (L) · salience-weighted distillation (S) · adaptive `retrieve_k` (S)

---

## 4. Cross-cutting decisions

1. **Embed model runs where?** → A **second, small, CPU-only** server on its own port. The 12B isn't an embedder and already saturates the 12 GB card. *Fix `embed_url` or it silently no-ops.*
2. **One index convention?** → **One.** Reuse `retrieve.py`'s `_bm25`+`_rrf`/`_cosine` everywhere — never a second BM25.
3. **Transcript index = new gated store?** → **No** — a rebuildable read accelerator, structurally unable to write canon or auto-populate the prompt.
4. **Per-turn extraction deterministic or model?** → **Deterministic per turn (free); model judgment rides `scene_memory`'s cadence call.** No mandatory second per-turn model call.
5. **Which contradicting fact wins?** → **The operator, always** (auto-rules reintroduce the self-propagation risk the diode prevents).
6. **Recall every turn or on reference?** → **On reference**, behind a cheap keyword prefilter (reuse `referee.py`'s cue pattern).
7. **LLM contradiction detection?** → **Rule-based in `guard.py`; LLM only at the two judge points that already exist** (`referee`, `consolidate`). No third judge call path.

---

## 5. Honest limits + kill-criteria

- **The diode is a discipline, not a mechanism — re-verify every PR** with a CI grep: does anything import `transcript` inside `retrieve.py`, or feed transcript text into `embed()`/a canon write outside `consolidate.py`?
- **Embeddings may not earn their cost at loom's real scale** (20 nodes/40 lines; BM25 over proper-noun-dense text is near its ceiling). **Kill-criterion:** don't build embed co-residency/caching until a real log shows BM25 missing a node that *mattered* twice. Build the ablation logger first; let evidence trigger the spend. Cheap wins (scene_memory + guard + Phase-1 grounding) likely capture most of the value.
- **Retrieval can *hurt* at small scale** — `retrieve_k=8` over 8-30 nodes pulls nearly the whole canon in; an adaptive `retrieve_k` floor matters more than embeddings.
- **`_COS_FLOOR=0.5` / RRF `k=60` are unvalidated, vendored from another corpus** — re-validate before trusting.
- **Prompt-level steering is unreliable on Mag-Mell** (STEERING.md: directives ignored, aggressive ones collapse to `11 11 1 1`). Anti-repetition clauses are mitigation, not guarantee; the reliable lever is structural (`director` beat-history).
- **Compaction is permanent + lossy → fail-closed** (skip on any doubt), unlike `scene_memory`'s fail-soft.
- **Silent degradation is the quiet killer** — `llm.embed()` swallows exceptions → unlogged lexical fallback. The probe (Phase 0) is not optional.
- **Three append-only stores grow forever** (transcript, canon-on-merge, + provenance/event logs) — cap before shipping any new ledger.

---

## 6. Recommended first build

**Phase 1 — ground the world-round in retrieval.** *(S; touches `worldturn.py` + `sleep.py` only; ~15-line diff each; reuses `retrieve.retrieve()` + `retrieve_k` already in scope.)*

Highest value-per-effort on the map: it **directly closes the one reported bug**, needs **no new files, no new store, no new model call, and not even Phase 0** (lexical retrieval alone beats an arbitrary 1500-char alphabetical slice), and establishes the retrieval-grounding discipline every later generator inherits. Land the co-location `where`-enum fix in the same pass. **Then:** Phase 0 → Phase 2 — together the MVP: grounded generation + the pages made retrievable.

---

Full map written to `/tmp/claude-1000/-home-Fenrir-sigilus-Sigilus-merge/c4fa9f26-045c-4cdf-b040-5ee05dfbba78/scratchpad/loom_memory_map.md`. Real loom source is at `/home/Fenrir/Proj/loom/loom/` (note: this is a separate repo from the session cwd `Sigilus merge` — per your memory, loom is the standalone side project, not Primarch).