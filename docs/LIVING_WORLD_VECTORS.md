# Loom Living-World Control Vectors — the buildable map

## 1. Architecture overview

Loom already runs the whole thesis at N=1: `tone.py` maps context (world genre + place `tone:` + the tension homeostat) to one signed scalar, clamped to a coherent band (`FLOOR=-5.0, CEIL=3.0`), sent per-turn as `control_vector_scale` on `llm.chat()` and re-applied by loom's patched `../loom-llama.cpp` (`patches/dynamic-control-vector-scale.patch`) before each generation — safe only under `--parallel 1`. The full system is that primitive generalized along four separated concerns: a **vector library** (one authored `steering/<axis>.gguf` per axis, each from its own clean contrastive corpus), feeding a **weight engine** (per-axis pure functions turning the already-threaded signals — tension, location tone, beat, reputation, depth — into a target intensity, smoothed turn-to-turn toward that target with per-trait decay-to-baseline, so a *trait* is a response **curve**, not a static scalar), feeding a **composition layer** (collapse the per-axis weights into what the wire actually accepts), feeding **application** (the existing `control_vector_scale` per-request path). The load-bearing truth that shapes every phase: the server holds exactly **one** summed `cvec_base` and rescales it by **one** float — so "composition" is either done at `serve.sh` launch time (llama.cpp already sums stacked `--control-vector-scaled` flags into one blob) or offline in Python (pre-sum raw tensors into one served preset), and true independent per-request per-axis weighting is a *second* C++ patch, deferred until there are several judged vectors that actually need to vary independently in the same turn.

## 2. Phased roadmap

Sequenced cheapest-proof-of-thesis first; the two architecture-changing phases (real multi-vector composition, per-character sub-calls) are deferred behind an empirical coherence gate rather than assumed to work.

---

**Phase 0 — Weight engine + axis-switching (no new vector) · ✅ MVP**
*Felt result:* the one working tone axis becomes visibly *alive* — the register moves with the scene on a legible curve you can see and tune, not buried in `_bias()` arithmetic.
*Builds:* refactor `tone.py`'s `scale()` into a small `steer.py` with a per-axis `weights()` + a `compose()` that (for now) returns one scalar; a `WeightState` dict (mirrors `_tension`) holding the smoothed per-axis value; an EMA smoothing+decay rule reusing `_tension`'s decay machinery; a `signal adapter` that packages the already-computed signals once per turn; an offline **curve-preview harness**; a `/api/steer_debug` read-only endpoint + a live weight-bar readout in `static/index.html`.
*Effort:* S–M (mostly refactor of proven code).
*Unlocks:* the abstraction every later phase rides on; telemetry for tuning; the authoring UI. **This is the MVP** — it delivers felt aliveness against the *current* server with zero extraction and zero coherence risk.

**Phase 1 — Second orthogonal axis (extraction + sweep) · the first real test**
*Felt result:* scenes gain a genuinely second dimension of mood (e.g. dread that's independent of warmth — a cozy room that's *wrong*).
*Builds:* author ~150–250 matched ChatML pairs for **DREAD** (same-scene skeletons, TONE held constant), extract via `llama-cvector-generator`, run a layer×scale sweep; a `sweep.py` grid+judge harness (repetition-loop detector is the cheap deterministic tell that already caught brevity); an `extract.sh` wrapper + a GPU-logistics runbook; the anti-correlation cosine probe between `tone.gguf` and the new vector at layers 12–28.
*Effort:* M (S code, but real corpus-authoring + a coordinated GPU session).
*Unlocks:* proof that a second axis is separable and coherent *before* any composition machinery. DREAD is chosen because it slots onto the **existing tension homeostat** with zero new plumbing. **If bipolar levity works** (test DREAD+PLAYFULNESS as one signed axis), you land at TONE + LEVITY = 2 axes for the price of ~1.5.

**Phase 2 — Composition (offline pre-sum → static blend) · ⚠️ diminishing-returns line begins here**
*Felt result:* two axes active at once in a scene (e.g. grim *and* dreadful), where dominant-axis switching alone couldn't express it.
*Builds:* an offline numpy pre-sum of two `.gguf` tensors into one served preset (answers the ceiling question with **zero C++**); OR extend `serve.sh` to stack `--control-vector-scaled` flags (llama.cpp sums at launch); a **composability harness** (fixed 5–10 scene battery run at realistic *combined* runtime scales — TONE solo, DREAD solo, TONE+DREAD summed); a ceiling manager (fixed per-axis sub-budget, shrunk once 2+ axes are live).
*Effort:* M.
*Unlocks:* the first honest answer to "how many axes really compose." **This is where returns start diminishing** — the STEERING data (tone shatters past +4.5; brevity into `11 11 1 1` loops at 1.6) says summed vectors shatter *below* individual sweet spots. Ship only if the harness proves 2 axes hold. Most of the "alive" feeling comes from weights moving over **time** (Phase 0), not simultaneous blending.

**Phase 3 — Server-side N-vector independent weights · defer**
*Felt result:* each axis dialed independently per turn (not one scalar over a static blend).
*Builds:* the second C++ patch — N named unit `cvec_base` entries, a `control_vector_scales: {name: float}` map, sum-then-apply server-side (mirrors the fork's own `llama_set_adapters_lora(adapters[], scales[])` precedent, same 3 files).
*Effort:* L (real C++ surgery on an already hand-patched fork; re-verify `--parallel 1` safety).
*Unlocks:* continuous independent weighting — **only worth it** once 3+ judged single-axis vectors exist AND a concrete scene needs two varying independently in one turn. Given the composability ceiling, this buys flexibility, **not** safety margin. Do not build speculatively.

**Phase 4 — Per-character steering · defer hard, spike first**
*Felt result:* one NPC carries an affect the rest of the scene doesn't share.
*Builds:* a throwaway **sub-call cost/quality spike** first (3 calls for a 2-NPC scene, blind-rated vs today's single call) — because a control vector tints the *whole* forward pass, so per-character = separate steered sub-calls (Nx calls, Nx latency under `--parallel 1`, re-architects `narrate.py`'s single-call loop). If pursued: a focus-character detector (default None-on-ambiguity), then either a two-pass focus-rewrite (splice risk) or full per-actor generation (reuses `worldturn.py`'s proven Nx-call pattern; fence model output via `prompt_security`).
*Effort:* L.
*Unlocks:* true per-character affect — **but the spike may show prompt-only per-character voice (`character.voice_clause`, already shipped) is already enough.** `depth.py` is direct in-repo proof that a "living world" dimension was solved with pure prompting at zero vector cost.

**Phase 5 — Learned weights · speculative/optional, not roadmap-committed**
*Felt result:* curves fit from playtest data instead of hand-authored.
*Effort:* L. *Unlocks:* marginal gains only. No training data exists until Phase 0 telemetry runs for a long stretch; a solo project likely never accumulates enough signal to beat hand-tuned curves. Explicitly the point of diminishing returns.

## 3. Consolidated build list by phase

| Phase | Build | Effort |
|---|---|---|
| **0 (MVP)** | `steer.py` — generalize `tone.py` (`weights()` + `compose()`) | S |
| 0 | `WeightState` — persistent per-trait smoothed scalar (mirrors `_tension`) | S |
| 0 | Smoothing/decay rule (EMA + per-trait snap-threshold, reuse `_tension` decay) | S |
| 0 | Signal adapter — package existing state into one `ContextSignals` struct | S |
| 0 | ResponseCurve — per-axis piecewise/threshold spec in a data file | M |
| 0 | Curve-preview harness (offline, no GPU) | S |
| 0 | `config.py` `steer`/`steer_axes` keys + `web.py` GET/POST arms + `/api/steer_debug` | S |
| 0 | `static/index.html` steering panel (live weight bars) | S |
| **1** | DREAD corpus (~150–250 pairs, TONE held constant) + extraction | L (authoring) |
| 1 | `sweep.py` — layer×scale grid + repetition-loop judge | M |
| 1 | `extract.sh` wrapper + GPU-logistics runbook | S |
| 1 | Anti-correlation cosine probe (offline) | S |
| 1 | (optional) PLAYFULNESS as bipolar levity axis with DREAD | M |
| **2** | `compose.py` — offline N-vector pre-sum (GGUF reader) | M |
| 2 | `serve.sh` multi-`--control-vector-scaled` stacking | S |
| 2 | Composability harness (combined-scale scene battery) | M |
| 2 | Ceiling manager (fixed sub-budgets, shrink when 2+ live) | M |
| **3** | Server patch: N named vectors + scale-map | L |
| **4** | Sub-call cost/quality spike (throwaway) | M |
| 4 | Focus-character detector | S |
| 4 | Two-pass focus-rewrite OR per-actor sub-call generation | M / L |
| **5** | Learned/adaptive weights | L (speculative) |

## 4. Cross-cutting decisions

1. **How does a multi-axis weight dict become the one scalar the server accepts?** → **Offline pre-sum / static launch-blend first (zero C++), one live scalar riding on top.** Escalate to a server-side scale-map (Phase 3) only after there are 3+ judged vectors and a concrete scene needs independent per-turn variation. The wire only accepts one float over one blob — respect that until the value is proven.

2. **Rules-authored curves or learned?** → **Rules.** No labeled "correct intensity" signal exists; loom is zero-dependency/sealed by design; ~5–10 threshold rules per trait are easier to red-team than a regressor. Revisit only if hand curves demonstrably fail after several axes are live.

3. **Bipolar single axis vs two independent axes for DREAD/PLAYFULNESS?** → **Start bipolar** (one signed "levity" axis) — half the authoring cost, and the states are genuinely mutually exclusive in a coherent scene. Fall back to two gated unipolar axes only if extraction shows the "more dread" and "more playful" directions aren't antiparallel in activation space (empirical, can't be predicted).

4. **Which second axis?** → **DREAD** (drivable off the *existing* tension homeostat, zero new plumbing, sharpest contrast to author). **Not** urgency/calm (collapses onto what tension already drives via tone) and **not** brevity-shaped diffuse axes. Formality/register is the natural *third* (ties to the unused reputation signal, maximally orthogonal to mood).

5. **Per-trait smoothing or one global rate?** → **Per-trait k + per-trait snap-threshold.** This is literally where "the stoic cracks for a beat" lives — a slow reputation-driven drift and a sudden betrayal-beat spike need different dynamics. A global constant defeats the core thesis.

6. **Does `depth.py`'s mirror↔other axis become a vector?** → **No — leave it a prompt clause.** It already works with zero coherence cost; converting it spends the composability budget for unclear gain. Pick a *net-less* new axis (DREAD) so the composition test reads cleanly.

## 5. Honest limits + kill-criteria

- **Composability ceiling is real and UNMEASURED for sums.** The only in-repo data is one vector alone: tone works to +4.5 then shatters; brevity degenerates into `11 11 1 1` loops at scale 1.6. There is **zero** existing evidence about summed multi-vector behavior on Mag-Mell. Do not assume the ~3–4 rule of thumb; the composability harness must run *before* committing to a 3-axis roadmap. **Kill:** if TONE+DREAD summed can't hold coherence at their combined realistic scales, stop at axis-switching (Phase 0) and ship DREAD as a swap-in, not a blend.

- **Not every trait is vector-shaped.** Brevity is proof (well-authored 20-pair corpus, still weak/diffuse). **Kill per axis:** if a new axis trims <~15% of its intended effect before shattering, or its anti-correlation cosine with an existing axis is high (it's the same axis renamed) or strongly negative (they cancel), shelve it as a documented dead end (like `brevity.gguf` sitting unwired) — not a failure to fix harder.

- **Per-character cost is Nx, and hybrid may beat full.** A control vector tints the *entire* forward pass; per-character = separate sub-calls, sequential under `--parallel 1` (no concurrency — 12GB fills with one 12B), turning a ~10–20s narration into 40–80s for a 3–4 NPC scene. `character.voice_clause` + prompt already gives per-character voice for free. **Kill:** run the sub-call spike first; if blind raters can't distinguish the stitched multi-call version from today's single call, per-character-via-vector is killed outright.

- **Corpus authoring is the recurring bottleneck, not code.** The composition math scales to N trivially; each axis is a fresh hand-curated corpus + GPU sweep. The library's practical size stays ~3–4 for a long time regardless of what the code supports. Model-assisted drafting still needs a human minimal-pair curation pass or it extracts a confounded direction.

- **No automated shatter detector exists.** Every STEERING judgment was human-eyeballed. Adaptive per-scene weights need the repetition-loop detector wired as a runtime **clamp** (reject/scale-down a combination that would shatter) or a bad context-driven weight silently ships broken prose to a player.

## 6. Recommended first build

**Refactor `tone.py` into `steer.py` with a smoothed-curve weight engine — Phase 0, no new vector, no extraction, no GPU session.** Concretely: factor `scale()` into a per-axis `weights()` function + a `compose()` that still returns the single scalar `narrate.py` already threads through `llm.chat(control_vector_scale=...)`; add a `WeightState` dict and an EMA-with-decay update reusing `_tension`'s machinery so the tone scalar *smooths and decays* turn-to-turn instead of snapping; add `/api/steer_debug` + a live weight-bar readout in `static/index.html`. This ships felt aliveness on the *one proven axis* against the *current* server, builds the abstraction and telemetry every later phase depends on, and carries zero coherence risk — earning the right to spend a coordinated GPU session on DREAD (Phase 1) only after the engine is real and legible. Migrate the four `tone_steer` references together (`config.py`, `narrate.py` ×2, `web.py`, `index.html` `s_tone`) or the toggle breaks silently — `config.load()` merges JSON with no schema validation.

*Grounding: verified against `~/Proj/loom/loom/tone.py`, `serve.sh`, `narrate.py:90/110/156/197/228`, `llm.py:48/62`, `config.py:47`, `web.py:114/304`, `static/index.html:396/404`, `depth.py`, `steering/` (tone.gguf, brevity.gguf + corpora), and `docs/STEERING.md` (cozy −5…dread +3, shatter >+4.5; brevity ~15% trim then loops at 1.6).*