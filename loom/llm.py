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


def chat(messages: list[dict], cfg: dict, max_tokens: int | None = None,
         temperature: float | None = None) -> str:
    """One /v1/chat/completions round-trip → cleaned assistant text."""
    payload = {
        "model": cfg["llm_model"],
        "messages": messages,
        "max_tokens": max_tokens or cfg["max_tokens"],
        "temperature": cfg["temperature"] if temperature is None else temperature,
    }
    resp = _post(cfg["llm_url"], payload, cfg["api_key"], cfg["request_timeout"])
    try:
        content = resp["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise LLMError(f"unexpected response shape: {json.dumps(resp)[:300]}")
    return strip_think_blocks(content)


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
