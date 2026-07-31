"""loom.web — a tiny, dependency-free local UI for playing and browsing a campaign.

Pure stdlib http.server, bound to localhost. Serves one self-contained page + a
small JSON API over the campaign vault. Narrator turns go through the same
narrate.turn as the CLI; the world map + reader read canon directly. Nothing here
reaches outside the campaign — same wall as everything else.
"""
from __future__ import annotations
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from . import config, canon, state, transcript, narrate, consolidate, llm, threads

STATIC = Path(__file__).resolve().parent / "static"


def _graph(world: Path) -> dict:
    nodes = canon.load_all(world)
    names = {n["name"] for n in nodes}
    links = []
    for n in nodes:
        for tgt in n["links"]:
            target = tgt.split("|")[0].strip()          # [[Name|alias]] → Name
            if target in names and target != n["name"]:
                links.append({"from": n["name"], "to": target})
    return {"nodes": [{"name": n["name"], "kind": n["frontmatter"].get("kind", "lore")}
                      for n in nodes], "links": links}


def make_handler(cfg: dict):
    tpath = config.transcript_path(cfg)
    world = config.world_dir(cfg)
    spath = config.state_path(cfg)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass  # quiet

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(u.query)
            if u.path in ("/", "/index.html"):
                return self._send(200, (STATIC / "index.html").read_bytes(),
                                  "text/html; charset=utf-8")
            if u.path == "/api/state":
                th = threads.load(spath.parent / "threads.json")
                return self._send(200, {
                    "campaign": cfg["campaign"],
                    "model": cfg["llm_url"],
                    "canon": _graph(world)["nodes"],
                    "state": {k: v for k, v in state.load(spath).items() if not k.startswith("_")},
                    "threads": [{"question": t.question, "status": t.status,
                                 "readiness": round(t.readiness, 2)} for t in th
                                if t.status != "resolved"],
                    "transcript": transcript.recent(tpath, 60),
                })
            if u.path == "/api/graph":
                return self._send(200, _graph(world))
            if u.path == "/api/node":
                node = canon.read_node(world, (q.get("name") or [""])[0])
                if not node:
                    return self._send(404, {"error": "no such node"})
                return self._send(200, {"name": node["name"], "body": node["body"],
                                        "kind": node["frontmatter"].get("kind", "lore"),
                                        "links": node["links"]})
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                return self._send(400, {"error": "bad json"})

            if u.path == "/api/turn":
                text = (body.get("input") or "").strip()
                if not text:
                    return self._send(400, {"error": "empty"})
                try:
                    return self._send(200, {"narrator": narrate.turn(text, cfg, tpath, world, spath)})
                except llm.LLMError as e:
                    return self._send(502, {"error": str(e)})
            if u.path == "/api/consolidate":
                lines = transcript.read_all(tpath)
                if not lines:
                    return self._send(200, {"nodes": [], "state": {}, "threads_new": [],
                                            "threads_resolved": [], "summary": "nothing to consolidate"})
                try:
                    existing = threads.load(spath.parent / "threads.json")
                    return self._send(200, consolidate.propose(cfg, lines, existing))
                except Exception as e:
                    return self._send(502, {"error": str(e)})
            if u.path == "/api/consolidate/apply":
                proposals = body.get("proposals") or {}
                ok = {"node": set(body.get("approved_nodes") or []),
                      "state": set(body.get("approved_state") or []),
                      "thread": set(body.get("approved_threads") or []),
                      "resolve": set(body.get("approved_resolved") or [])}
                written = consolidate.apply(
                    proposals, world, spath,
                    approve=lambda kind, name, _p: name in ok.get(kind, set()))
                return self._send(200, {"written": written})
            return self._send(404, {"error": "not found"})

    return H


def serve(cfg=None, host="127.0.0.1", port=8100):
    cfg = cfg or config.load()
    httpd = ThreadingHTTPServer((host, port), make_handler(cfg))
    print(f"loom UI → http://{host}:{port}   (campaign '{cfg['campaign']}', model {cfg['llm_url']})")
    print("  Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
