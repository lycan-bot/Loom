"""config load/save round-trips (multi-world switching writes campaign here). Offline."""
import json
import tempfile
import unittest
from pathlib import Path
from loom import config


class ConfigTest(unittest.TestCase):
    def test_save_merges_and_persists(self):
        p = Path(tempfile.mkdtemp()) / "config.json"
        config.save({"campaign": "alpha"}, p)
        config.save({"mechanics": True}, p)          # merge, don't clobber
        d = json.loads(p.read_text())
        self.assertEqual(d["campaign"], "alpha")
        self.assertTrue(d["mechanics"])

    def test_load_merges_over_defaults(self):
        p = Path(tempfile.mkdtemp()) / "config.json"
        p.write_text('{"campaign":"beta"}')
        cfg = config.load(p)
        self.assertEqual(cfg["campaign"], "beta")
        self.assertEqual(cfg["llm_model"], "local")   # a default is preserved


if __name__ == "__main__":
    unittest.main()
