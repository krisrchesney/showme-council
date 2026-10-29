"""Usage is reported as tokens, turns and time. Dollar figures exist only as api_equiv_usd."""

import json
import os
import unittest
from datetime import date
from unittest import mock

from pipeline import agents, paths, run
from pipeline.run import _norm_usage, estimate, nightly, summarize_usage
from tests.helpers import DOC_ID, STUB, TempDataTest

STAGE = {"tokens_in": 1000, "tokens_out": 200, "num_turns": 2, "duration_s": 10.0,
         "api_equiv_usd": 0.05, "models": ["claude-sonnet-5-5"]}


class SummarizeTests(unittest.TestCase):
    def test_totals_and_per_stage(self):
        u = summarize_usage({"extractor": STAGE, "summarizer": dict(STAGE, tokens_in=500)})["usage"]
        self.assertEqual((u["tokens_in"], u["tokens_out"], u["turns"], u["seconds"]), (1500, 400, 4, 20.0))
        self.assertEqual(u["api_equiv_usd"], 0.1)
        self.assertEqual(u["by_stage"]["summarizer"]["tokens_in"], 500)

    def test_models_are_listed(self):
        self.assertEqual(summarize_usage({"extractor": STAGE})["models"], ["claude-sonnet-5-5"])

    def test_files_from_before_the_rename_still_load(self):
        old = {"cost_usd": 0.34, "num_turns": 2, "duration_s": 60.5,
               "usage": {"input_tokens": 2, "cache_creation_input_tokens": 23795, "cache_read_input_tokens": 0,
                         "output_tokens": 7720},
               "model_usage": {"claude-opus-5-5": {}}}
        n = _norm_usage(old)
        self.assertEqual((n["tokens_in"], n["tokens_out"], n["api_equiv_usd"]), (23797, 7720, 0.34))
        self.assertEqual(n["models"], ["claude-opus-5-5"])


class EstimateTests(TempDataTest):
    def test_estimate_leads_with_tokens_and_says_it_is_not_a_charge(self):
        run.ingest("kansascity", "2026-10-22", "2026-10-23", fixture=True)
        e = estimate(DOC_ID)
        self.assertGreater(e["tokens_in"], 40000)
        self.assertEqual(e["model"], "claude-sonnet-5-5")
        self.assertIn("not a charge", e["note"])
        self.assertNotIn("cost", json.dumps(e).lower())
        self.assertLess(e["api_equiv_usd"], estimate(DOC_ID, "claude-opus-5-5")["api_equiv_usd"])


class ReportTests(TempDataTest):
    def test_report_and_metrics_carry_usage_not_cost(self):
        nightly("kansascity", days=10, max_docs=4, loop_cap=4.0, fixture=True, stub_dir=STUB, today=date(2026, 10, 29))
        with open(paths.METRICS, encoding="utf-8") as f:
            line = f.read()
        rep = json.loads(line)
        self.assertEqual(set(rep["usage"]) & {"tokens_in", "tokens_out", "turns", "seconds", "api_equiv_usd"},
                         {"tokens_in", "tokens_out", "turns", "seconds", "api_equiv_usd"})
        self.assertEqual(rep["auth"], "subscription")
        self.assertNotIn("cost_usd", line)
        self.assertNotIn("cost_by_stage", line)

    def test_nightly_output_reports_tokens_and_time(self):
        with mock.patch("builtins.print") as pr:
            nightly("kansascity", days=10, max_docs=4, loop_cap=4.0, fixture=True, stub_dir=STUB, today=date(2026, 10, 29))
        out = " ".join(str(c.args[0]) for c in pr.call_args_list if c.args)
        self.assertIn("tokens in", out)
        self.assertNotIn("$", out)


class NoPerTokenBillingTests(unittest.TestCase):
    def test_api_key_and_bearer_token_never_reach_the_agent_process(self):
        env = {"ANTHROPIC_API_KEY": "k", "ANTHROPIC_AUTH_TOKEN": "t", "CLAUDE_CODE_OAUTH_TOKEN": "sub", "SHOWME_BARE": ""}
        with mock.patch.dict(os.environ, env):
            clean = agents.clean_env()
        self.assertNotIn("ANTHROPIC_API_KEY", clean)
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", clean)
        self.assertEqual(clean["CLAUDE_CODE_OAUTH_TOKEN"], "sub")

    def test_nightly_workflow_sets_only_the_subscription_token(self):
        with open(os.path.join(paths.ROOT, ".github", "workflows", "nightly.yml"), encoding="utf-8") as f:
            wf = f.read()
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}", wf)
        self.assertNotIn("ANTHROPIC_API_KEY: ${{", wf)
        self.assertNotIn('SHOWME_BARE: "1"', wf)


if __name__ == "__main__":
    unittest.main()
