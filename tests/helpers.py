"""Shared test setup: point every pipeline path at a throwaway folder."""

import os
import shutil
import tempfile
import unittest

from pipeline import paths

STUB = os.path.join(paths.FIXTURES, "kansascity", "stub")
FIXTURE_DATE = "2026-10-22"     # the cached KC Council meeting (event 19561)
DOC_ID = "kc-19561-minutes"


class TempDataTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="showme-test-")
        self._saved = {k: getattr(paths, k) for k in ("DATA", "RAW", "WORK", "PUBLISHED", "STATE", "METRICS", "SITE")}
        d = os.path.join(self.tmp, "data")
        paths.DATA, paths.RAW, paths.WORK = d, os.path.join(d, "raw"), os.path.join(d, "work")
        paths.PUBLISHED, paths.STATE = os.path.join(d, "published"), os.path.join(d, "state.json")
        paths.METRICS, paths.SITE = os.path.join(d, "metrics.jsonl"), os.path.join(self.tmp, "site")

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(paths, k, v)
        shutil.rmtree(self.tmp, ignore_errors=True)
