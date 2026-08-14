"""loom.compact — node compaction (storyteller-memory Phase 7, the culmination).

Over a long campaign a canon node ACCRETES: each consolidation appends a fresh block to its body, so
a central character's node swells to thousands of words of overlapping, repetitive prose — slower to
load every turn and muddier to reason over. Compaction distills a bloated node into a tighter version
that PRESERVES every fact + [[link]] but drops the redundancy.

Fail-closed + gated (the diode): a distillation that would DROP a canon [[link]], not actually shrink,
or come back empty is REFUSED — the original stands. The operator blesses the rest, exactly like
consolidation. This is what keeps a 500-turn campaign as fast/coherent as a 5-turn one.
"""
from __future__ import annotations
import re
from . import canon, llm

_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_DEFAULT_THRESHOLD = 1800          # chars of body before a node is a compaction candidate


def _links(body: str) -> set:
    """The set of [[link]] targets in a body (alias stripped), for the fail-closed preservation check."""
    return {m.split("|")[0].strip() for m in _LINK_RE.findall(body or "")}


def oversized(world, threshold: int = _DEFAULT_THRESHOLD) -> list[dict]:
    """Canon nodes whose body has grown past `threshold` chars — the compaction candidates, largest
    first. Deterministic; no model call."""
    out = [n for n in canon.load_all(world) if len(n.get("body", "") or "") > threshold]
    return sorted(out, key=lambda n: -len(n["body"]))


_PROMPT = """You are the archivist compacting an overgrown canon node — it has accreted repetitive \
blocks over many sessions. Rewrite its body into a TIGHTER version that:
- PRESERVES every established fact, every named character/place, and EVERY [[link]] exactly as written,
- removes only repetition, redundant restatement, and filler,
- keeps the node's voice and markdown,
- invents NOTHING new.

Return ONLY the rewritten body markdown (no preamble, no code fence).

NODE: %s (%s)
CURRENT BODY:
%s
"""


def propose(node: dict, cfg: dict) -> str:
    """Ask the model for a distilled body. Uses the archivist endpoint (reliable prose). Returns the
    new body text (unverified — call verify() before applying)."""
    ccfg = dict(cfg)
    for k, ck in (("llm_url", "consolidate_llm_url"), ("llm_model", "consolidate_model"),
                  ("api_key", "consolidate_api_key")):
        if cfg.get(ck):
            ccfg[k] = cfg[ck]
    kind = node["frontmatter"].get("kind", "lore")
    raw = llm.complete(_PROMPT % (node["name"], kind, node["body"]), ccfg,
                       max_tokens=800, temperature=0.2)
    return llm.strip_think_blocks(raw).strip().strip("`").strip()


def verify(original_body: str, distilled: str, min_shrink: float = 0.15) -> tuple[bool, str]:
    """The fail-closed gate: a distillation is accepted ONLY if it keeps every [[link]], actually
    shrinks (by >= min_shrink), and isn't empty. Returns (ok, reason). Never loses canon silently."""
    distilled = (distilled or "").strip()
    if len(distilled) < 40:
        return False, "distillation came back empty/too short"
    lost = _links(original_body) - _links(distilled)
    if lost:
        return False, f"would drop canon link(s): {', '.join(sorted(lost))}"
    if len(distilled) > len(original_body) * (1 - min_shrink):
        return False, "did not meaningfully shrink"
    return True, "ok"


def apply(world, name: str, distilled: str) -> bool:
    """Replace the node's body with the distilled version, preserving its frontmatter (drives, voice,
    links-as-fields). Returns True if written. Caller must have verify()'d first (the diode)."""
    node = canon.read_node(world, name)
    if node is None:
        return False
    canon.write_node(world, node["name"], distilled, node["frontmatter"])
    return True
