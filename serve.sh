#!/usr/bin/env bash
# loom's OWN sovereign model server — NO Primarch control vector, its own port.
#
# This is what decouples loom from the mind: the shared :8080 server is Primarch's
# persona-server and applies the counterpart control-vector to everything. loom runs
# its own llama-server here, un-steered, on :8090.
#
# Swap models by setting MODEL=; everything else has sane defaults:
#   MODEL=/path/to/rocinante-12b.Q4_K_M.gguf ./serve.sh
set -euo pipefail

LLAMA_SERVER="${LLAMA_SERVER:-/home/Fenrir/sigilus/llama.cpp/build/bin/llama-server}"
MODEL="${MODEL:-/home/Fenrir/sigilus/Models/gemma-4-12B-it-QAT-Q4_0.gguf}"
PORT="${PORT:-8090}"
NGL="${NGL:-999}"          # full GPU offload; lower to share VRAM, 0 for CPU-only
CTX="${CTX:-16384}"
FA="${FA:-off}"           # RDNA2 + Vulkan: flash-attn is BROKEN — 'on'/'auto' can fall to CPU (~35x slower). Keep off.

[[ -x "$LLAMA_SERVER" ]] || { echo "!! llama-server not found at $LLAMA_SERVER (set LLAMA_SERVER=)" >&2; exit 1; }
[[ -f "$MODEL" ]]        || { echo "!! model not found at $MODEL (set MODEL=/path/to/model.gguf)" >&2; exit 1; }

# VRAM preflight: two full-offload 12B servers won't fit a 12GB card.
if ss -tlnp 2>/dev/null | grep -q '127.0.0.1:8080'; then
  echo "note: something already serves :8080 (likely Primarch's persona-server)."
  echo "      a 12GB card can't hold two full-offload servers — stop that one first,"
  echo "      or run loom's with reduced NGL= (partial) or NGL=0 (CPU-only)."
fi

echo "loom-server → $(basename "$MODEL") on 127.0.0.1:$PORT  (ngl=$NGL ctx=$CTX, NO control vector)"
exec "$LLAMA_SERVER" -m "$MODEL" --host 127.0.0.1 --port "$PORT" \
  -ngl "$NGL" --ctx-size "$CTX" --flash-attn "$FA" --reasoning-budget 0 --parallel 1
