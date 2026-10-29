"""Agent definitions load, the headless command is locked down, and the repo stays safe to publish."""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from pipeline import agents, paths

PIPELINE_AGENTS = ("extractor", "summarizer", "fact-checker")


class AgentDefinitionTests(unittest.TestCase):
    def test_pipeline_agents_load_with_a_pinned_model(self):
        for name in PIPELINE_AGENTS:
            a = agents.load_agent(name)
            self.assertTrue(a["model"].startswith("claude-"), name)
            self.assertIn("data", a["prompt"].lower(), f"{name} must say source text is data, not instructions")

    def test_schemas_are_valid_json(self):
        for s in ("extractor", "summarizer", "fact_checker"):
            self.assertEqual(agents.load_schema(s)["type"], "object")

    def test_command_has_no_tools_and_a_budget_cap(self):
        with mock.patch.dict(os.environ, {"SHOWME_BARE": ""}):
            cmd = agents.build_command("extractor", "extractor", "agents.json", 0.75)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        self.assertEqual(cmd[cmd.index("--max-budget-usd") + 1], "0.75")
        self.assertEqual(cmd[cmd.index("--agent") + 1], "extractor")
        json.loads(cmd[cmd.index("--json-schema") + 1])
        self.assertNotIn("--bare", cmd)

    def test_ci_mode_adds_bare(self):
        with mock.patch.dict(os.environ, {"SHOWME_BARE": "1", "ANTHROPIC_API_KEY": "test-placeholder"}):
            self.assertIn("--bare", agents.build_command("summarizer", "summarizer", "a.json", 1))

    def test_bare_without_api_key_fails_loudly(self):
        # Subscription auth can't use --bare; a silent fallback would fail mid-night instead.
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        env["SHOWME_BARE"] = "1"
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError):
                agents.build_command("summarizer", "summarizer", "a.json", 1)

    def test_subscription_token_survives_env_cleaning(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_OAUTH_TOKEN": "t", "CLAUDE_CODE_SESSION_ID": "x", "CLAUDECODE": "1"}):
            env = agents.clean_env()
        self.assertEqual(env.get("CLAUDE_CODE_OAUTH_TOKEN"), "t")
        self.assertNotIn("CLAUDE_CODE_SESSION_ID", env)
        self.assertNotIn("CLAUDECODE", env)

    def test_stray_api_key_cannot_switch_billing_in_subscription_mode(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "x", "SHOWME_BARE": ""}):
            self.assertNotIn("ANTHROPIC_API_KEY", agents.clean_env())
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "x", "SHOWME_BARE": "1"}):
            self.assertEqual(agents.clean_env()["ANTHROPIC_API_KEY"], "x")

    def test_stub_mode_never_calls_claude(self):
        stub = os.path.join(paths.FIXTURES, "kansascity", "stub")
        with mock.patch("subprocess.run", side_effect=AssertionError("called claude")):
            out, usage = agents.run_agent("extractor", "extractor", {}, tempfile.mkdtemp(), 1, stub_dir=stub)
        self.assertEqual(usage["cost_usd"], 0.0)
        self.assertTrue(out["claims"])


class RepoHygieneTests(unittest.TestCase):
    def tracked(self):
        r = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                           cwd=paths.ROOT, capture_output=True, text=True)
        return [f for f in r.stdout.splitlines() if f]

    def test_no_secrets_in_repo_files(self):
        pat = re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}|ANTHROPIC_API_KEY\s*=\s*['\"]?sk-")
        for f in self.tracked():
            p = os.path.join(paths.ROOT, f)
            if os.path.getsize(p) > 2_000_000:
                continue
            with open(p, encoding="utf-8", errors="ignore") as fh:
                self.assertIsNone(pat.search(fh.read()), f)

    def test_working_data_is_not_committed(self):
        for f in self.tracked():
            self.assertFalse(f.startswith(("data/raw/", "data/work/", "site/")), f)

    def test_site_carries_disclaimer_and_source_credit(self):
        from pipeline.site import FOOTER
        self.assertIn("Unofficial", FOOTER)
        self.assertIn("City of Kansas City, Missouri", FOOTER)

    def test_stop_hook_skips_pipeline_calls(self):
        r = subprocess.run([sys.executable, os.path.join(paths.ROOT, ".claude", "hooks", "check_on_stop.py")],
                           input="{}", capture_output=True, text=True, env=dict(os.environ, SHOWME_PIPELINE="1"))
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
