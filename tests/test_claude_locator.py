"""Finding the claude CLI without assuming PATH or an %APPDATA% that only resolves inside the desktop app."""

import os
import shutil
import tempfile
import unittest

from pipeline.agents import EXE, find_claude, login_instructions


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("x")
    return path


class LocatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="showme-claude-")
        self.home = os.path.join(self.tmp, "home")
        self.local = os.path.join(self.tmp, "Local")
        self.roaming = os.path.join(self.tmp, "Roaming")
        os.makedirs(self.home)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def packaged(self, version, h="abc123"):
        return touch(os.path.join(self.local, "Packages", "Claude_pzs8sxrjxfjjc", "LocalCache", "Roaming",
                                  "Claude", "claude-code", version, h, EXE))

    def find(self, **env):
        base = {"LOCALAPPDATA": self.local, "APPDATA": self.roaming}
        base.update(env)
        return find_claude(env=base, which=lambda _: None, home=self.home)

    def test_newest_version_wins_numerically_not_alphabetically(self):
        self.packaged("2.1.9")
        newest = self.packaged("2.1.10")
        self.packaged("2.1.299", "h1")      # a real-looking later folder
        path, how = self.find()
        self.assertTrue(path.endswith(os.path.join("2.1.299", "h1", EXE)), path)
        os.remove(path)
        self.assertEqual(self.find()[0], newest)    # 2.1.10 beats 2.1.9 ("2.1.9" > "2.1.10" as text)
        self.assertIn("bundled", how)

    def test_packaged_location_beats_the_appdata_redirect(self):
        touch(os.path.join(self.roaming, "Claude", "claude-code", "2.9.9", "zz", EXE))
        real = self.packaged("2.1.5")
        self.assertEqual(self.find()[0], real)

    def test_appdata_is_used_when_nothing_else_exists(self):
        only = touch(os.path.join(self.roaming, "Claude", "claude-code", "2.1.1", "zz", EXE))
        self.assertEqual(self.find()[0], only)

    def test_order_explicit_then_path_then_standalone_then_bundled(self):
        self.packaged("2.1.299")
        standalone = touch(os.path.join(self.home, ".local", "bin", EXE))
        self.assertEqual(self.find()[0], standalone)
        on_path = touch(os.path.join(self.tmp, "bin", EXE))
        got = find_claude(env={"LOCALAPPDATA": self.local}, which=lambda _: on_path, home=self.home)
        self.assertEqual(got, (on_path, "PATH"))
        explicit = touch(os.path.join(self.tmp, "mine", EXE))
        got = find_claude(env={"CLAUDE_BIN": explicit}, which=lambda _: on_path, home=self.home)
        self.assertEqual(got, (explicit, "CLAUDE_BIN"))

    def test_bad_claude_bin_is_an_error_not_a_silent_fallback(self):
        self.packaged("2.1.299")
        with self.assertRaises(FileNotFoundError) as cm:
            self.find(CLAUDE_BIN=os.path.join(self.tmp, "nope.exe"))
        self.assertIn("CLAUDE_BIN", str(cm.exception))

    def test_nothing_found_lists_where_it_looked_and_how_to_install(self):
        with self.assertRaises(FileNotFoundError) as cm:
            self.find()
        msg = str(cm.exception)
        self.assertIn("PATH", msg)
        self.assertIn("Packages", msg)
        self.assertIn("install.ps1", msg)

    def test_login_instruction_uses_the_full_path(self):
        p = self.packaged("2.1.299")
        cmd = login_instructions(p)
        self.assertEqual(cmd, f'& "{p}" auth login')
        self.assertNotIn("%APPDATA%", cmd)
        self.assertTrue(os.path.isabs(p))


class DocsDontSendUsersDownTheWrongPathTests(unittest.TestCase):
    def test_user_facing_docs_have_no_appdata_login_command(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ("README.md", "DESIGN.md", "CLAUDE.md", "TASKS.md"):
            with open(os.path.join(root, name), encoding="utf-8") as f:
                text = f.read()
            self.assertNotIn("$env:APPDATA\\Claude\\claude-code", text, name)

    def test_docs_name_the_secret_and_forbid_putting_it_in_files_or_chat(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "TASKS.md"), encoding="utf-8") as f:
            t1 = f.read().split("### T-2")[0]
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", t1)
        self.assertIn("never go in", t1)
        self.assertIn("chat", t1)


if __name__ == "__main__":
    unittest.main()
