"""loom.inbox — the single-writer hand-off between the background archivist and the turn thread.

The auto-consolidation daemon does ONLY the slow model call (propose) and appends its result here;
it never touches state.json / threads.json / canon. The main turn thread drains this inbox at the
start of the next turn and applies everything itself. Because only the turn thread ever mutates the
shared stores, the whole background-fold-vs-turn race dissolves by construction (there is no second
concurrent writer left to lose to).

An append-only JSONL file the daemon owns exclusively. append() and take() are guarded by an
in-process lock — both callers live in the same process (the ThreadingHTTPServer), so the lock makes
them mutually exclusive and a concurrent append can never be lost by a take()'s truncate.
"""
from __future__ import annotations
import json
import os
import tempfile
import threading
from pathlib import Path

_LOCK = threading.Lock()                       # append (daemon) vs take (turn thread) — same process


def _path(spath) -> Path:
    return Path(spath).parent / "consolidate_inbox.jsonl"


def append(spath, rec: dict) -> None:
    """Append one fold job as a JSON line. Held under the lock so a take() can't truncate between the
    open and the write. Jobs are small; O_APPEND keeps a single write atomic at the OS level too."""
    line = (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8")
    p = _path(spath)
    with _LOCK:
        fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)


def take(spath) -> list[dict]:
    """Read every queued job and atomically empty the inbox (mkstemp + os.replace), returning the
    jobs in append order. Malformed lines are skipped, never fatal. Held under the same lock as
    append(), so no job appended by the daemon is lost in the truncate."""
    p = _path(spath)
    with _LOCK:
        if not p.exists():
            return []
        try:
            raw = p.read_text("utf-8")
        except Exception:
            return []
        jobs = []
        for ln in raw.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                j = json.loads(ln)
                if isinstance(j, dict):
                    jobs.append(j)
            except Exception:
                continue                          # a torn/garbled line is skipped, never fatal
        try:                                      # empty the inbox atomically (replace with an empty file)
            d = os.path.dirname(str(p)) or "."
            fd, tmp = tempfile.mkstemp(dir=d)
            os.close(fd)
            os.replace(tmp, str(p))
        except Exception:
            pass
    return jobs
