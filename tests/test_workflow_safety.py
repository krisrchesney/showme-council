"""The workflow runs on a public repo that holds a token secret. These pin what makes that safe,
and the report command the workflow uses for its summary."""

import os
import re
import unittest
from datetime import date

from pipeline import paths
from pipeline.run import nightly, report_markdown
from tests.helpers import DOC_ID, STUB, TempDataTest

WF = os.path.join(paths.ROOT, ".github", "workflows", "nightly.yml")


def workflow():
    with open(WF, encoding="utf-8") as f:
        return f.read().replace("\r\n", "\n")


def active_lines(text):
    return [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]


class WorkflowSafetyTests(unittest.TestCase):
    def setUp(self):
        self.text = workflow()
        self.lines = active_lines(self.text)

    def test_triggers_are_dispatch_and_at_most_the_one_nightly_schedule(self):
        on = self.text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertIn("workflow_dispatch:", on)
        for bad in ("pull_request", "pull_request_target", "push:", "issue_comment", "workflow_run", "repository_dispatch"):
            self.assertNotIn(bad, "\n".join(active_lines(on)), bad)
        crons = [ln.strip() for ln in active_lines(on) if "cron:" in ln]
        self.assertLessEqual(len(crons), 1)
        for c in crons:
            # The YAML list item reads `- cron: "..."`; compare the cron itself, exactly.
            self.assertEqual(c.split("#")[0].strip().removeprefix("- ").strip(), 'cron: "30 7 * * *"')

    def test_permissions_are_read_only(self):
        block = self.text.split("\npermissions:\n", 1)[1].split("\n\n", 1)[0].strip().splitlines()
        self.assertEqual([b.strip() for b in block], ["contents: read"])
        for bad in ("write", "id-token", "pages", "actions:"):
            self.assertNotIn(bad, "\n".join(self.lines).split("jobs:")[0].split("permissions:")[1], bad)

    def test_every_action_is_pinned_to_a_commit_sha(self):
        uses = [re.search(r"uses:\s*(\S+)", ln).group(1) for ln in self.lines if "uses:" in ln]
        self.assertGreaterEqual(len(uses), 3)
        for u in uses:
            self.assertRegex(u, r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$", u)

    def test_the_token_is_set_on_exactly_one_step_and_never_in_a_script(self):
        refs = [ln for ln in self.lines if "secrets." in ln]
        self.assertEqual([r.strip() for r in refs], ["CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}"])
        self.assertNotIn("ANTHROPIC_API_KEY", "\n".join(self.lines))
        self.assertNotIn("SHOWME_BARE", "\n".join(self.lines))

    def test_inputs_reach_the_shell_only_as_validated_env_vars(self):
        for ln in self.lines:
            if ln.strip().startswith("if:"):
                continue                      # a job condition is evaluated by Actions, never by a shell
            if "inputs." in ln or "github.event" in ln:
                self.assertRegex(ln, r"^\s+[A-Z_]+: \$\{\{ (inputs\.\w+|github\.event_name) \}\}$", ln)
        self.assertIn("bad doc_id", self.text)
        self.assertIn("bad mode", self.text)
        self.assertIn("bad days", self.text)
        self.assertIn("bad max_docs", self.text)

    def test_checkout_does_not_keep_credentials_and_the_job_has_a_timeout(self):
        self.assertIn("persist-credentials: false", self.text)
        self.assertIn("timeout-minutes:", self.text)

    def test_the_run_never_touches_the_repos_own_data(self):
        self.assertIn("SHOWME_DATA_DIR: ${{ runner.temp }}/showme-data", self.text)


def job_block(text, name):
    """The lines of one job (from '  name:' to the next top-level job or the end)."""
    jobs = text.split("\njobs:\n", 1)[1]
    m = re.search(rf"(?m)^  {name}:\n(.*?)(?=^  [a-z_-]+:\n|\Z)", jobs, re.S)
    return m.group(1)


class TwoJobSplitTests(unittest.TestCase):
    """The job that talks to the model can't write; the job that can write never touches the model."""

    def setUp(self):
        self.text = workflow()
        self.run_job = job_block(self.text, "run")
        self.build_job = job_block(self.text, "build")
        self.publish_job = job_block(self.text, "publish")

    def test_the_model_job_has_no_write_permissions(self):
        self.assertNotIn("permissions:", self.run_job)            # so it inherits the top-level contents: read
        for bad in ("write", "id-token", "deploy-pages", "publish_data.py --data \"$SHOWME_DATA_DIR\" --remote \"$REPO_URL\"\n"):
            self.assertNotIn(bad, self.run_job, bad)

    def test_the_write_job_has_exactly_the_three_permissions_and_no_model_token(self):
        perms = re.search(r"permissions:\n((?:      .+\n)+)", self.publish_job).group(1).split("\n")
        self.assertEqual(sorted(p.strip() for p in perms if p.strip()), ["contents: write", "id-token: write", "pages: write"])
        for bad in ("secrets.", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC", "pipeline.run", "claude "):
            self.assertNotIn(bad, self.publish_job, bad)

    def test_publishing_needs_an_explicit_yes_and_never_follows_a_dry_run(self):
        cond = re.search(r"(?m)^    if: (.+)$", self.publish_job).group(1)
        for needle in ("needs.run.outputs.publish == 'true'", "needs.run.outputs.mode == 'nightly'", "needs.run.outputs.dry_run == 'false'"):
            self.assertIn(needle, cond)
        self.assertIn("needs: [run, build]", self.publish_job)
        # a scheduled run publishes; a manual one only when asked. Both are settled in one validated step.
        self.assertIn('PUBLISH=true', self.run_job)
        self.assertIn("PUBLISH: ${{ inputs.publish }}", self.run_job)

    def test_defaults_are_the_safe_ones(self):
        self.assertRegex(self.text, r"dry_run:\n(?:        .+\n)*?        default: true")
        self.assertRegex(self.text, r"publish:\n(?:        .+\n)*?        default: false")
        self.assertRegex(self.text, r"mode:\n(?:        .+\n)*?        default: document")

    def test_the_night_restores_the_data_branch_before_running_and_only_for_real_nightly_runs(self):
        i_restore = self.run_job.index("Restore earlier results")
        i_run = self.run_job.index("Run the pipeline")
        self.assertLess(i_restore, i_run)
        step = self.run_job[i_restore:i_run]
        self.assertIn("steps.cfg.outputs.mode == 'nightly' && steps.cfg.outputs.dry_run == 'false'", step)
        self.assertIn("publish_data.py --restore", step)
        self.assertNotIn("secrets.", step)

    def test_window_defaults_are_small(self):
        self.assertRegex(self.text, r"days:\n(?:        .+\n)*?        default: \"3\"")
        self.assertRegex(self.text, r"max_docs:\n(?:        .+\n)*?        default: \"4\"")

    def test_a_scheduled_run_is_a_real_publishing_nightly_with_fixed_small_limits(self):
        self.assertIn('if [ "$EVENT" = "schedule" ]; then', self.run_job)
        self.assertIn("MODE=nightly; DRY_RUN=false; PUBLISH=true; DAYS=3; MAX_DOCS=4", self.run_job)

    def test_the_build_job_has_no_token_no_write_and_no_model(self):
        self.assertNotIn("permissions:", self.build_job)
        for bad in ("secrets.", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC", "PUBLISH_TOKEN", "claude ", "pipeline.run process", "pipeline.run nightly",
                    "write", "deploy-pages", "publish_data.py"):
            self.assertNotIn(bad, self.build_job, bad)
        self.assertIn("persist-credentials: false", self.build_job)

    def test_names_are_checked_against_roll_calls_after_the_model_and_before_the_artifact_is_uploaded(self):
        i_run, i_check, i_up = (self.run_job.index(x) for x in ("Run the pipeline", "Check names against the city's roll calls", "upload-artifact"))
        self.assertLess(i_run, i_check)
        self.assertLess(i_check, i_up)
        step = self.run_job[i_check:i_up]
        self.assertIn("pipeline.run verify-members", step)
        self.assertNotIn("secrets.", step)
        self.assertIn("steps.cfg.outputs.mode == 'nightly' && steps.cfg.outputs.dry_run == 'false'", step)

    def test_the_build_installs_the_requirements_before_it_imports_the_pipeline(self):
        self.assertLess(self.build_job.index("pip install -r requirements.txt"), self.build_job.index("backfill_rows.py"))

    def test_the_build_scans_for_private_text_before_it_uploads_the_site(self):
        self.assertLess(self.build_job.index("scan_site.py"), self.build_job.index("upload-pages-artifact"))
        self.assertIn("--accuracy site-inputs/topic_accuracy.json", self.build_job)
        self.assertIn("needs.run.outputs.mode == 'nightly' && needs.run.outputs.dry_run == 'false'", self.build_job)

    def test_there_is_one_publish_path_the_run_job_uploads_no_pages_artifact(self):
        self.assertNotIn("upload-pages-artifact", self.run_job)
        self.assertEqual(self.text.count("deploy-pages@"), 1)
        self.assertEqual(self.text.count("upload-pages-artifact@"), 1)

    def test_the_push_token_is_the_runs_own_and_only_on_the_write_job(self):
        self.assertIn("PUBLISH_TOKEN: ${{ github.token }}", self.publish_job)
        self.assertNotIn("PUBLISH_TOKEN", self.run_job)
        self.assertIn("persist-credentials: false", self.publish_job)


class ReportCommandTests(TempDataTest):
    def test_report_is_tokens_turns_and_time_not_dollars(self):
        nightly("kansascity", days=10, max_docs=4, loop_cap=4.0, fixture=True, stub_dir=STUB, today=date(2026, 10, 29))
        md = report_markdown(DOC_ID)
        self.assertIn("tokens in", md)
        self.assertIn("turns", md)
        self.assertIn("facts: 7 extracted, 3 passed", md)
        self.assertIn("voted-item coverage: 1 of", md)
        self.assertIn("fact-checker flags: 4 of 7", md)
        self.assertNotIn("$", md)
        self.assertNotIn("cost", md.lower())


if __name__ == "__main__":
    unittest.main()
