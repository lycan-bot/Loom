# Building loom's own llama.cpp

loom runs a **self-owned** llama.cpp so nothing about it depends on Primarch's shared build or
persona-server — loom is a sovereign, standalone project. The build lives at `../loom-llama.cpp`
(a sibling of the loom repo, NOT committed — it's a ~GB build tree); `serve.sh` points at it.

## Why our own build

Beyond isolation: it's the tree we **patch**. The frontier feature — per-turn dynamic tone (a control
vector whose scale follows the scene) — needs a small server patch (`control_vector_scale` per
request), and we can only patch a build we own.

## Reproduce

```bash
# 1. clone the source (from the known-good local build, same commit)
git clone /home/Fenrir/sigilus/llama.cpp /home/Fenrir/Proj/loom-llama.cpp
cd /home/Fenrir/Proj/loom-llama.cpp

# 2. the UI gotcha (see below) — reuse the working build's already-downloaded UI assets
mkdir -p tools/ui/dist
tar xzf /home/Fenrir/sigilus/llama.cpp/build/tools/ui/dist.tar.gz -C tools/ui/dist

# 3. configure (Vulkan, Release, ccache; no curl, no UI build, no HF fetch)
cmake -B build -DGGML_VULKAN=ON -DGGML_NATIVE=ON -DCMAKE_BUILD_TYPE=Release \
      -DGGML_CCACHE=ON -DLLAMA_CURL=OFF -DLLAMA_BUILD_UI=OFF -DHF_ENABLED=OFF

# 4. build ONLY the server, CPU-capped (Wolf is CPU-sensitive — never -j 12 uncapped)
taskset -c 0-3 nice -n 18 cmake --build build --target llama-server -j 4
```

ccache (shared with the existing build) makes this mostly cache hits — minutes, not a cold compile.

## The UI gotcha (why step 2 exists)

`llama-server` hard-links `llama-ui`, which provisions the bundled web UI by (1) pre-built assets in
`tools/ui/dist`, else (2) an `npm run build` (needs Node), else (3) downloading `dist.tar.gz` from a
HuggingFace bucket (needs network). In a disconnected/no-npm build all three fail and the `llama-ui-embed`
step FATAL-errors. loom doesn't use llama.cpp's web UI (it serves its own on :8100), but the link is
mandatory — so we satisfy **priority 1** by dropping the working build's already-downloaded `dist.tar.gz`
contents into `tools/ui/dist`. `-DLLAMA_BUILD_UI=OFF -DHF_ENABLED=OFF` stop it from trying npm/network.

## Serve

`serve.sh` (default `LLAMA_SERVER=../loom-llama.cpp/build/bin/llama-server`, Mag-Mell on :8090) — and it
takes an optional `VECTOR=steering/tone.gguf VECTOR_SCALE=…` to serve with a control vector.

## Next

Patch the server for a per-request `control_vector_scale` (re-apply `llama_set_adapter_cvec` before
generation; safe under `--parallel 1`; backward-compatible), then have loom drive the scale each turn
from the scene's location tone + the tension homeostat. See [docs/STEERING.md](STEERING.md).
