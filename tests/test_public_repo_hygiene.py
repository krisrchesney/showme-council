"""This repo is public. Nothing personal or private belongs in its files: not the private board's link, not
local paths with the Windows account name, not tokens. (History can't be rewritten, so catch it before commit.)"""

import os
import re
import subprocess
import unittest

from pipeline import paths

# Built by concatenation so this file doesn't match its own patterns.
PRIVATE_LINK = re.compile("claude" + r"\.ai/(artifact|code)/")
LOCAL_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]+Users[\\/]")
GITHUB_TOKENS = re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-ant-[A-Za-z0-9_-]{10,})")


def tracked():
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                         cwd=paths.ROOT, capture_output=True, text=True).stdout.splitlines()
    return [f for f in out if f and os.path.isfile(os.path.join(paths.ROOT, f))]


def text_of(rel):
    p = os.path.join(paths.ROOT, rel)
    if os.path.getsize(p) > 2_000_000:
        return ""
    with open(p, encoding="utf-8", errors="ignore") as f:
        return f.read()


class PublicRepoHygieneTests(unittest.TestCase):
    def hits(self, pattern):
        return [f for f in tracked() if pattern.search(text_of(f))]

    def test_no_private_artifact_or_session_links(self):
        self.assertEqual(self.hits(PRIVATE_LINK), [])

    def test_no_absolute_local_paths(self):
        self.assertEqual(self.hits(LOCAL_PATH), [])

    def test_no_github_or_anthropic_tokens(self):
        self.assertEqual(self.hits(GITHUB_TOKENS), [])

    def test_claude_md_points_to_the_board_without_naming_it(self):
        t = text_of("CLAUDE.md")
        self.assertIn("../CommandCenter/CLAUDE.md", t)
        self.assertNotRegex(t, PRIVATE_LINK)


if __name__ == "__main__":
    unittest.main()
