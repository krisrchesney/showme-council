"""T-21: the workflow that deploys the reviewed explorer site is manual, secret-free and pinned."""

import os
import re
import unittest

from pipeline import paths

PATH = os.path.join(paths.ROOT, ".github", "workflows", "explorer.yml")


class ExplorerWorkflow(unittest.TestCase):
    def setUp(self):
        with open(PATH, encoding="utf-8") as f:
            self.text = f.read()
        self.code = "\n".join(l for l in self.text.splitlines() if not l.lstrip().startswith("#"))

    def test_manual_only(self):
        self.assertRegex(self.code, r"(?m)^on:\n  workflow_dispatch:\n")
        for trigger in ("push:", "pull_request", "schedule:", "issue_comment", "workflow_run"):
            self.assertNotIn(trigger, self.code)

    def test_no_secrets_and_no_model(self):
        self.assertNotIn("secrets.", self.code)
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", self.code)
        self.assertNotIn("run:", self.code)

    def test_every_action_is_pinned_to_a_commit_sha(self):
        uses = re.findall(r"uses:\s*(\S+)", self.code)
        self.assertEqual(len(uses), 3)
        for u in uses:
            self.assertRegex(u, r"@[0-9a-f]{40}$")

    def test_minimal_permissions_and_no_kept_credentials(self):
        self.assertRegex(self.code, r"(?m)^permissions:\n  contents: read\n")
        self.assertIn("pages: write", self.code)
        self.assertIn("id-token: write", self.code)
        self.assertNotIn("contents: write", self.code)
        self.assertIn("persist-credentials: false", self.code)

    def test_it_deploys_only_the_public_folder_of_the_site_branch(self):
        self.assertIn("ref: site", self.code)
        self.assertIn("path: public", self.code)


if __name__ == "__main__":
    unittest.main()
