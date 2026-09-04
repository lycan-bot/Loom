"""The CLI arg parsing for `loom clock` (the blessed-countdown seed path). Pure, offline."""
import unittest
from loom.__main__ import _clock_args


class ClockArgsTest(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_clock_args(["the eclipse comes", "30"]), ("the eclipse comes", 30, False, ""))

    def test_hidden_flag(self):
        self.assertEqual(_clock_args(["the god wakes", "12", "hidden"]), ("the god wakes", 12, True, ""))
        self.assertTrue(_clock_args(["x", "3", "--hidden"])[2])

    def test_seed_runs_to_end(self):
        q, span, hidden, seed = _clock_args(["the storm", "5", "hidden", "--seed", "the birds have gone quiet"])
        self.assertEqual((q, span, hidden), ("the storm", 5, True))
        self.assertEqual(seed, "the birds have gone quiet")

    def test_bad_usage(self):
        self.assertEqual(_clock_args([]), (None, None, False, ""))                       # nothing
        self.assertEqual(_clock_args(["only a question"]), (None, None, False, ""))      # missing beats
        self.assertIsNone(_clock_args(["q", "notanumber"])[1])                           # non-int beats → span None
        self.assertEqual(_clock_args(["q", "notanumber"])[0], "q")                       # …question still parsed

    def test_clock_payload_hidden_is_a_horizon(self):
        # red-team fix: a hidden CLI clock must carry scope='horizon' or the world-round dread never fires
        from loom.__main__ import _clock_payload
        h = _clock_payload("the god wakes", 8, True, "")
        self.assertEqual((h["scope"], h["hidden"], h["kind"], h["clock"], h["span"]),
                         ("horizon", True, "clock", 8, 8))
        v = _clock_payload("the eclipse", 30, False, "")
        self.assertEqual((v["scope"], v["hidden"]), ("local", False))                    # a visible countdown is local


if __name__ == "__main__":
    unittest.main()
