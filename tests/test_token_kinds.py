"""Usage carries the four kinds of token (fresh input, cache read, cache write, output), backward compatible with older records."""

import unittest

from pipeline import agents
from pipeline.run import _norm_usage, summarize_usage

RAW = {"input_tokens": 2, "cache_read_input_tokens": 855, "cache_creation_input_tokens": 24037, "output_tokens": 10911}


class TokenKinds(unittest.TestCase):
    def test_breakdown_from_claudes_usage_block(self):
        self.assertEqual(agents.token_breakdown(RAW), {"input": 2, "cacheRead": 855, "cacheWrite": 24037, "output": 10911})
        self.assertEqual(agents.token_breakdown(None), {"input": 0, "cacheRead": 0, "cacheWrite": 0, "output": 0})

    def test_tokens_in_is_input_plus_cache_read_plus_cache_write(self):
        n = _norm_usage({"usage": RAW, "num_turns": 2, "duration_s": 1.0})
        self.assertEqual(n["tokens_in"], 2 + 855 + 24037)
        self.assertEqual(n["tokens"], {"input": 2, "cacheRead": 855, "cacheWrite": 24037, "output": 10911})

    def test_a_saved_stage_with_the_new_field_keeps_it(self):
        t = {"input": 1, "cacheRead": 2, "cacheWrite": 3, "output": 4}
        self.assertEqual(_norm_usage({"tokens_in": 6, "tokens_out": 4, "tokens": t})["tokens"], t)

    def test_an_older_record_without_the_raw_block_has_no_breakdown_and_nothing_is_invented(self):
        n = _norm_usage({"tokens_in": 73182, "tokens_out": 11869, "num_turns": 2, "duration_s": 3.0})
        self.assertIsNone(n["tokens"])
        self.assertEqual(n["tokens_in"], 73182)

    def test_totals_add_up_only_when_every_stage_has_a_breakdown(self):
        a = {"tokens_in": 10, "tokens_out": 5, "tokens": {"input": 1, "cacheRead": 4, "cacheWrite": 5, "output": 5}, "num_turns": 2, "duration_s": 1.0}
        b = dict(a)
        u = summarize_usage({"x": a, "y": b})["usage"]
        self.assertEqual(u["tokens"], {"input": 2, "cacheRead": 8, "cacheWrite": 10, "output": 10})
        self.assertEqual(u["tokens_in"], 20)
        old = {"tokens_in": 10, "tokens_out": 5, "num_turns": 2, "duration_s": 1.0}
        self.assertIsNone(summarize_usage({"x": a, "y": old})["usage"]["tokens"])

    def test_stub_runs_report_zero_of_every_kind(self):
        self.assertEqual(agents.add_breakdowns([agents.token_breakdown({})]), {"input": 0, "cacheRead": 0, "cacheWrite": 0, "output": 0})


if __name__ == "__main__":
    unittest.main()
