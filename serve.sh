#!/usr/bin/env bash
# loom's OWN sovereign model server — its own llama.cpp build, its own port, NO Primarch vector.
#
# loom runs a SELF-OWNED llama.cpp (built at ../loom-llama.cpp — see docs/BUILD_LLAMA.md) so nothing
# about it depends on Primarch's shared build or persona-server. Un-steered by default on :8090; serve
# with a loom control vector (e.g. the tone vector) by setting VECTOR=.
#
#   MODEL=/path/model.gguf ./serve.sh
#   VECTOR=steering/tone.gguf VECTOR_SCALE=2.0 ./serve.sh    # baseline tone steer
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LLAMA_SERVER="${LLAMA_SERVER:-$HERE/../loom-llama.cpp/build/bin/llama-server}"
MODEL="${MODEL:-/home/Fenrir/sigilus/Models/MN-12B-Mag-Mell-R1-Q5_K_M.gguf}"
PORT="${PORT:-8090}"
NGL="${NGL:-999}"          # full GPU offload; lower to share VRAM, 0 for CPU-only
CTX="${CTX:-16384}"
FA="${FA:-off}"           # RDNA2 + Vulkan: flash-attn is BROKEN — keep off (else ~35x CPU fallback)
VECTOR="${VECTOR:-}"                    # optional control vector, e.g. steering/tone.gguf
VECTOR_SCALE="${VECTOR_SCALE:-1.0}"     # base scale (loom overrides per-turn via the patched server)
VECTOR_LAYERS="${VECTOR_LAYERS:-12 28}" # inclusive layer range

[[ -x "$LLAMA_SERVER" ]] || { echo "!! llama-server not found at $LLAMA_SERVER — build loom's (docs/BUILD_LLAMA.md)" >&2; exit 1; }
[[ -f "$MODEL" ]]        || { echo "!! model not found at $MODEL (set MODEL=/path/to/model.gguf)" >&2; exit 1; }

VEC_ARGS=()
if [[ -n "$VECTOR" ]]; then
  [[ "$VECTOR" = /* ]] || VECTOR="$HERE/$VECTOR"
  VEC_ARGS=(--control-vector-scaled "$VECTOR:$VECTOR_SCALE" --control-vector-layer-range $VECTOR_LAYERS)
  echo "  + control vector: $(basename "$VECTOR") @ $VECTOR_SCALE (layers $VECTOR_LAYERS)"
fi

# VRAM preflight: two full-offload 12B servers won't fit a 12GB card.
if ss -tlnp 2>/dev/null | grep -q '127.0.0.1:8080'; then
  echo "note: something serves :8080 (likely Primarch's persona-server) — a 12GB card can't hold two"
  echo "      full-offload 12Bs; stop it, or run loom's with reduced NGL= (partial) / NGL=0 (CPU-only)."
fi

echo "loom-server → $(basename "$MODEL") on 127.0.0.1:$PORT  (loom's own build, ngl=$NGL ctx=$CTX)"
exec "$LLAMA_SERVER" -m "$MODEL" --host 127.0.0.1 --port "$PORT" \
  -ngl "$NGL" --ctx-size "$CTX" --flash-attn "$FA" --reasoning-budget 0 --parallel 1 "${VEC_ARGS[@]}"
