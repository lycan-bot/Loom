"""loom.llm — a thin, dependency-free client for a local OpenAI-compatible model
server (llama-server / Ollama / LM Studio).

Vendored clean from the Primarch mind: only the request shape and the
`strip_think_blocks` reasoning-filter are carried over — none of the floor,
sovereignty, or config apparatus comes with it.
"""
from __future__ import annotations
import json, re, urllib.request, urllib.error


class LLMError(RuntimeError):
    pass


# --- vendored verbatim from primarch/llm_engine.py (pure, dependency-free) ---
def strip_think_blocks(text: str) -> str:
    """Remove <think>...</think> and similar reasoning blocks from model output.
    Handles: <think>, <thinking>, <reasoning>, <reflection> — closed and unclosed."""
    if not text:
        return text
    for tag in ("think", "thinking", "reasoning", "reflection"):
        text = re.sub(rf"<{tag}>[\s\S]*?</{tag}>", "", text)
        text = re.sub(rf"<{tag}>[\s\S]*$", "", text)
    return text.strip()


def _post(url: str, payload: dict, api_key: str, timeout: int) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        raise LLMError(f"HTTP {e.code} from {url}: {body}")
    except urllib.error.URLError as e:
        raise LLMError(f"could not reach model server at {url} ({e.reason}). "
                       f"Is llama-server running?")
    except Exception as e:
        raise LLMError(f"model call failed: {e}")


def _anti_repetition(cfg: dict) -> dict:
    """Sampler-level anti-repetition params for NARRATION only (never the structured archivist calls,
    which want clean JSON). The repetition on this model is a sampling attractor — a re-roll escapes
    it — so DRY + a light frequency penalty make the repeated path LOSE at the logit level on every
    roll, which no prompt directive achieves. A stock server ignores keys it doesn't know."""
    if not cfg.get("anti_repetition"):
        return {}
    return {
        "dry_multiplier": cfg.get("dry_multiplier", 0.8),
        "dry_base": cfg.get("dry_base", 1.75),
        "dry_allowed_length": cfg.get("dry_allowed_length", 2),
        "frequency_penalty": cfg.get("frequency_penalty", 0.3),
        "presence_penalty": cfg.get("presence_penalty", 0.0),
    }


def chat(messages: list[dict], cfg: dict, max_tokens: int | None = None,
         temperature: float | None = None, response_format=None, control_vector_scale=None) -> str:
    """One /v1/chat/completions round-trip → cleaned assistant text. `response_format`
    (e.g. {"type": "json_object"}) constrains generation via the server's grammar —
    guaranteeing valid JSON even from a wild model. `control_vector_scale` (loom's patched
    server) sets the served control vector's scale for this turn — dynamic tone; ignored by a
    stock server or one with no vector loaded."""
    payload = {
        "model": cfg["llm_model"],
        "messages": messages,
        "max_tokens": max_tokens or cfg["max_tokens"],
        "temperature": cfg["temperature"] if temperature is None else temperature,
    }
    if response_format:
        payload["response_format"] = response_format
    else:
        payload.update(_anti_repetition(cfg))          # narration only — never the structured (JSON) calls
    if control_vector_scale is not None:
        payload["control_vector_scale"] = control_vector_scale
    resp = _post(cfg["llm_url"], payload, cfg["api_key"], cfg["request_timeout"])
    try:
        content = resp["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise LLMError(f"unexpected response shape: {json.dumps(resp)[:300]}")
    return strip_think_blocks(content)


def chat_stream(messages: list[dict], cfg: dict, max_tokens: int | None = None,
                temperature: float | None = None, control_vector_scale=None):
    """Stream a /v1/chat/completions call (SSE) — yields assistant text deltas as the model produces
    them. The caller accumulates and applies strip_think_blocks on the full text at the end (a think
    block can't be reliably stripped mid-stream). Raises LLMError before the first yield if the
    server is unreachable; a mid-stream drop ends the generator (the caller commits what it has)."""
    payload = {
        "model": cfg["llm_model"],
        "messages": messages,
        "max_tokens": max_tokens or cfg["max_tokens"],
        "temperature": cfg["temperature"] if temperature is None else temperature,
        "stream": True,
    }
    payload.update(_anti_repetition(cfg))               # streaming is always narration → anti-repetition applies
    if control_vector_scale is not None:
        payload["control_vector_scale"] = control_vector_scale
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        cfg["llm_url"], data=data, method="POST",
        headers={"Content-Type": "application/json", "Accept": "text/event-stream",
                 "Authorization": f"Bearer {cfg['api_key']}"})
    try:
        resp = urllib.request.urlopen(req, timeout=cfg["request_timeout"])
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        raise LLMError(f"HTTP {e.code} from {cfg['llm_url']}: {body}")
    except urllib.error.URLError as e:
        raise LLMError(f"could not reach model server at {cfg['llm_url']} ({e.reason}). "
                       f"Is llama-server running?")
    except Exception as e:
        raise LLMError(f"model call failed: {e}")
    try:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if chunk == "[DONE]":
                break
            try:
                delta = json.loads(chunk)["choices"][0]["delta"].get("content")
            except (KeyError, IndexError, TypeError, ValueError):
                continue
            if delta:
                yield delta
    finally:
        resp.close()


def schema_format(name: str, schema: dict) -> dict:
    """An ENFORCED response_format: the server applies the JSON schema as a token-level grammar, so
    even a wild RP model emits valid, correctly-shaped JSON. Prefer this over {"type":"json_object"},
    which loom's llama.cpp treats as a soft hint the model can (and does) ignore — producing prose."""
    return {"type": "json_schema", "json_schema": {"name": name, "schema": schema}}


def complete(prompt: str, cfg: dict, system: str | None = None, **kw) -> str:
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return chat(messages, cfg, **kw)


def embed(texts: list[str], cfg: dict) -> list[list[float]] | None:
    """Embed via the server's /v1/embeddings endpoint. Returns None when embeddings
    are disabled or unreachable — callers fall back to lexical retrieval."""
    if not cfg.get("use_embeddings"):
        return None
    payload = {"model": cfg["embed_model"], "input": texts}
    try:
        resp = _post(cfg["embed_url"], payload, cfg["api_key"], cfg["request_timeout"])
        return [row["embedding"] for row in resp["data"]]
    except Exception:
        return None  # best-effort; lexical retrieval still works
