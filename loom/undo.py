"""loom.undo — take back the last turn.

A play affordance: a bad beat isn't permanent. Before each turn commits, a SNAPSHOT of the
reversible state is pushed — the transcript position (it is append-only, so we remember how far to
truncate) plus the raw bytes of threads.json and state.json. Undo pops the last snapshot and
restores it, which reverses everything a turn changed: the player+narrator lines, thread ripening,
the tension homeostat, location, recap/nearby notes.

Consolidated CANON is deliberately NOT snapshotted — it is not touched per-turn (consolidation is
its own step), so a per-turn undo has nothing to reverse there. The undo stack is a scratch file in
the campaign dir, capped so it can't grow without bound.
"""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from . import transcript

_CAP = 30               # keep the last N turns undoable; older snapshots fall off the stack


def _upath(tpath: Path) -> Path:
    return Path(tpath).parent / "undo.jsonl"


def _atomic_write(path: Path, text: str) -> None:
    """Write via a unique temp + os.replace — a torn write can't corrupt state.json/threads.json
    (matches state.save's discipline; a restore that half-writes would defeat the point of undo)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
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


def snapshot(tpath: Path, spath: Path) -> None:
    """Capture the pre-turn state so this turn can be taken back. Call BEFORE any mutation."""
    tpath, spath = Path(tpath), Path(spath)
    thpath = spath.parent / "threads.json"
    epath = spath.parent / "episodic.jsonl"
    fpath = spath.parent / "facts_log.jsonl"

    def _nlines(p):
        return len([ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]) if p.exists() else 0

    snap = {
        "n_transcript": len(transcript.read_all(tpath)),
        # the episodic timeline is append-only too — remember its length so undo can truncate any events
        # a fold appended on the undone turns (else the timeline asserts a beat that no longer happened).
        # Captured AFTER _prepare's drain, so a fold that legitimately landed this turn is preserved.
        "n_episodic": _nlines(epath),
        # the provenance ledger is append-only for the same reason — a fold that recorded an old→new
        # change on the undone turns must roll back too, or `loom why` would cite a change that unhappened.
        "n_facts": _nlines(fpath),
        "threads": thpath.read_text(encoding="utf-8") if thpath.exists() else None,
        "state": spath.read_text(encoding="utf-8") if spath.exists() else None,
    }
    up = _upath(tpath)
    lines = up.read_text(encoding="utf-8").splitlines() if up.exists() else []
    lines.append(json.dumps(snap, ensure_ascii=False))
    lines = lines[-_CAP:]                                    # bound the stack
    _atomic_write(up, "\n".join(lines) + "\n")


def can_undo(tpath: Path) -> bool:
    up = _upath(tpath)
    return up.exists() and bool(up.read_text(encoding="utf-8").strip())


def undo(tpath: Path, spath: Path) -> bool:
    """Pop the last snapshot and restore it. Returns True if a turn was taken back, False if the
    stack is empty (nothing to undo). A malformed snapshot line is discarded, not crashed on."""
    tpath, spath = Path(tpath), Path(spath)
    up = _upath(tpath)
    if not up.exists():
        return False
    lines = [ln for ln in up.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        return False
    snap = None
    while lines and snap is None:
        try:
            snap = json.loads(lines.pop())                  # newest first; skip a corrupt entry
        except Exception:
            snap = None
    _atomic_write(up, ("\n".join(lines) + "\n") if lines else "")
    if not isinstance(snap, dict):
        return False

    # restore the transcript by truncating to the remembered entry count (append-only, so this is
    # exactly the pre-turn log). Rewrite in transcript's own jsonl format.
    n = int(snap.get("n_transcript", 0) or 0)
    entries = transcript.read_all(tpath)[:n]
    _atomic_write(tpath, "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries))

    # truncate the append-only episodic timeline back to its pre-turn length, reversing any events a
    # fold on the undone turns appended (episodic.jsonl is a separate file undo would otherwise miss)
    epath = spath.parent / "episodic.jsonl"
    ne = snap.get("n_episodic")
    if ne is not None and epath.exists():
        elines = [ln for ln in epath.read_text(encoding="utf-8").splitlines() if ln.strip()][:int(ne)]
        _atomic_write(epath, ("\n".join(elines) + "\n") if elines else "")

    # truncate the append-only provenance ledger the same way — a fold's recorded old→new changes on
    # the undone turns must vanish with them (else the audit trail asserts a change that no longer stands)
    fpath = spath.parent / "facts_log.jsonl"
    nf = snap.get("n_facts")
    if nf is not None and fpath.exists():
        flines = [ln for ln in fpath.read_text(encoding="utf-8").splitlines() if ln.strip()][:int(nf)]
        _atomic_write(fpath, ("\n".join(flines) + "\n") if flines else "")

    # restore threads.json + state.json to their pre-turn bytes (or remove if they didn't exist)
    thpath = spath.parent / "threads.json"
    for path, raw in ((thpath, snap.get("threads")), (spath, snap.get("state"))):
        if raw is not None:
            _atomic_write(path, raw)
        elif path.exists():
            path.unlink()
    return True
