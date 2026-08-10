"""loom.web — a tiny, dependency-free local UI for playing and browsing a campaign.

Pure stdlib http.server, bound to localhost. Serves one self-contained page + a
small JSON API over the campaign vault. Narrator turns go through the same
narrate.turn as the CLI; the world map + reader read canon directly. Nothing here
reaches outside the campaign — same wall as everything else.
"""
from __future__ import annotations
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from . import config, canon, state, transcript, narrate, consolidate, llm, threads, imagine, guard, character, sleep, worldturn, player, generate, setting, undo, reputation, salience, assistant

STATIC = Path(__file__).resolve().parent / "static"

# ThreadingHTTPServer runs every request on its own thread. Any two POSTs that read-modify-write the
# durable stores (state.json / threads.json / the transcript) would otherwise last-writer-wins-clobber
# each other — reverting the watermark, or reverting the _rep_applied ledger and re-arming the
# reputation double-apply. This process-wide lock serializes the MUTATING requests, restoring the
# single-writer invariant the background-fold design already assumes on the daemon side. Pure
# propose/preview POSTs (a model call, no durable write) are exempt so a long archivist call never
# stalls play.
_WRITE_LOCK = threading.Lock()
_READONLY_POSTS = frozenset({"/api/assist", "/api/consolidate", "/api/imagine", "/api/generate"})


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
                st_all = state.load(spath)
                rep = reputation.load(st_all)
                return self._send(200, {
                    "campaign": cfg["campaign"],
                    "model": cfg["llm_url"],
                    "canon": _graph(world)["nodes"],
                    "state": {k: v for k, v in st_all.items() if not k.startswith("_")},
                    "location": st_all.get("_location", ""),
                    "memory": st_all.get("_memory", "") if cfg.get("scene_memory") else "",
                    "steer": st_all.get("_steer", {}) if cfg.get("tone_steer") else {},
                    "unconsolidated": max(0, len(transcript.read_all(tpath)) - int(st_all.get("_consolidated", 0) or 0)),
                    "auto_consolidate": bool(cfg.get("auto_consolidate")),
                    "pending_canon": len(consolidate.pending(spath)),   # canon parked by auto-fold, awaiting bless
                    "reputation": [{"who": w, "standing": int(e.get("standing", 0) or 0),
                                    "label": reputation.label(int(e.get("standing", 0) or 0)),
                                    "log": [s for s in (e.get("log") or []) if isinstance(s, str)]}
                                   for w, e in sorted(rep.items()) if isinstance(e, dict)],
                    "can_undo": undo.can_undo(tpath),
                    "threads": [{"id": t.id, "question": t.question, "status": t.status,
                                 "readiness": round(t.readiness, 2)} for t in th
                                if t.status != "resolved"],
                    "transcript": transcript.recent(tpath, 60),
                })
            if u.path == "/api/graph":
                return self._send(200, _graph(world))
            if u.path == "/api/cards":
                # the cast + world, tiered by salience for the card rail (deterministic, grounded)
                return self._send(200, {"tiers": salience.classify(world, tpath, spath)})
            if u.path == "/api/threads":
                # ALL threads (every status) with full detail — the quest-book board + memories view
                return self._send(200, {"threads": [
                    {"id": t.id, "question": t.question, "kind": t.kind, "status": t.status,
                     "readiness": round(t.readiness, 2), "entities": t.entities, "seed": t.seed,
                     "payoff": t.payoff} for t in threads.load(spath.parent / "threads.json")]})
            if u.path == "/api/pending":
                # canon-node proposals auto-consolidation PARKED for the operator to bless (the diode's pen) —
                # the fix for auto-fold silently dropping canon past the watermark
                return self._send(200, {"nodes": [
                    {"name": n.get("name", ""), "kind": n.get("kind", "lore"),
                     "body": n.get("body", ""), "fields": n.get("fields") or {}}
                    for n in consolidate.pending(spath)]})
            if u.path == "/api/check":
                fs = guard.check(world, spath.parent / "threads.json")
                return self._send(200, {"findings": [{"severity": f.severity, "kind": f.kind,
                                                       "message": f.message} for f in fs]})
            if u.path == "/api/node":
                node = canon.read_node(world, (q.get("name") or [""])[0])
                if not node:
                    return self._send(404, {"error": "no such node"})
                resp = {"name": node["name"], "body": node["body"],
                        "kind": node["frontmatter"].get("kind", "lore"), "links": node["links"],
                        "fields": {k: v for k, v in node["frontmatter"].items() if k not in ("kind", "title")}}
                if resp["kind"] == "character":
                    resp["card"] = character.card(node)
                return self._send(200, resp)
            if u.path == "/api/worlds":
                base = config.ROOT / cfg["campaigns_dir"]
                names = sorted(p.name for p in base.iterdir() if (p / "world").is_dir()) if base.exists() else []
                return self._send(200, {"campaigns": names, "active": cfg["campaign"]})
            if u.path == "/api/player":
                return self._send(200, player.card(world))
            if u.path == "/api/config":
                return self._send(200, {"depth": cfg.get("depth", 0.0), "mechanics": bool(cfg.get("mechanics")),
                                        "world_rounds": bool(cfg.get("world_rounds")),
                                        "world_cadence": cfg.get("world_cadence", 3),
                                        "tone_steer": bool(cfg.get("tone_steer")),
                                        "stream": bool(cfg.get("stream")),
                                        "scene_memory": bool(cfg.get("scene_memory")),
                                        "memory_every": cfg.get("memory_every", 4),
                                        "auto_consolidate": bool(cfg.get("auto_consolidate")),
                                        "auto_consolidate_apply": bool(cfg.get("auto_consolidate_apply")),
                                        "consolidate_every": cfg.get("consolidate_every", 8)})
            if u.path == "/api/setting":
                return self._send(200, setting.card(world))
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            # serialize state-mutating requests (single-writer invariant); exempt pure propose/preview
            # POSTs so a slow archivist/imagine model call doesn't stall a turn.
            if urllib.parse.urlparse(self.path).path in _READONLY_POSTS:
                return self._do_POST()
            with _WRITE_LOCK:
                return self._do_POST()

        def _do_POST(self):
            u = urllib.parse.urlparse(self.path)
            try:
                clen = max(0, int(self.headers.get("Content-Length") or 0))   # not 'length' — that's a module
                body = json.loads(self.rfile.read(clen) or b"{}")
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
            if u.path == "/api/turn/stream":
                # token-by-token narration over SSE. The stream is PROVISIONAL: narrate.turn_stream
                # runs the same output guard + referee at finalize and only its result is committed,
                # emitting a 'replace' if the on-screen text has to be corrected (the spine holds).
                text = (body.get("input") or "").strip()
                if not text:
                    return self._send(400, {"error": "empty"})
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")   # don't let a proxy buffer the stream
                self.end_headers()

                def sse(event, data):
                    self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
                    self.wfile.flush()

                try:
                    for kind, payload in narrate.turn_stream(text, cfg, tpath, world, spath):
                        if kind == "token":
                            sse("token", {"t": payload})
                        elif kind == "replace":
                            sse("replace", {"text": payload})
                        elif kind == "final":
                            try:
                                world_pulse = worldturn.maybe_round(cfg, world, spath)
                            except Exception:
                                world_pulse = []
                            if world_pulse:
                                sse("world", {"world": world_pulse})
                            sse("done", {"narrator": payload})
                except llm.LLMError as e:
                    sse("error", {"error": str(e)})
                except Exception as e:
                    sse("error", {"error": f"stream failed: {e}"})
                return
            if u.path == "/api/undo":
                # take back the last turn — restores transcript, threads, tension, location
                return self._send(200, {"undone": undo.undo(tpath, spath)})
            if u.path == "/api/continue":
                # ⤵ extend the last narration (does not advance the plan/tension)
                try:
                    return self._send(200, {"narrator": narrate.resume(cfg, tpath, world, spath)})
                except llm.LLMError as e:
                    return self._send(502, {"error": str(e)})
            if u.path == "/api/retry":
                # ↻ re-roll the last turn fresh (undo + re-narrate the same input)
                try:
                    text = narrate.retry(cfg, tpath, world, spath)
                except llm.LLMError as e:
                    return self._send(502, {"error": str(e)})
                if text is None:
                    return self._send(200, {"narrator": None})
                try:
                    world_pulse = worldturn.maybe_round(cfg, world, spath)
                except Exception:
                    world_pulse = []
                return self._send(200, {"narrator": text, "world": world_pulse})
            if u.path == "/api/assist":
                # Oracle: an OUT-OF-CHARACTER assistant. Its reply never enters the transcript/canon,
                # and its actions are PROPOSALS the player applies via the gated author endpoints.
                msg = (body.get("message") or "").strip()
                if not msg:
                    return self._send(400, {"error": "empty"})
                history = body.get("history") if isinstance(body.get("history"), list) else []
                try:
                    return self._send(200, assistant.ask(cfg, world, spath, history, msg))
                except llm.LLMError as e:
                    return self._send(502, {"error": str(e)})
            if u.path == "/api/consolidate":
                lines, total = consolidate.unconsolidated(tpath, spath)   # only the NEW turns (incremental)
                if not lines:
                    return self._send(200, {"nodes": [], "state": {}, "threads_new": [],
                                            "threads_resolved": [], "summary": "nothing new to consolidate"})
                try:
                    existing = threads.load(spath.parent / "threads.json")
                    proposals = consolidate.propose(cfg, lines, existing, world=world)
                    proposals["_start"] = total - len(lines)             # the window bounds — round-tripped so
                    proposals["_total"] = total                          # apply gets the SAME deed-key + watermark
                    return self._send(200, proposals)                    # save the drain path uses (no split-commit)
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
                      "location": set(body.get("approved_locations") or []),
                      "reputation": set(body.get("approved_reputation") or [])}
                tlen = len(transcript.read_all(tpath))
                total = min(int(proposals.get("_total") or tlen), tlen)   # never mark PAST the real transcript
                start = max(0, int(proposals.get("_start") or 0))         #   (a stale/corrupt _total can't leap it)
                try:
                    # SAME idempotent-reputation + combined-watermark save as the auto/drain path: deed-key
                    # on (start, total) so a re-run can't double-count, and the watermark advances in the
                    # same state.save as _rep (no split-commit). Replaces the old separate mark_consolidated.
                    written = consolidate.apply(
                        proposals, world, spath,
                        approve=lambda kind, name, _p: name in ok.get(kind, set()),
                        deed_window=(start, total), watermark=total)
                except Exception as e:
                    return self._send(502, {"error": str(e)})
                return self._send(200, {"written": written})
            if u.path == "/api/pending/apply":
                # bless the parked canon into the world-bible. approved_nodes (names) gates it; omit to
                # bless all. A review pass is final — the pen is emptied either way (declined = dropped).
                approved = body.get("approved_nodes")
                approve = ((lambda kind, name, _p: name in set(approved))
                           if isinstance(approved, list) else (lambda *a: True))
                try:
                    written = consolidate.apply_pending(world, spath, approve=approve)
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
            if u.path == "/api/config":
                up = {}
                if "depth" in body:
                    try:
                        up["depth"] = max(0.0, min(1.0, float(body["depth"])))
                    except (TypeError, ValueError):
                        pass
                if "mechanics" in body:
                    up["mechanics"] = bool(body["mechanics"])
                if "world_rounds" in body:
                    up["world_rounds"] = bool(body["world_rounds"])
                if "tone_steer" in body:
                    up["tone_steer"] = bool(body["tone_steer"])
                if "stream" in body:
                    up["stream"] = bool(body["stream"])
                if "scene_memory" in body:
                    up["scene_memory"] = bool(body["scene_memory"])
                if "memory_every" in body:
                    try:
                        up["memory_every"] = max(1, min(20, int(body["memory_every"])))
                    except (TypeError, ValueError):
                        pass
                if "auto_consolidate" in body:
                    up["auto_consolidate"] = bool(body["auto_consolidate"])
                if "auto_consolidate_apply" in body:
                    up["auto_consolidate_apply"] = bool(body["auto_consolidate_apply"])
                if "consolidate_every" in body:
                    try:
                        up["consolidate_every"] = max(2, min(40, int(body["consolidate_every"])))
                    except (TypeError, ValueError):
                        pass
                if up:
                    config.save(up)
                return self._send(200, {"ok": True})
            if u.path == "/api/generate":                     # roll a world + cast (no write)
                seed = (body.get("seed") or "").strip()
                try:
                    n = max(1, min(6, int(body.get("n") or 3)))
                except (TypeError, ValueError):
                    n = 3
                try:
                    wc = generate.world(cfg, seed)
                    cast = generate.cast(cfg, wc, n) if (wc.get("name") or wc.get("body")) else []
                except llm.LLMError as e:
                    return self._send(502, {"error": str(e)})
                return self._send(200, {"world": wc, "cast": cast})
            if u.path == "/api/generate/apply":               # write a rolled world into a NEW campaign
                name = (body.get("name") or "").strip()
                wc = body.get("world") if isinstance(body.get("world"), dict) else None
                if not config.valid_campaign_name(name):
                    return self._send(400, {"error": "bad campaign name"})
                if not wc:
                    return self._send(400, {"error": "no world to write"})
                cdir = config.ROOT / cfg["campaigns_dir"] / name
                if (cdir / "world").exists() and any((cdir / "world").glob("*.md")):
                    return self._send(400, {"error": f"campaign '{name}' already exists"})
                (cdir / "world").mkdir(parents=True, exist_ok=True)
                generate.write_world(cdir / "world", wc, [c for c in (body.get("cast") or []) if isinstance(c, dict)])
                state.save(cdir / "state.json", {})
                config.save({"campaign": name})
                return self._send(200, {"ok": True, "name": name})
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
