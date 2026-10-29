"""Coverage against the city's own vote record, and the stop when the default model covers too little.

The fixtures under tests/fixtures/kansascity/runs/ are the saved agent outputs of two real runs on the
2026-10-22 minutes: Opus 5.5, and Sonnet 5.5 with the first extractor prompt.
"""

import glob
import json
import os
import unittest
from unittest import mock

from pipeline import paths, run
from pipeline.run import ESCALATION_MODEL, NeedsStrongerModel, process
from pipeline.verify import COVERAGE_MIN, COVERAGE_MIN_ITEMS, code_checks, coverage, decide, split_pages
from tests.helpers import DOC_ID, TempDataTest

FIX = os.path.join(paths.FIXTURES, "kansascity")
META = {"doc_id": DOC_ID, "body": "Council", "kind": "minutes", "date": "2026-10-22"}


def load(*parts):
    with open(os.path.join(FIX, *parts), encoding="utf-8") as f:
        return json.load(f)


def rescore(run_name):
    with open(glob.glob(os.path.join(FIX, "*Minutes.txt"))[0], encoding="utf-8") as f:
        pages = split_pages(f.read())
    items = load("eventitems_19561.json")
    claims = load("runs", run_name, "facts.json")["claims"]
    checks = {c["id"]: code_checks(c, pages, META, items) for c in claims}
    res = decide(META, claims, checks, load("runs", run_name, "summary.json"), load("runs", run_name, "verdicts.json"))
    return coverage(META, items, res["accepted"]), res


class CoverageNumbersTests(unittest.TestCase):
    def test_opus_covers_19_of_29_recorded_votes(self):
        cov, _ = rescore("opus")
        self.assertEqual((cov["covered"], cov["voted"]), (19, 29))

    def test_sonnet_first_prompt_covers_4_of_29(self):
        cov, _ = rescore("sonnet-prompt1")
        self.assertEqual((cov["covered"], cov["voted"]), (4, 29))

    def test_the_floor_separates_them(self):
        self.assertGreater(rescore("opus")[0]["rate"], COVERAGE_MIN)
        self.assertLess(rescore("sonnet-prompt1")[0]["rate"], COVERAGE_MIN)

    def test_floor_has_not_been_lowered(self):
        # Lowering it to let a run through is the "gaming the check" failure in CLAUDE.md.
        self.assertGreaterEqual(COVERAGE_MIN, 0.40)
        self.assertGreaterEqual(COVERAGE_MIN_ITEMS, 5)

    def test_missing_items_are_listed(self):
        cov, _ = rescore("sonnet-prompt1")
        self.assertEqual(len(cov["missing"]), 25)
        self.assertNotIn("260895", cov["missing"])      # a fact Sonnet extracted and that passed
        self.assertIn("260919", cov["missing"])         # its only fact for this item was rejected, so not covered

    def test_agendas_and_empty_meetings_have_nothing_to_measure(self):
        items = load("eventitems_19561.json")
        self.assertIsNone(coverage(dict(META, kind="agenda"), items, []))
        self.assertIsNone(coverage(META, [], []))

    def test_an_unaccepted_claim_does_not_count(self):
        items = [{"EventItemMatterFile": "1", "EventItemPassedFlagName": "Pass"},
                 {"EventItemMatterFile": "2", "EventItemPassedFlagName": "Pass"}]
        cov = coverage(META, items, [{"matter_file": "1"}])
        self.assertEqual((cov["covered"], cov["voted"], cov["missing"]), (1, 2, ["2"]))


def fake_agents(run_name):
    """run_agent stand-in that returns a saved real run's outputs, with no model call."""
    files = {"extractor": "facts.json", "summarizer": "summary.json", "fact-checker": "verdicts.json"}

    def fake(name, schema, payload, out_dir, loop_cap, stub_dir=None, timeout=900, model=None):
        return load("runs", run_name, files[name]), {"tokens_in": 0, "tokens_out": 0, "num_turns": 0,
                                                       "duration_s": 0.0, "api_equiv_usd": 0.0, "models": []}
    return fake


class CoverageStopTests(TempDataTest):
    def setUp(self):
        super().setUp()
        run.ingest("kansascity", "2026-10-22", "2026-10-23", fixture=True)

    def test_thin_extraction_on_the_default_model_stops_and_names_opus(self):
        with mock.patch.object(run, "run_agent", fake_agents("sonnet-prompt1")):
            with self.assertRaises(NeedsStrongerModel) as cm:
                process(DOC_ID)
        msg = str(cm.exception)
        self.assertIn("this may need Opus", msg)
        self.assertIn("only 4 of 29 voted items", msg)
        self.assertFalse(os.path.exists(os.path.join(paths.PUBLISHED, f"{DOC_ID}.json")))

    def test_good_coverage_publishes_and_reports_it(self):
        with mock.patch.object(run, "run_agent", fake_agents("opus")):
            rep = process(DOC_ID)
        self.assertEqual((rep["coverage"]["covered"], rep["coverage"]["voted"]), (19, 29))

    def test_explicit_opus_run_reports_low_coverage_but_does_not_stop(self):
        with mock.patch.object(run, "run_agent", fake_agents("sonnet-prompt1")):
            rep = process(DOC_ID, model=ESCALATION_MODEL)
        self.assertEqual(rep["coverage"]["covered"], 4)

    def test_site_shows_coverage(self):
        with mock.patch.object(run, "run_agent", fake_agents("opus")):
            process(DOC_ID)
        from pipeline.site import build_site
        out, _ = build_site()
        with open(os.path.join(out, "index.html"), encoding="utf-8") as f:
            self.assertIn("19 of 29 recorded votes", f.read())
        with open(os.path.join(out, "doc", f"{DOC_ID}.html"), encoding="utf-8") as f:
            self.assertIn("cover 19 of the 29 items the Council voted on", f.read())


if __name__ == "__main__":
    unittest.main()
