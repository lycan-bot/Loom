"""Sampler-level anti-repetition: DRY + frequency penalty ride NARRATION calls (chat / chat_stream)
but NOT the structured archivist calls (response_format set), which want clean JSON. Offline —
_post is stubbed, no server. The repetition on this model is a sampling attractor (a re-roll escapes
it), so it's fixed at the sampler, not the prompt."""
import unittest
from loom import llm, config


def _cfg(**over):
    c = {"llm_model": "m", "llm_url": "u", "api_key": "", "max_tokens": 100,
         "temperature": 0.8, "request_timeout": 30}
    c.update({k: config.DEFAULTS[k] for k in
              ("anti_repetition", "dry_multiplier", "dry_base", "dry_allowed_length",
               "frequency_penalty", "presence_penalty")})
    c.update(over)
    return c


class AntiRepetitionTest(unittest.TestCase):
    def _capture_chat(self, cfg, **kw):
        cap = {}
        orig = llm._post
        llm._post = lambda url, payload, key, to: (cap.update(payload),
                                                   {"choices": [{"message": {"content": "hi"}}]})[1]
        try:
            llm.chat([{"role": "user", "content": "x"}], cfg, **kw)
        finally:
            llm._post = orig
        return cap

    def test_params_ride_narration(self):
        cap = self._capture_chat(_cfg())
        self.assertEqual(cap.get("dry_multiplier"), 0.8)
        self.assertEqual(cap.get("frequency_penalty"), 0.3)
        self.assertIn("dry_allowed_length", cap)

    def test_params_absent_on_structured_calls(self):
        # a consolidation/archivist call sets response_format → must stay clean (no DRY/penalty)
        cap = self._capture_chat(_cfg(), response_format={"type": "json_object"})
        self.assertNotIn("dry_multiplier", cap)
        self.assertNotIn("frequency_penalty", cap)

    def test_toggle_off_sends_nothing(self):
        cap = self._capture_chat(_cfg(anti_repetition=False))
        self.assertNotIn("dry_multiplier", cap)
        self.assertNotIn("frequency_penalty", cap)


if __name__ == "__main__":
    unittest.main()
