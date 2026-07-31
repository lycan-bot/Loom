"""The director: pays off ripe near threads on a stall, moves the world on a clock,
seeds new ones, and never lands mid-tension. Pure, offline."""
import unittest
from loom import director, pacing
from loom.threads import Thread


def P(directive, tension):
    return pacing.Pacing(directive, tension, 0.1, "")


class DirectorTest(unittest.TestCase):
    def test_hold_no_threads_is_none(self):
        self.assertEqual(director.decide([], [], P("hold", 0.2)).mode, "none")

    def test_offer_ready_near_pays_off(self):
        t = Thread("x", "the light", status="ready", readiness=0.9, entities=["The Lighthouse"])
        b = director.decide([t], ["The Lighthouse"], P("offer", 0.2), [])
        self.assertEqual(b.mode, "payoff")
        self.assertIs(b.thread, t)

    def test_offer_ready_but_not_near_no_payoff(self):
        t = Thread("x", "the light", status="ready", readiness=0.9, entities=["The Lighthouse"])
        b = director.decide([t], ["The Tavern"], P("offer", 0.2), [])
        self.assertEqual(b.mode, "hook")               # room, but nothing near → generic nudge

    def test_clock_moves_world_even_on_hold(self):
        c = Thread("s", "storm", kind="clock", status="ready", entities=["World"])
        self.assertEqual(director.decide([c], ["Harbor"], P("hold", 0.2), []).mode, "world")

    def test_high_tension_suppresses_everything(self):
        c = Thread("s", "storm", kind="clock", status="ready", entities=["World"])
        self.assertEqual(director.decide([c], ["Harbor"], P("hold", 0.8), []).mode, "none")

    def test_newly_seeded_plants_a_seed(self):
        t = Thread("x", "the light", status="seeded", entities=["The Lighthouse"])
        b = director.decide([t], ["The Lighthouse"], P("hold", 0.2), [t])
        self.assertEqual(b.mode, "seed")

    def test_settle_cools_payoff_and_resolves_world(self):
        t = Thread("x", "q", status="ready", readiness=0.9)
        director.settle(director.Beat("payoff", t))
        self.assertEqual(t.status, "ripening")
        self.assertEqual(t.readiness, 0.3)
        c = Thread("s", "storm", kind="clock", status="ready")
        director.settle(director.Beat("world", c))
        self.assertEqual(c.status, "resolved")

    def test_clause_shapes(self):
        t = Thread("x", "the light", payoff="a name surfaces", seed="still, dark water")
        self.assertIn("gentle opening", director.clause(director.Beat("payoff", t)))
        self.assertIn("WORLD MOVES", director.clause(director.Beat("world", t)))
        self.assertIn("faintest hint", director.clause(director.Beat("seed", t)))
        self.assertEqual(director.clause(director.Beat("none")), "")


if __name__ == "__main__":
    unittest.main()
