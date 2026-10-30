"""T-20 scheduled: the snapshot workflow's safety properties, and the restore / dedupe / append-only push flow (offline)."""

import datetime
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from pipeline import paths

sys.path.insert(0, os.path.join(paths.ROOT, "scripts"))
import publish_data  # noqa: E402
import snapshot_agendas as sa  # noqa: E402
from tests.test_snapshot_agendas import FakeApi, event, item  # noqa: E402

WF = os.path.join(paths.ROOT, ".github", "workflows", "snapshots.yml")


def text():
    with open(WF, encoding="utf-8") as f:
        return f.read().replace("\r\n", "\n")


def active(t):
    return [ln for ln in t.splitlines() if not ln.lstrip().startswith("#")]


class SnapshotWorkflowSafetyTests(unittest.TestCase):
    def setUp(self):
        self.t = text()
        self.lines = active(self.t)
        self.on = self.t.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]

    def test_triggers_are_a_schedule_and_a_manual_run_only(self):
        on = "\n".join(active(self.on))
        self.assertIn("schedule:", on)
        self.assertIn("workflow_dispatch:", on)
        for bad in ("pull_request", "pull_request_target", "push:", "issue_comment", "workflow_run", "repository_dispatch", "inputs:"):
            self.assertNotIn(bad, on, bad)
        self.assertEqual(len(re.findall(r"cron:", on)), 2)

    def test_it_runs_twice_a_day_once_before_and_once_after_a_council_afternoon(self):
        self.assertIn('"0 14 * * *"', self.t)
        self.assertIn('"30 23 * * *"', self.t)

    def test_permissions_are_read_only_except_the_one_write_the_push_needs(self):
        top = self.t.split("\npermissions:\n", 1)[1].split("\n\n", 1)[0].strip().splitlines()
        self.assertEqual([x.strip() for x in top], ["contents: read"])
        job = self.t.split("\njobs:\n", 1)[1]
        perms = re.search(r"permissions:\n((?:      .+\n)+)", job).group(1).split("\n")
        self.assertEqual([p.strip() for p in perms if p.strip()], ["contents: write"])
        for bad in ("id-token", "pages", "actions:", "pull-requests", "issues:"):
            self.assertNotIn(bad, "\n".join(self.lines), bad)

    def test_every_action_is_pinned_to_a_commit_sha(self):
        uses = [re.search(r"uses:\s*(\S+)", ln).group(1) for ln in self.lines if "uses:" in ln]
        self.assertEqual(len(uses), 2)
        for u in uses:
            self.assertRegex(u, r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$", u)

    def test_no_secret_and_no_model_anywhere(self):
        body = "\n".join(self.lines)
        self.assertNotIn("secrets.", body)
        for bad in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC", "claude-code", "npm install", "pipeline.run", "run_agent"):
            self.assertNotIn(bad, body, bad)

    def test_the_push_token_is_the_runs_own_and_the_checkout_keeps_no_credentials(self):
        self.assertIn("PUBLISH_TOKEN: ${{ github.token }}", self.t)
        self.assertIn("persist-credentials: false", self.t)

    def test_it_writes_to_its_own_branch_and_never_to_master_or_the_data_branch(self):
        cmd = next(ln for ln in self.lines if "snapshot_agendas.py" in ln)
        self.assertIn("--branch snapshots", cmd)
        for bad in ("--branch data", "--branch master", "--branch main"):
            self.assertNotIn(bad, cmd)
        self.assertNotIn("publish_data.py", "\n".join(self.lines))      # that script owns the data branch

    def test_a_concurrency_group_and_a_timeout(self):
        self.assertIn("group: agenda-snapshots", self.t)
        self.assertIn("timeout-minutes: 15", self.t)
        self.assertIn("cancel-in-progress: false", self.t)

    def test_nothing_in_the_nightly_pipeline_calls_the_snapshot(self):
        with open(os.path.join(paths.ROOT, ".github", "workflows", "nightly.yml"), encoding="utf-8") as f:
            self.assertNotIn("snapshot", f.read().lower())


TODAY = datetime.date(2026, 11, 2)
NOW = datetime.datetime(2026, 11, 3, 12, 0, 0, tzinfo=datetime.timezone.utc)


class SnapshotPushFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="showme-sp-")
        self.remote = os.path.join(self.tmp, "remote.git")
        subprocess.run(["git", "init", "--quiet", "--bare", self.remote], check=True)
        seed = os.path.join(self.tmp, "seed")
        os.makedirs(seed)
        for cmd in (["init", "--quiet"], ["config", "user.name", "t"], ["config", "user.email", "t@example.com"]):
            subprocess.run(["git", *cmd], cwd=seed, check=True)
        with open(os.path.join(seed, "code.py"), "w") as f:
            f.write("x\n")
        subprocess.run(["git", "add", "-A"], cwd=seed, check=True)
        subprocess.run(["git", "commit", "--quiet", "-m", "code"], cwd=seed, check=True)
        subprocess.run(["git", "push", "--quiet", self.remote, "HEAD:refs/heads/master"], cwd=seed, check=True)
        self.logs = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def tree(self, branch):
        return subprocess.run(["git", "ls-tree", "-r", "--name-only", branch], cwd=self.remote, capture_output=True, text=True).stdout.split()

    def go(self, api, hours=0, out=None):
        out = out or tempfile.mkdtemp(dir=self.tmp)           # a fresh runner every time: nothing carries over locally
        return sa.run(api, out, TODAY, 7, NOW + datetime.timedelta(hours=hours), True, self.remote, "snapshots", True, log=self.logs.append)

    def api(self, **kw):
        return FakeApi([event(1, "2026-11-05", **kw)], {1: [item(10, "100", 1), item(11, "101", 2)]})

    def test_the_first_run_creates_an_orphan_snapshots_branch_and_leaves_master_alone(self):
        self.go(self.api())
        files = self.tree("snapshots")
        self.assertEqual(len(files), 1)
        self.assertRegex(files[0], r"^1/20261103T120000Z\.json$")
        self.assertEqual(self.tree("master"), ["code.py"])
        self.assertNotIn("master", subprocess.run(["git", "branch", "--contains", "snapshots"], cwd=self.remote, capture_output=True, text=True).stdout)

    def test_an_unchanged_agenda_on_a_fresh_runner_adds_nothing(self):
        self.go(self.api())
        self.go(self.api(), hours=9)
        self.assertEqual(len(self.tree("snapshots")), 1)
        self.assertEqual(subprocess.run(["git", "rev-list", "--count", "snapshots"], cwd=self.remote, capture_output=True, text=True).stdout.strip(), "1")

    def test_a_revision_adds_a_second_file_and_the_original_stays(self):
        self.go(self.api())
        revised = FakeApi([event(1, "2026-11-05", status="Final-Revised", published="2026-11-05T21:10:00")],
                          {1: [item(10, "100", 1), item(11, "101", 2), item(12, "102", 3)]})
        self.go(revised, hours=30)
        files = self.tree("snapshots")
        self.assertEqual(sorted(files), ["1/20261103T120000Z.json", "1/20261104T180000Z.json"])

    def test_the_branch_is_append_only(self):
        d = tempfile.mkdtemp(dir=self.tmp)
        os.makedirs(os.path.join(d, "1"))
        with open(os.path.join(d, "1", "a.json"), "w") as f:
            f.write('{"v": 1}')
        publish_data.commit_tree(d, self.remote, "snapshots", "one")
        with open(os.path.join(d, "1", "a.json"), "w") as f:
            f.write('{"v": 2}')
        with self.assertRaises(FileExistsError):
            publish_data.commit_tree(d, self.remote, "snapshots", "two")
        self.assertEqual(subprocess.run(["git", "show", "snapshots:1/a.json"], cwd=self.remote, capture_output=True, text=True).stdout, '{"v": 1}')

    def test_a_snapshot_never_deletes_what_is_already_on_the_branch(self):
        d1 = tempfile.mkdtemp(dir=self.tmp)
        os.makedirs(os.path.join(d1, "1"))
        with open(os.path.join(d1, "1", "a.json"), "w") as f:
            f.write("{}")
        publish_data.commit_tree(d1, self.remote, "snapshots", "one")
        d2 = tempfile.mkdtemp(dir=self.tmp)                    # a run that has only a new file
        os.makedirs(os.path.join(d2, "2"))
        with open(os.path.join(d2, "2", "b.json"), "w") as f:
            f.write("{}")
        publish_data.commit_tree(d2, self.remote, "snapshots", "two")
        self.assertEqual(sorted(self.tree("snapshots")), ["1/a.json", "2/b.json"])

    def test_dry_run_and_save_without_push_do_not_touch_the_remote(self):
        sa.run(self.api(), tempfile.mkdtemp(dir=self.tmp), TODAY, 7, NOW, False, self.remote, "snapshots", True, log=self.logs.append)
        sa.run(self.api(), tempfile.mkdtemp(dir=self.tmp), TODAY, 7, NOW, True, self.remote, "snapshots", False, log=self.logs.append)
        branches = subprocess.run(["git", "branch", "--list", "snapshots"], cwd=self.remote, capture_output=True, text=True).stdout
        self.assertEqual(branches.strip(), "")

    def test_the_push_token_header_is_not_a_url_and_not_a_file(self):
        os.environ["PUBLISH_TOKEN"] = "tok-123"
        try:
            args = publish_data._auth_args("https://github.com/o/r.git")
            self.assertTrue(args and "tok-123" not in " ".join(args))
            self.go(self.api())                                 # a local remote: the header is unused and nothing breaks
            self.assertEqual(publish_data._AUTH, [])
        finally:
            del os.environ["PUBLISH_TOKEN"]

    def test_saved_files_hold_only_the_citys_rows(self):
        os.environ["PUBLISH_TOKEN"] = "tok-should-never-be-saved"
        try:
            self.go(self.api())
        finally:
            del os.environ["PUBLISH_TOKEN"]
        blob = subprocess.run(["git", "show", f"snapshots:{self.tree('snapshots')[0]}"], cwd=self.remote, capture_output=True, text=True).stdout
        self.assertNotIn("tok-should-never-be-saved", blob)
        self.assertNotIn("TOKEN", blob)


if __name__ == "__main__":
    unittest.main()
