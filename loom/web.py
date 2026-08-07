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
from . import config, canon, state, transcript, narrate, consolidate, llm, threads, imagine, guard, character, sleep, worldturn, player

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
    def _ctx():
        c = config.load()                 # reload each request so a campaign switch takes effect
        return c, config.transcript_path(c), config.world_dir(c), config.state_path(c)

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
            try:
                cfg, tpath, world, spath = _ctx()      # a poisoned campaign → clean error, not a dropped connection
            except Exception as e:
                return self._send(500, {"error": f"bad config: {e}"})
            if u.path == "/api/state":
                th = threads.load(spath.parent / "threads.json")
                return self._send(200, {
                    "campaign": cfg["campaign"],
                    "model": cfg["llm_url"],
                    "canon": _graph(world)["nodes"],
                    "state": {k: v for k, v in state.load(spath).items() if not k.startswith("_")},
                    "threads": [{"id": t.id, "question": t.question, "status": t.status,
                                 "readiness": round(t.readiness, 2)} for t in th
                                if t.status != "resolved"],
                    "transcript": transcript.recent(tpath, 60),
                })
            if u.path == "/api/graph":
                return self._send(200, _graph(world))
            if u.path == "/api/check":
                fs = guard.check(world, spath.parent / "threads.json")
                return self._send(200, {"findings": [{"severity": f.severity, "kind": f.kind,
                                                       "message": f.message} for f in fs]})
            if u.path == "/api/node":
                node = canon.read_node(world, (q.get("name") or [""])[0])
                if not node:
                    return self._send(404, {"error": "no such node"})
                resp = {"name": node["name"], "body": node["body"],
                        "kind": node["frontmatter"].get("kind", "lore"), "links": node["links"]}
                if resp["kind"] == "character":
                    resp["card"] = character.card(node)
                return self._send(200, resp)
            if u.path == "/api/worlds":
                base = config.ROOT / cfg["campaigns_dir"]
                names = sorted(p.name for p in base.iterdir() if (p / "world").is_dir()) if base.exists() else []
                return self._send(200, {"campaigns": names, "active": cfg["campaign"]})
            if u.path == "/api/player":
                return self._send(200, player.card(world))
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            try:
                length = max(0, int(self.headers.get("Content-Length") or 0))
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                return self._send(400, {"error": "bad request"})
            try:
                cfg, tpath, world, spath = _ctx()
            except Exception as e:
                return self._send(500, {"error": f"bad config: {e}"})

            if u.path == "/api/turn":
                text = (body.get("input") or "").strip()
                if not text:
                    return self._send(400, {"error": "empty"})
                try:
                    narration = narrate.turn(text, cfg, tpath, world, spath)
                except llm.LLMError as e:
                    return self._send(502, {"error": str(e)})
                # the world takes its round on cadence (toggle-gated) — surfaced beside the scene.
                # never let a world-round hiccup 500 a turn whose narration already committed
                try:
                    world_pulse = worldturn.maybe_round(cfg, world, spath)
                except Exception:
                    world_pulse = []
                return self._send(200, {"narrator": narration, "world": world_pulse})
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
                if not isinstance(proposals, dict):
                    return self._send(400, {"error": "bad proposals"})
                ok = {"node": set(body.get("approved_nodes") or []),
                      "state": set(body.get("approved_state") or []),
                      "thread": set(body.get("approved_threads") or []),
                      "resolve": set(body.get("approved_resolved") or []),
                      "disposition": set(body.get("approved_dispositions") or []),
                      "location": set(body.get("approved_locations") or [])}
                try:
                    written = consolidate.apply(
                        proposals, world, spath,
                        approve=lambda kind, name, _p: name in ok.get(kind, set()))
                except Exception as e:
                    return self._send(502, {"error": str(e)})
                return self._send(200, {"written": written})
            if u.path == "/api/imagine":
                try:
                    cands = imagine.propose(world, spath.parent / "threads.json", cfg)
                except Exception as e:
                    return self._send(502, {"error": str(e)})
                return self._send(200, {"candidates": [
                    {"id": c.id, "question": c.question, "entities": c.entities,
                     "seed": c.seed, "payoff": c.payoff} for c in cands]})
            if u.path == "/api/imagine/bless":
                approved = set(body.get("approved_ids") or [])
                cands = [threads.Thread(id=c["id"], question=c.get("question", ""), status="imagined",
                                        entities=c.get("entities") or [], seed=c.get("seed", ""),
                                        payoff=c.get("payoff", "")) for c in (body.get("candidates") or [])]
                added = imagine.bless(spath.parent / "threads.json", cands,
                                      approve=lambda k, q, c: c.id in approved)
                return self._send(200, {"added": added})
            if u.path == "/api/sleep":
                # advance the world between sessions; the button-click IS the bless (the diode's
                # consent), so preview + apply happen in one call — state stays consistent.
                thp = spath.parent / "threads.json"
                try:
                    report = sleep.advance(cfg, world, thp)
                except Exception as e:
                    return self._send(502, {"error": str(e)})
                if report.get("recap"):
                    w = sleep.apply(report, thp, spath, approve=lambda *a: True)
                    return self._send(200, {"recap": w["recap"], "beats": report["beats"],
                                            "resolved": w["resolved"]})
                if report.get("pending"):                         # something happened but recap failed → roll back
                    return self._send(502, {"error": "the world stirred but the recap couldn't be written; try again"})
                threads.save(thp, report["threads"])              # nothing due; time passed quietly, persist ticks
                return self._send(200, {"recap": "", "beats": report["beats"], "resolved": []})
            if u.path == "/api/use":
                name = (body.get("name") or "").strip()
                base = config.ROOT / cfg["campaigns_dir"]
                if not config.valid_campaign_name(name) or not (base / name / "world").is_dir():
                    return self._send(400, {"error": "no such campaign"})
                config.save({"campaign": name})
                return self._send(200, {"active": name})
            # --- authoring (writes stay inside the campaign world by construction) ---
            if u.path == "/api/player/save":
                name = (body.get("name") or "").strip()
                if not name:
                    return self._send(400, {"error": "name required"})
                player.save(world, name, role=body.get("role") or "", description=body.get("description") or "",
                            wants=body.get("wants") or "", location=body.get("location") or "")
                return self._send(200, {"ok": True, "player": player.card(world)})
            if u.path == "/api/node/save":
                name = (body.get("name") or "").strip()
                if not name:
                    return self._send(400, {"error": "name required"})
                fields = {k: v for k, v in (body.get("fields") or {}).items() if v}
                canon.write_node(world, name, body.get("body") or "",
                                 {"kind": body.get("kind") or "lore", **fields})
                return self._send(200, {"ok": True, "name": name})
            if u.path == "/api/node/delete":
                p = world / (canon.slug(body.get("name") or "") + ".md")
                if p.exists() and p.parent.resolve() == world.resolve():
                    p.unlink()
                return self._send(200, {"ok": True})
            if u.path == "/api/new":
                name = (body.get("name") or "").strip()
                if not config.valid_campaign_name(name):
                    return self._send(400, {"error": "bad name"})
                cdir = config.ROOT / cfg["campaigns_dir"] / name
                (cdir / "world").mkdir(parents=True, exist_ok=True)
                if not any((cdir / "world").glob("*.md")):
                    canon.write_node(cdir / "world", "The World",
                                     "The opening premise of the story goes here.", {"kind": "lore"})
                state.save(cdir / "state.json", {})
                config.save({"campaign": name})
                return self._send(200, {"ok": True, "name": name})
            if u.path == "/api/thread/save":
                t = body.get("thread") or {}
                q = (t.get("question") or "").strip()
                if not q:
                    return self._send(400, {"error": "question required"})
                thp = spath.parent / "threads.json"
                tid = t.get("id") or threads.make_id(q)
                keep = [x for x in threads.load(thp) if x.id != tid]
                keep.append(threads.Thread(
                    id=tid, question=q, kind=t.get("kind") or "question",
                    status=t.get("status") or "dormant", readiness=float(t.get("readiness") or 0.0),
                    entities=t.get("entities") or [], seed=t.get("seed") or "", payoff=t.get("payoff") or ""))
                threads.save(thp, keep)
                return self._send(200, {"ok": True, "id": tid})
            if u.path == "/api/thread/delete":
                thp = spath.parent / "threads.json"
                threads.save(thp, [x for x in threads.load(thp) if x.id != body.get("id")])
                return self._send(200, {"ok": True})
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
