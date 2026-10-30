"""Nightly is minutes-only until the agenda-vs-minutes guard exists, and a night starts from what was published."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date

from pipeline import run
from pipeline.run import load_state, nightly
from tests.helpers import DOC_ID, STUB, TempDataTest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import publish_data  # noqa: E402


class MinutesOnlyTests(TempDataTest):
    def test_ingest_fetches_only_minutes_by_default(self):
        ids = run.ingest("kansascity", "2026-10-22", "2026-10-23", fixture=True)
        self.assertEqual(ids, [DOC_ID])

    def test_agendas_are_fetched_only_when_asked_for(self):
        ids = run.ingest("kansascity", "2026-10-22", "2026-10-23", fixture=True, kinds=("minutes", "agenda"))
        self.assertEqual(ids, [DOC_ID])        # the fixture has no agenda text, so the agenda fails ingest...
        self.assertEqual(load_state()["docs"]["kc-19561-agenda"]["status"], "error")   # ...and that is recorded

    def test_a_default_night_never_touches_an_agenda(self):
        nightly("kansascity", days=10, max_docs=4, loop_cap=4.0, fixture=True, stub_dir=STUB, today=date(2026, 10, 29))
        self.assertNotIn("kc-19561-agenda", load_state()["docs"])


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="showme-rs-")
        self.remote = os.path.join(self.tmp, "remote.git")
        subprocess.run(["git", "init", "--quiet", "--bare", self.remote], check=True)
        self.data = os.path.join(self.tmp, "night1")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, base, rel, text):
        p = os.path.join(base, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)

    def test_no_data_branch_yet_means_start_from_nothing(self):
        target = os.path.join(self.tmp, "fresh")
        self.assertFalse(publish_data.restore(target, self.remote))
        self.assertFalse(os.path.exists(os.path.join(target, "state.json")))

    def test_tonight_starts_from_everything_published_so_far(self):
        self.write(self.data, "state.json", json.dumps({"docs": {"a": {"status": "ok"}}}))
        self.write(self.data, "metrics.jsonl", '{"doc_id": "a"}\n')
        self.write(self.data, "published/a.json", '{"headline": "A"}')
        publish_data.publish(self.data, self.remote)

        night2 = os.path.join(self.tmp, "night2")
        self.assertTrue(publish_data.restore(night2, self.remote))
        with open(os.path.join(night2, "state.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["docs"]["a"]["status"], "ok")
        self.assertTrue(os.path.exists(os.path.join(night2, "published", "a.json")))

    def test_a_second_night_adds_to_the_record_instead_of_replacing_it(self):
        self.write(self.data, "state.json", "{}")
        self.write(self.data, "published/a.json", '{"headline": "A"}')
        publish_data.publish(self.data, self.remote)
        night2 = os.path.join(self.tmp, "night2")
        publish_data.restore(night2, self.remote)
        self.write(night2, "published/b.json", '{"headline": "B"}')
        publish_data.publish(night2, self.remote)
        tree = subprocess.run(["git", "ls-tree", "-r", "--name-only", "data"], cwd=self.remote, capture_output=True, text=True).stdout.split()
        self.assertEqual(sorted(p for p in tree if p.startswith("published/")), ["published/a.json", "published/b.json"])

    def test_without_a_restore_a_night_would_erase_earlier_pages(self):
        # This is the bug the restore step exists to prevent.
        self.write(self.data, "published/a.json", '{"headline": "A"}')
        publish_data.publish(self.data, self.remote)
        lonely = os.path.join(self.tmp, "lonely")
        self.write(lonely, "published/b.json", '{"headline": "B"}')
        publish_data.publish(lonely, self.remote)
        tree = subprocess.run(["git", "ls-tree", "-r", "--name-only", "data"], cwd=self.remote, capture_output=True, text=True).stdout.split()
        self.assertEqual([p for p in tree if p.startswith("published/")], ["published/b.json"])

    def test_restore_writes_only_inside_the_data_dir(self):
        self.write(self.data, "published/a.json", "{}")
        publish_data.publish(self.data, self.remote)
        target = os.path.join(self.tmp, "t", "d")
        publish_data.restore(target, self.remote)
        self.assertEqual(sorted(os.listdir(os.path.join(self.tmp, "t"))), ["d"])


if __name__ == "__main__":
    unittest.main()
