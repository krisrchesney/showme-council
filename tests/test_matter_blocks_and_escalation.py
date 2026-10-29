"""Matter-block check (found by the first real run) and the stop-and-ask-for-Opus rule."""

import glob
import json
import os
import shutil
import tempfile
import unittest
from datetime import date
from unittest import mock

from pipeline import paths, run
from pipeline.agents import AgentOutputError
from pipeline.run import ESCALATION_MODEL, NeedsStrongerModel, load_state, nightly, process
from pipeline.verify import code_checks, matter_blocks, matter_check, normalize, split_pages
from tests.helpers import DOC_ID, STUB, TempDataTest

FIX = os.path.join(paths.FIXTURES, "kansascity")
META = {"doc_id": DOC_ID, "body": "Council", "kind": "minutes", "date": "2026-10-22"}


def fixture():
    with open(glob.glob(os.path.join(FIX, "*Minutes.txt"))[0], encoding="utf-8") as f:
        pages = split_pages(f.read())
    with open(os.path.join(FIX, "eventitems_19561.json"), encoding="utf-8") as f:
        items = json.load(f)
    return pages, items


class MatterBlockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages, cls.items = fixture()

    def test_most_items_are_located_in_the_minutes(self):
        wanted = {i["EventItemMatterFile"] for i in self.items if i["EventItemMatterFile"]}
        found = {m for _, m in matter_blocks(self.pages, self.items)}
        self.assertGreaterEqual(len(found) / len(wanted), 0.8)

    def test_lookalike_items_get_their_own_blocks(self):
        # 260905 / 260908 / 260942 all open "Authorizing the Manager of Procurement Services..."
        starts = {m: s for s, m in matter_blocks(self.pages, self.items)}
        self.assertEqual(len({starts[m] for m in ("260905", "260908", "260942")}), 3)

    def test_quote_inside_its_items_block(self):
        c = {"matter_file": "260919", "quote": "Authenticated Ordinance 260919 A motion was made that this Ordinance be Passed"}
        self.assertEqual(matter_check(c, self.pages, self.items), "block")

    def test_quote_from_a_different_item_is_caught(self):
        # The real wording of 260920's block, attributed to 260919.
        c = {"matter_file": "260919", "quote": "Authorizing the City Manager to expend an amount not to exceed $ 1,100,000.00 for the purpose of audio and video"}
        self.assertEqual(matter_check(c, self.pages, self.items), "other:260920")

    def test_matter_number_is_proven_by_position_not_by_the_quote(self):
        c = {"id": "x", "type": "spending", "matter_file": "260920", "outcome": None, "amount_usd": 1100000.0,
             "statement": "Ordinance 260920 authorizes up to $1,100,000.00 for audio and video upgrades.",
             "quote": "Authorizing the City Manager to expend an amount not to exceed $ 1,100,000.00 for the purpose of audio and video"}
        ck = code_checks(c, self.pages, META, self.items)
        self.assertEqual((ck["matter"], ck["numbers_missing_from_quote"], ck["passed"]), ("block", [], True))

    def test_other_numbers_must_still_be_in_the_quote(self):
        c = {"id": "x", "type": "spending", "matter_file": "260920", "outcome": None, "amount_usd": 2100000.0,
             "statement": "Ordinance 260920 authorizes up to $2,100,000.00.",
             "quote": "Authorizing the City Manager to expend an amount not to exceed $ 1,100,000.00 for the purpose of audio and video"}
        ck = code_checks(c, self.pages, META, self.items)
        self.assertIn("number_not_in_quote", ck["reasons"])

    def test_paren_spacing_normalizes(self):
        self.assertEqual(normalize("one ( 1) year"), normalize("one (1) year"))


class EscalationTests(TempDataTest):
    def setUp(self):
        super().setUp()
        self.stub = tempfile.mkdtemp(prefix="showme-stub-")
        for f in ("extractor.json", "summarizer.json"):
            shutil.copy(os.path.join(STUB, f), self.stub)
        # A fact-checker that skips every claim: the "can't handle this document" signal.
        with open(os.path.join(self.stub, "fact-checker.json"), "w", encoding="utf-8") as f:
            json.dump({"claims": [], "sentences": []}, f)

    def tearDown(self):
        shutil.rmtree(self.stub, ignore_errors=True)
        super().tearDown()

    def ingest(self):
        run.ingest("kansascity", "2026-10-22", "2026-10-23", fixture=True)

    def test_default_model_is_sonnet(self):
        self.assertEqual(run.DEFAULT_MODEL, "claude-sonnet-5-5")
        for name in ("extractor", "summarizer", "fact-checker"):
            from pipeline.agents import load_agent
            self.assertEqual(load_agent(name)["model"], "claude-sonnet-5-5")

    def test_checker_skipping_claims_stops_and_names_opus(self):
        self.ingest()
        with self.assertRaises(NeedsStrongerModel) as cm:
            process(DOC_ID, stub_dir=self.stub)
        self.assertIn("this may need Opus", str(cm.exception))
        self.assertIn(f"--model {ESCALATION_MODEL}", str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(paths.PUBLISHED, f"{DOC_ID}.json")))

    def test_explicit_opus_run_does_not_loop_the_escalation(self):
        self.ingest()
        rep = process(DOC_ID, stub_dir=self.stub, model=ESCALATION_MODEL)   # user chose Opus: publish what passes
        self.assertEqual(rep["claims_accepted"], 0)

    def test_bad_agent_output_on_sonnet_asks_for_opus_but_on_opus_just_fails(self):
        self.ingest()
        boom = AgentOutputError("no structured output")
        with mock.patch.object(run, "run_agent", side_effect=boom):
            with self.assertRaises(NeedsStrongerModel):
                process(DOC_ID)
            with self.assertRaises(AgentOutputError):
                process(DOC_ID, model=ESCALATION_MODEL)

    def test_nightly_parks_the_document_instead_of_retrying_it(self):
        nightly("kansascity", days=10, max_docs=4, loop_cap=4.0, fixture=True, stub_dir=self.stub, today=date(2026, 10, 29))
        self.assertEqual(load_state()["docs"][DOC_ID]["status"], "needs_model")
        nightly("kansascity", days=10, max_docs=4, loop_cap=4.0, fixture=True, stub_dir=self.stub, today=date(2026, 10, 29))
        self.assertEqual(load_state()["docs"][DOC_ID]["tries"], 1)   # not retried on the same model

    def test_redecide_reuses_saved_agent_output_without_calling_claude(self):
        self.ingest()
        process(DOC_ID, stub_dir=STUB)
        with mock.patch.object(run, "run_agent", side_effect=AssertionError("called claude")):
            rep = run.redecide(DOC_ID)
        self.assertEqual(rep["claims_accepted"], 3)
        with open(paths.METRICS, encoding="utf-8") as f:
            self.assertEqual(len([x for x in f if x.strip()]), 1)   # replaced, not appended


if __name__ == "__main__":
    unittest.main()
