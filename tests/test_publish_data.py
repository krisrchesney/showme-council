"""Commit-back to the data branch, tested against a throwaway local 'remote' (no network, no GitHub)."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import publish_data  # noqa: E402


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


class PublishDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="showme-pd-")
        self.remote = os.path.join(self.tmp, "remote.git")
        subprocess.run(["git", "init", "--quiet", "--bare", self.remote], check=True)
        # give the remote a master with code in it, to prove the data branch stays separate
        seed = os.path.join(self.tmp, "seed")
        os.makedirs(seed)
        git(seed, "init", "--quiet")
        git(seed, "config", "user.name", "t")
        git(seed, "config", "user.email", "t@example.com")
        with open(os.path.join(seed, "code.py"), "w") as f:
            f.write("print('code')\n")
        git(seed, "add", "-A")
        git(seed, "commit", "--quiet", "-m", "code")
        git(seed, "push", "--quiet", self.remote, "HEAD:refs/heads/master")
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(os.path.join(self.data, "published"))
        os.makedirs(os.path.join(self.data, "raw", "doc"))      # working data: must never be copied
        os.makedirs(os.path.join(self.data, "work", "doc"))
        self.write("state.json", {"docs": {"a": {"status": "ok"}}})
        self.write("published/a.json", {"headline": "A"})
        self.write("raw/doc/source.txt", "raw")
        self.write("work/doc/facts.json", {"claims": []})
        with open(os.path.join(self.data, "metrics.jsonl"), "w") as f:
            f.write('{"doc_id": "a"}\n')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, obj):
        p = os.path.join(self.data, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(obj if isinstance(obj, str) else json.dumps(obj))

    def tree(self, branch):
        return set(git(self.remote, "ls-tree", "-r", "--name-only", branch).split())

    def test_first_run_creates_an_orphan_data_branch_with_only_the_record(self):
        committed, changed, pushed = publish_data.publish(self.data, self.remote)
        self.assertEqual((committed, pushed), (True, True))
        self.assertEqual(self.tree("data"), {"state.json", "metrics.jsonl", "published/a.json"})
        self.assertEqual(self.tree("master"), {"code.py"})            # master untouched
        self.assertEqual(git(self.remote, "rev-list", "--count", "data").strip(), "1")
        self.assertNotIn("master", git(self.remote, "branch", "--contains", "data"))

    def test_working_data_is_never_copied(self):
        publish_data.publish(self.data, self.remote)
        self.assertFalse([p for p in self.tree("data") if p.startswith(("raw/", "work/"))])

    def test_a_second_identical_run_commits_nothing(self):
        publish_data.publish(self.data, self.remote)
        committed, changed, pushed = publish_data.publish(self.data, self.remote)
        self.assertEqual((committed, changed, pushed), (False, [], False))
        self.assertEqual(git(self.remote, "rev-list", "--count", "data").strip(), "1")

    def test_new_results_add_a_commit_and_removed_pages_disappear(self):
        publish_data.publish(self.data, self.remote)
        self.write("published/b.json", {"headline": "B"})
        os.remove(os.path.join(self.data, "published", "a.json"))
        committed, changed, pushed = publish_data.publish(self.data, self.remote)
        self.assertTrue(committed and pushed)
        self.assertEqual(self.tree("data"), {"state.json", "metrics.jsonl", "published/b.json"})
        self.assertEqual(git(self.remote, "rev-list", "--count", "data").strip(), "2")

    def test_dry_run_reports_the_change_but_pushes_nothing(self):
        committed, changed, pushed = publish_data.publish(self.data, self.remote, dry_run=True)
        self.assertEqual((committed, pushed), (True, False))
        self.assertIn("published/a.json", changed)
        r = subprocess.run(["git", "branch", "--list", "data"], cwd=self.remote, capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "")                       # the branch was not created

    def test_the_commit_is_by_the_bot_not_by_a_person(self):
        publish_data.publish(self.data, self.remote)
        self.assertEqual(git(self.remote, "log", "-1", "--format=%an", "data").strip(), "showme-council bot")


if __name__ == "__main__":
    unittest.main()
