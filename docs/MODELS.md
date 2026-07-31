# MODELS — what to serve loom on this box

From a live web sweep (2026-07-31, 6 agents, 38 candidates) for the target box:
**AMD RX 6700 XT, 12GB, RDNA2, llama.cpp Vulkan**, ~16k context, for an uncensored
DM/story-narrator. The local-model scene moves monthly — verify against the live
sources at the bottom.

## ⚠ Load-bearing hardware gotcha
On **RDNA2 + Vulkan, flash-attention is broken**: `-fa on` (or `auto` picking it)
falls back to CPU and craters token-gen ~35×. **`serve.sh` forces `--flash-attn off`
and keeps KV at f16.** Don't turn it on.

## Narrator (the voice) — pick one
| Model | GGUF repo | Quant | ~VRAM | Notes |
|---|---|---|---|---|
| **MN-12B-Mag-Mell-R1** ★ | `bartowski/MN-12B-Mag-Mell-R1-GGUF` | Q5_K_M | ~8.7 GB | Top pick: the most-cited 12B RP/story merge; minimal slop, strong worldbuilding; uncensored-by-tune (not lobotomized by abliteration → reads more in-character). ChatML, Temp ~1.25 / MinP 0.2. |
| Wayfarer-2-12B | LatitudeGames (Nemo-based) | Q5_K_M | ~8.7 GB | On-theme alt: a purpose-built adversarial GM — real failure, no plot armor. Most literally "true D&D" if enforced peril matters more than prose polish. |
| Llama-3.1-8B-Stheno-v3.4 | `Sao10K` / bartowski | Q5_K_M | ~5.7 GB | Lighter/faster (~55–70 tok/s est.), less depth. Good when VRAM's shared. |
| Cydonia-24B-v4.3 | `TheDrummer/Cydonia-24B-v4.3-GGUF` | IQ3_XXS | ~9.3 GB | Best brain, but only fits at a quant where its edge over a full-precision 12B evaporates. Really a 16 GB-tier model. |

## Archivist (clean JSON for consolidation) — pick one
| Model | GGUF repo | Quant | ~VRAM | Notes |
|---|---|---|---|---|
| **Llama-3.1-8B-Instruct** ★ | `bartowski/Meta-Llama-3.1-8B-Instruct-GGUF` | Q6_K | ~6.6 GB | The one with a real benchmark: 100% JSON parse / 95.7% schema compliance (Apr-2026). NB: "Llama 3.3 8B" doesn't exist — use 3.1. |
| Qwen3-4B-Instruct-2507 | `Qwen` / bartowski | Q6_K | ~3.3 GB | Tiny co-resident — fits beside the narrator on one GPU. Use the non-thinking `-2507` build. |

**The real lever:** llama-server's `--json-schema SCHEMA` / `-jf FILE` (GBNF grammar)
guarantees valid JSON from *any* model — so consolidation can be constrained even
without a dedicated archivist. Keep the schema flat (no regex). *Round-2: point loom's
`consolidate` at a server started with `--json-schema` matching the proposals shape.*

## Get it + point loom at it
```bash
# narrator (check the repo for the exact Q5_K_M filename):
huggingface-cli download bartowski/MN-12B-Mag-Mell-R1-GGUF \
  --include "*Q5_K_M*.gguf" --local-dir /home/Fenrir/sigilus/Models
MODEL=/home/Fenrir/sigilus/Models/MN-12B-Mag-Mell-R1-Q5_K_M.gguf ./serve.sh
```
Two models at once won't fit 12 GB — run the archivist as a second `serve.sh` only
while the narrator is stopped, or use the tiny Qwen3-4B co-resident with reduced `NGL=`.

## Honest uncertainty
tok/s figures are extrapolated from a *single* measured 7B RX 6700 XT benchmark —
verify with `llama-bench`. Leaderboard pages (UGI / EQ-Bench) are JS-rendered so exact
scores couldn't be pulled; rankings lean on RP-community consensus. Mag-Mell's best
coherence is ~10–16k, not guaranteed at full 16k. A few hyped names ("Qwen3.5-Opus-
Distilled", "Gemma 4 26B-A4B", a Heretic-abliterated Nemo) were unverifiable — treat
as rumor. **Freshest picks:** UGI Leaderboard · EQ-Bench Creative Writing ·
r/SillyTavernAI (weekly megathreads) · r/LocalLLaMA · TheDrummer / inflatebot HF pages.
