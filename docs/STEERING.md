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
