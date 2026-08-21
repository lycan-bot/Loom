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

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as r:
            return json.loads(r.read())

    def test_state(self):
        d = self._get("/api/state")
        self.assertIn("campaign", d)
        self.assertIsInstance(d["canon"], list)

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
