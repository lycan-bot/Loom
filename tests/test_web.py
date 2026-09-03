"""The web handler, driven over a real localhost socket (read-only endpoints). Offline."""
import json
import threading
import urllib.request
import urllib.parse
import unittest
from http.server import ThreadingHTTPServer
from loom import web, config


class WebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.make_handler(config.load()))
        cls.port = cls.httpd.server_address[1]
        cls.t = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()          # release the listening socket (else a ResourceWarning)

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as r:
            return json.loads(r.read())

    def test_state(self):
        d = self._get("/api/state")
        self.assertIn("campaign", d)
        self.assertIsInstance(d["canon"], list)
        self.assertIsInstance(d["pending_canon"], int)       # counted off the already-loaded state, not a re-parse
        self.assertIsInstance(d["pending_reversal"], int)
        self.assertGreaterEqual(d["pending_reversal"], 0)

    def test_onclick_escaping_is_centralized(self):
        """XSS regression guard. Model/canon-authored names flow into onclick JS-strings inside double-quoted
        attributes; a bare `.replace(/'/g,...)` escapes only the single quote, so a name carrying a `"` closes
        the attribute and injects a live handler. Every such site must route through escJsAttr (which also
        entity-escapes the `"`), so the ONLY hand-rolled single-quote escape left in the page is escJsAttr's own
        definition — if a second one reappears, the class regressed."""
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=5) as r:
            html = r.read().decode()
        self.assertIn("const escJsAttr", html)                       # the centralized attribute+JS-string escaper
        self.assertIn("&quot;", html)                                # esc/escJsAttr emit the double-quote entity
        self.assertEqual(html.count("replace(/'/g"), 1,
                         "a hand-rolled single-quote escape reappeared outside escJsAttr — the XSS class regressed")

    def test_worlds_lists_example(self):
        self.assertIn("example", self._get("/api/worlds")["campaigns"])

    def test_graph_and_check(self):
        self.assertIn("nodes", self._get("/api/graph"))
        self.assertIn("findings", self._get("/api/check"))

    def test_npc_endpoint_composes_the_interior(self):
        pc = self._get("/api/player").get("name")            # there is always a PC in a live campaign
        if not pc:
            self.skipTest("no player character in the live campaign")
        d = self._get("/api/npc?name=" + urllib.parse.quote(pc))
        self.assertEqual(d["name"], pc)
        self.assertTrue(d["is_player"])
        for key in ("tier", "rung", "card", "mood", "agenda", "remembers", "remembers_player", "agenda_projected"):
            self.assertIn(key, d)                            # the whole interior composes (+ the display-projection flag)

    def test_npc_endpoint_404_for_unknown(self):
        try:
            self._get("/api/npc?name=DefinitelyNoSuchCharacterXYZ")
            self.fail("expected 404")
        except urllib.request.HTTPError as e:
            self.assertEqual(e.code, 404)
            e.close()                     # close the error response (else a ResourceWarning)

    def test_reversals_endpoint_lists_held(self):
        d = self._get("/api/reversals")                      # contradiction-repair pen (read-only)
        self.assertIn("reversals", d)
        self.assertIsInstance(d["reversals"], list)

    def test_world_endpoint_shape(self):
        d = self._get("/api/world")                          # the symbolic-object layer (read-only)
        self.assertIn("enabled", d)
        self.assertIsInstance(d["subjects"], list)
        self.assertIsInstance(d["count"], int)

    def test_ablation_endpoint_shape(self):
        d = self._get("/api/ablation")                       # the retrieval-miss instrument (read-only)
        self.assertIn("enabled", d)
        self.assertIsInstance(d["by_entity"], dict)
        self.assertIn("kill_criterion_met", d)

    def test_why_returns_the_provenance_ledger(self):
        d = self._get("/api/why")                    # whole ledger (read-only)
        self.assertIn("changes", d)
        self.assertIsInstance(d["changes"], list)
        self.assertIn("changes", self._get("/api/why?name=Nobody"))   # filtered form also structural

    def test_index_served(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=5) as r:
            self.assertIn(b"loom", r.read())


if __name__ == "__main__":
    unittest.main()
