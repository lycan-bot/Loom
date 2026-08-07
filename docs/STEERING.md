# Steering loom's narrator — beyond the prompt

## The problem, stated honestly

loom's model (MN-12B-Mag-Mell-R1, a wild RP model) **does not follow behavioral directives**. Told
to write "1-2 sentences," it writes three paragraphs. So the prompt cannot make it concise, nor
reliably shift its register (grim ↔ cozy, ornate ↔ spare).

The token cap "worked" only by truncation — and **truncation is not concision**. A capped narration
is a whole thought guillotined mid-breath; trimming to the last sentence just tidies the stump. The
lesson: **length and register must be *generated*, not imposed.** We need to change what the model
*produces* — a whole, smaller (or differently-toned) thought — which is a decoding- or weights-level
intervention, not a prompt.

This is exactly the territory Primarch already works in (its persona control vector). loom
deliberately runs **un-steered** on its sovereign `:8090` — so anything here is an **opt-in loom
capability** (loom's *own* grammar/vector), never a reuse of Primarch's persona vector.

---

## The levers (all supported by loom's llama.cpp on `:8090`)

### 1. Control vectors — the behavioral lever ★ the real answer

Add a steering direction to the model's hidden states at inference
(`--control-vector-scaled <vec.gguf>:<scale>` + `--control-vector-layer-range`). The vector is a
direction in activation space extracted from **contrastive prompt pairs** — e.g. verbose↔terse,
purple↔plain, calm↔dread narration.

- **How we'd make one:** `cvector-generator` (in loom's llama.cpp build) or `repeng` — feed N pairs
  of narration differing only on the axis, extract the mean-difference direction per layer.
  **Primarch already proved this on this exact model family** (gemma-4 / the 12B: the Tier-B
  counterpart vector, 47 dirs, the gemma-4 `cvector-generator` off-by-one fix). The toolchain exists.
- **For LENGTH:** a *brevity* vector — steer toward the terse pole and the model **naturally writes
  shorter *complete* thoughts.** This is the clean fix to the whole complaint: concise by nature, not
  cut off.
- **For REGISTER:** a *tone* vector (dread↔cozy, ornate↔spare) — the loom analogue of the persona
  vector, and it **composes with the authored `genre`** (setting.py). A "cosmic-horror" world could
  carry a dread-steered narrator.
- **Pros:** genuine behavioral steering; whole thoughts; a continuous strength dial (the scale);
  composable. **Cons:** needs contrastive data + one extraction run per axis; subtle axes need a
  layer×scale sweep to tune (Primarch's playbook); a vector is model-specific.

### 2. Grammar / GBNF — the structural lever (fast to prototype)

Constrain generation to a grammar (loom already does this for JSON via `response_format`). A grammar
that permits **at most N sentences** makes the model write *complete* sentences and stop at the
limit — it ends **cleanly on a whole thought**, just fewer of them. Unlike the token cap, nothing is
severed.

- **Pros:** a hard length ceiling that ends cleanly; **no training**; deterministic; immediate.
- **Cons:** a GBNF that permits rich prose *and* counts sentences is fiddly (dialogue, quotes,
  abbreviations, ellipses all confuse "what is a sentence"); can feel mechanical; only governs
  length/structure, not tone.
- **Verdict:** the cheapest thing to *try first* — if grammar-bounded length reads as "concise"
  rather than "clipped," it may be enough on its own.

### 3. Logit bias — the crude lever (mostly a trap for length)

Per-token bias via the API. Biasing the **EOS token up** to end sooner is **the same truncation
flaw** — it stops the model early = shut-up-mid-thought. So logit-bias-for-length is **out**. Its
legitimate use is narrow: down-weight a specific verbal tic or filler word the model overuses. Cheap,
no training, but blunt.

### 4. Model choice / LoRA — the heavier levers

- **Swap the model:** a more instruction-following RP model would simply obey a length/register
  directive — sidesteps steering entirely, at some cost to Mag-Mell's "wild bard" flavor. The escape
  hatch if steering proves fussy.
- **LoRA finetune** for brevity/register: heaviest, most precise. **Blocked on this box** — it can
  *serve* LoRA (Vulkan) but not *train* it (CPU-only torch). Deferred.

---

## Recommendation

**For length (the actual complaint):**
1. **Prototype a sentence-cap GBNF first** — no training, immediate, ends cleanly. See if it feels
   like concision or like a straitjacket.
2. **If we want behavioral (not structural) control, extract a brevity control vector** — the clean,
   dial-able "concise by nature" fix, on Primarch's proven toolchain.
3. Logit-bias-EOS is off the table (repeats the truncation flaw). Model-swap is the escape hatch.

**For register (bonus, ties to `genre`):** a tone control vector per axis, composed with the authored
world genre — loom's own persona-vector-lite.

Both stay opt-in and sovereign: loom's *own* grammar/vector on `:8090`, never the persona vector.

## First move

Two cheap experiments, cheapest first:
- **(a) GBNF sentence-cap** — write a grammar that bounds narration to ~N complete sentences, wire it
  into `llm.chat` (like the JSON grammar), try it live. Fast; reversible; no training.
- **(b) Brevity control vector** — assemble ~30–50 verbose↔terse narration pairs, run
  `cvector-generator`, serve it composed into loom's serve.sh, sweep layer×scale. Slower; the real
  behavioral lever.

Do (a) to learn what "bounded length" feels like, then decide whether (b) is worth the extraction.

---

## Results — the brevity experiment (2026-08-07)

The **pipeline is proven end to end**: `llama-cvector-generator` on the Mag-Mell GGUF over the Vulkan
GPU (`steering/brevity_{positive,negative}.txt`, 20 matched terse↔verbose pairs, `--method pca`)
extracts a 40-layer direction (`steering/brevity.gguf`, ~800KB) in a few minutes — **no CPU-hours**,
unlike repeng. Served via `--control-vector-scaled brevity.gguf:<s> --control-vector-layer-range`.

But the honest finding: **brevity is a WEAK axis to steer.** A fixed prompt swept:

| scale (layers 12–28) | words | quality |
|---|---|---|
| 0 (baseline) | 265 | normal |
| 1.0 | 230 | coherent, *mild* nudge |
| 1.6 | — | **shatters** — a sentence, then blank-line collapse |
| 2.0 (layers 18–30) | — | coherent start → `11 11 1 1…` degeneration |

So at coherent scales the vector only trims ~15%, and pushing harder doesn't make it terser — it
**breaks the model into degenerate loops.** The window between "mild" and "broken" is narrow, and
tighter/later layers didn't sharpen it.

**Why:** "write less" is not a clean semantic direction — verbosity is diffuse, entangled with the
whole generation process, so steering it hard destabilizes coherence. Control vectors shine on strong
**semantic/persona** axes (Primarch's verify↔sycophant steered beautifully); a stylistic *quantity*
like length is exactly the wrong shape for them.

**Takeaway:** vector-steered brevity is a *modest* tool (~15% at scale ≈1.0), not the strong lever we
wanted. The better bet is **register/tone** (dread↔cozy, ornate↔spare) — a strong semantic axis where
vectors excel, and which composes with the authored `genre`. That is the experiment worth running next.

---

## Results — the tone experiment (2026-08-07) ★ this one works

A **bipolar dread↔cozy** vector (`steering/tone_{dread,cozy}.txt`, 18 matched grim/warm pairs →
`steering/tone.gguf`) genuinely swings the whole register on **one signed scalar**, coherently:

| scale (layers 12–28) | tone |
|---|---|
| **+3** | strong dread — *"eerie silence… bedsheets stained as if a struggle… hairs on the back of your neck"* |
| **+2** | eerie, uncanny — *"a shiver down your spine… tapestries of dark rituals… an otherworldly glow"* |
| **0** | neutral |
| **−5** | warm/cozy — *"a cozy, inviting atmosphere… breakfast for two… a plush sofa invites you to sink in"* |
| **> +4.5** | shatters |

It **works** where brevity didn't — because *mood is a strong semantic axis*, the shape control vectors
are built for (cf. Primarch's verify↔sycophant). It is **asymmetric** (dread emerges near +2.5, cozy
needs ~−5, since a generic scene already leans slightly bleak) — so the usable dial is roughly
**cozy −5 … 0 … dread +3**, with a hard ceiling past +4.5.

## Making tone follow the setting (Wolf's question)

Tone is not one setting — a magic university is warm/wondrous, its monster-infested Fens are grim, a
summoned-demon familiar is uncanny. So tone must be a **context-driven scalar**, not a fixed vibe.
The signed scale above IS that scalar; drive it from signals loom already has:

1. **Genre baseline** (`setting.py`) → a default scale per world (cosmic-horror ≈ +2.5; cozy fantasy ≈
   −3; the magic-university ≈ slightly warm).
2. **Per-location tone** — a `tone:` on place nodes overrides it (the library → cozy; the Blighted
   Fens → dread), so the register shifts as the player moves.
3. **The tension homeostat** (`pacing.py`, already tracks cozy↔grim per turn) → nudge the scale toward
   dread as danger rises, back toward calm as it decays. Automatic contextual mood.

**The honest catch:** llama.cpp applies the control vector at **server launch**, not per request — so
true per-turn scale modulation needs runtime control-vector adjustment (llama.cpp may not expose it;
Primarch's `persona_vector.py` "served control vector" mechanism is the lead to investigate). So:

- **Achievable now:** a **per-campaign baseline tone** — serve the tone vector at a scale matched to
  the world's genre (set in serve.sh from config). The whole campaign's register matches its setting;
  per-scene shifts ride on top via the prompt (`setting`/tension clauses).
- **Frontier — BUILT ★ (2026-08-07):** per-turn scale driven live by location + tension, the fully
  dynamic "tone follows the scene." loom got its **own patched llama.cpp** (`../loom-llama.cpp`,
  `patches/dynamic-control-vector-scale.patch`) adding a per-request `control_vector_scale` — the
  vector is kept at unit scale and re-applied via `llama_set_adapter_cvec` before each generation,
  safe because the server runs `--parallel 1`. `tone.py` maps genre + location `tone:` + the tension
  homeostat → the scale; `narrate` sends it each turn (gated by `tone_steer`). Proven live end to
  end: same world/session/server, the Hearth read warm (−3.7), the Blighted Fen read grim (+1.3), no
  restart. Run it: `VECTOR=steering/tone.gguf ./serve.sh` + `tone_steer=true`.

  ⚠ The patch is only safe under `--parallel 1` (one active generation on the shared context);
  serve.sh sets that. A `--parallel >1` server would race the re-applied vector.
