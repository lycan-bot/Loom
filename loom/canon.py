"""loom.canon — the world-bible (the CONSOLIDATE tier): markdown nodes with
frontmatter + [[wikilinks]]. This is what the narrator reasons FROM.

The node format and `parse_frontmatter` are lifted from the Primarch vault, so a
campaign world is just a folder of plain, Obsidian-readable markdown.
"""
from __future__ import annotations
import os, re, tempfile
from pathlib import Path

_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(name: str) -> str:
    return _SLUG_RE.sub("-", name.strip().lower()).strip("-") or "node"


# --- vendored verbatim from primarch/modules/vault.py (pure, no PyYAML) ---
def parse_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter as a dict. Simple parser, no PyYAML needed."""
    if not content.startswith("---"):
        return {}
    end = content.find("\n---", 3)                # closing fence must be its OWN line, so an inline
    if end == -1:                                 # '---' inside a value can't terminate it early
        return {}
    result = {}
    for line in content[3:end].strip().split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if val.lower() == "true":
                val = True
            elif val.lower() == "false":
                val = False
            result[key] = val
    return result


def _body_of(content: str) -> str:
    if content.startswith("---"):
        end = content.find("\n---", 3)            # closing fence at the start of a line
        if end != -1:
            nl = content.find("\n", end + 1)      # the newline ending that closing '---' line
            return content[nl + 1:].lstrip("\n") if nl != -1 else ""
    return content


def links_in(content: str) -> list[str]:
    return _LINK_RE.findall(content)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")   # unique temp
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _fm_clean(v) -> str:
    """Frontmatter is single-line `key: value`. A newline in a key or value could inject extra
    keys or an early '---' terminator (dropping title/kind, leaking into the body) — so collapse
    line breaks out of every field before serializing."""
    return str(v).replace("\n", " ").replace("\r", " ").strip()


def write_node(world: Path, name: str, body: str, frontmatter: dict | None = None) -> Path:
    from . import seal                                  # lazy: seal imports canon (avoid a cycle)
    fm = dict(frontmatter or {})
    fm.setdefault("title", name)
    fm_lines = "\n".join(f"{_fm_clean(k)}: {_fm_clean(v)}" for k, v in fm.items())
    content = f"---\n{fm_lines}\n---\n\n{body.strip()}\n"
    path = world / f"{slug(name)}.md"
    seal.guard_path(path, world)                        # structural belt: the node file stays inside the world
    _atomic_write(path, content)
    return path


def read_node(world: Path, name: str) -> dict | None:
    path = world / f"{slug(name)}.md"
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8", errors="replace")   # a corrupt byte must not crash a turn
    return {"name": name, "path": path, "frontmatter": parse_frontmatter(content),
            "body": _body_of(content), "links": links_in(content)}


def load_all(world: Path) -> list[dict]:
    if not world.exists():
        return []
    out = []
    for path in sorted(world.glob("*.md")):
        content = path.read_text(encoding="utf-8", errors="replace")   # corrupt canon → degrade, don't crash
        fm = parse_frontmatter(content)
        out.append({"name": fm.get("title", path.stem), "path": path,
                    "frontmatter": fm, "body": _body_of(content),
                    "links": links_in(content)})
    return out
