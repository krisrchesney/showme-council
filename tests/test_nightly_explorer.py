"""T-22: the nightly builds the explorer. The private-text scan, the tracked site inputs, and the wording that depends on a schedule."""

import json
import os
import sys
import tempfile
import unittest

from pipeline import explore, paths

sys.path.insert(0, os.path.join(paths.ROOT, "scripts"))
import scan_site  # noqa: E402
from tests.test_explore import fixture_history  # noqa: E402

INPUTS = os.path.join(paths.ROOT, "site-inputs")


def write(d, name, text):
    path = os.path.join(d, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class ScanTests(unittest.TestCase):
    def test_clean_site_passes(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "index.html", "<p>Data: City of Kansas City, Missouri, published through Legistar.</p><a href='https://github.com/krisrchesney/showme-council/issues'>x</a>")
            self.assertEqual(scan_site.scan(d), [])
            self.assertEqual(scan_site.main([d]), 0)

    def test_each_kind_of_private_text_is_caught_and_never_printed(self):
        # built from pieces so this file itself holds none of the strings the repo's hygiene tests look for
        bad = {"a.html": "CLAUDE_CODE_OAUTH" + "_TOKEN", "b.html": "key sk-" + "ant-abcdefgh12345", "c.json": "Authorization: Bearer abc123",
               "d.html": "C" + ":\\Us" + "ers\\Someone\\project", "e.html": "https://claude" + ".ai/arti" + "fact/abc",
               "f.html": "write to person@example.com", "g.js": "ghp_" + "a" * 24}
        with tempfile.TemporaryDirectory() as d:
            for name, text in bad.items():
                write(d, name, text)
            got = {p for p, _ in scan_site.scan(d)}
            self.assertEqual(got, set(bad))
            self.assertEqual(scan_site.main([d]), 1)

    def test_the_built_fixture_site_is_clean(self):
        site = explore.build_explorer("unused", "unused", accuracy=None, built_at="2026-01-01 00:00 UTC", load_history=fixture_history)
        with tempfile.TemporaryDirectory() as d:
            site.write(d)
            self.assertEqual(scan_site.scan(d), [])


class SiteInputs(unittest.TestCase):
    def test_tracked_inputs_parse_and_are_public_safe(self):
        with open(os.path.join(INPUTS, "topic_accuracy.json"), encoding="utf-8") as f:
            acc = json.load(f)
        self.assertEqual(acc["n"], 300)
        self.assertIn("per_topic", acc)
        self.assertIn("public_safety", explore.folded_topics(acc))
        self.assertIn("parks_recreation", explore.folded_topics(acc))
        with open(os.path.join(INPUTS, "labels", "labels-19561.json"), encoding="utf-8") as f:
            labs = json.load(f)["labels"]
        self.assertTrue(all("label" in v and "shown" in v for v in labs.values()))
        with tempfile.TemporaryDirectory() as d:
            for root, _, files in os.walk(INPUTS):
                for name in files:
                    with open(os.path.join(root, name), encoding="utf-8") as f:
                        write(d, name, f.read())
            self.assertEqual(scan_site.scan(d), [])


class WordingTests(unittest.TestCase):
    def build(self, scheduled):
        site = explore.build_explorer("unused", "unused", built_at="2026-01-01 00:00 UTC", load_history=fixture_history, scheduled=scheduled)
        return site.pages["about.html"]

    def test_the_site_says_nightly_only_when_it_was_built_by_the_schedule(self):
        self.assertIn("run by hand so far", self.build(False))
        self.assertNotIn("it runs every night", self.build(False))
        self.assertIn("it runs every night", self.build(True))


if __name__ == "__main__":
    unittest.main()
