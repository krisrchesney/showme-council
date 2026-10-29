"""Fixes found by comparing Opus with Sonnet on the same document (docs/MODEL-COMPARISON.md), plus
the re-scored numbers of the three real runs, pinned so a later change to verify.py can't quietly move them.
"""

import glob
import json
import os
import unittest

from pipeline import paths
from pipeline.verify import code_checks, coverage, decide, matter_check, numbers, numbers_check, split_pages

FIX = os.path.join(paths.FIXTURES, "kansascity")
META = {"doc_id": "kc-19561-minutes", "body": "Council", "kind": "minutes", "date": "2026-10-22"}
BOILERPLATE = "A motion was made that this Ordinance be Passed.. The motion carried by the"

with open(glob.glob(os.path.join(FIX, "*Minutes.txt"))[0], encoding="utf-8") as _f:
    PAGES = split_pages(_f.read())
with open(os.path.join(FIX, "eventitems_19561.json"), encoding="utf-8") as _f:
    ITEMS = json.load(_f)


def score(run):
    def load(n):
        with open(os.path.join(FIX, "runs", run, n + ".json"), encoding="utf-8") as f:
            return json.load(f)
    claims = load("facts")["claims"]
    checks = {c["id"]: code_checks(c, PAGES, META, ITEMS) for c in claims}
    res = decide(META, claims, checks, load("summary"), load("verdicts"))
    return res, coverage(META, ITEMS, res["accepted"])


class BoilerplateQuoteTests(unittest.TestCase):
    """'A motion was made that this Ordinance be Passed' sits under every passed item. It proves the
    claim only for an item whose own block contains it."""

    def test_counts_when_it_occurs_in_the_claimed_items_block(self):
        self.assertEqual(matter_check({"matter_file": "260919", "quote": BOILERPLATE}, PAGES, ITEMS), "block")
        self.assertEqual(matter_check({"matter_file": "260895", "quote": BOILERPLATE}, PAGES, ITEMS), "block")

    def test_does_not_back_a_claim_about_an_item_whose_block_lacks_it(self):
        # 260931 was only referred to committee: its block has no "Passed" motion.
        self.assertTrue(matter_check({"matter_file": "260931", "quote": BOILERPLATE}, PAGES, ITEMS).startswith("other:"))

    def test_a_wrong_vote_claim_is_still_rejected_on_both_counts(self):
        c = {"id": "x", "type": "vote", "matter_file": "260931", "outcome": "passed", "amount_usd": None,
             "statement": "Ordinance 260931 passed.", "quote": BOILERPLATE}
        ck = code_checks(c, PAGES, META, ITEMS)
        self.assertIn("quote_from_other_item", ck["reasons"])
        self.assertIn("api_disagrees", ck["reasons"])
        self.assertFalse(ck["passed"])

    def test_a_right_vote_claim_with_the_boilerplate_quote_passes(self):
        c = {"id": "x", "type": "vote", "matter_file": "260919", "outcome": "passed", "amount_usd": None,
             "statement": "Ordinance 260919 passed.", "quote": BOILERPLATE}
        ck = code_checks(c, PAGES, META, ITEMS)
        self.assertEqual((ck["matter"], ck["api"], ck["passed"]), ("block", "agree", True))


class OrdinalTests(unittest.TestCase):
    def test_statement_ordinals_are_street_names_not_figures(self):
        self.assertEqual(numbers("on the 63rd & Prospect site and the 15th item", skip_ordinals=True), set())

    def test_whole_number_is_never_cut_down_to_a_prefix(self):
        # a naive "not followed by rd" lookahead backtracks 63rd to "6"
        self.assertEqual(numbers("the 63rd site"), {"63"})
        self.assertEqual(numbers("the 15th item"), {"15"})

    def test_quote_side_keeps_ordinals_so_november_5th_supports_november_5(self):
        c = {"statement": "held until November 5.", "quote": "Held on Docket until November 5th 10.22.2026", "amount_usd": None}
        self.assertEqual(numbers_check(c, META), [])

    def test_a_wrong_figure_is_still_caught(self):
        c = {"statement": "Spends $2,100,000 near 63rd Street.", "quote": "not to exceed $ 1,100,000.00 near 63rd Street", "amount_usd": None}
        self.assertEqual(numbers_check(c, META), ["2100000"])


class HeadlineTests(unittest.TestCase):
    def test_headline_falls_back_when_a_cited_claim_was_rejected(self):
        claims = [{"id": "c1", "matter_file": "1", "type": "vote", "outcome": None, "amount_usd": None, "statement": "s", "quote": "q" * 30, "page": 1},
                  {"id": "c2", "matter_file": "2", "type": "vote", "outcome": None, "amount_usd": None, "statement": "s", "quote": "q" * 30, "page": 1}]
        checks = {"c1": {"passed": True, "reasons": [], "api": "unchecked"}, "c2": {"passed": False, "reasons": ["quote_not_found"], "api": "unchecked"}}
        summary = {"headline": "Big news", "sentences": [{"text": "a", "claim_ids": ["c1"]}, {"text": "b", "claim_ids": ["c2"]}]}
        verdicts = {"claims": [{"id": "c1", "verdict": "SUPPORTED", "reason": ""}, {"id": "c2", "verdict": "SUPPORTED", "reason": ""}],
                    "sentences": [{"index": 0, "verdict": "FAITHFUL", "reason": ""}, {"index": 1, "verdict": "FAITHFUL", "reason": ""},
                                  {"index": 2, "verdict": "FAITHFUL", "reason": ""}]}
        res = decide(META, claims, checks, summary, verdicts)
        self.assertEqual(res["headline"], "Council minutes, 2026-10-22")
        self.assertFalse(res["report"]["headline_checked"])
        # and with every cited claim accepted, the checked headline is used
        checks["c2"] = {"passed": True, "reasons": [], "api": "unchecked"}
        self.assertEqual(decide(META, claims, checks, summary, verdicts)["headline"], "Big news")


class RealRunPinsTests(unittest.TestCase):
    """Saved agent outputs of three real runs on the same minutes, scored by the current verify.py."""

    def test_opus_5_5(self):
        res, cov = score("opus")
        self.assertEqual((res["report"]["claims_extracted"], res["report"]["claims_accepted"]), (37, 32))
        self.assertEqual((cov["covered"], cov["voted"]), (19, 29))

    def test_sonnet_5_5_first_prompt(self):
        res, cov = score("sonnet-prompt1")
        self.assertEqual((res["report"]["claims_extracted"], res["report"]["claims_accepted"]), (7, 5))
        self.assertEqual((cov["covered"], cov["voted"]), (4, 29))

    def test_sonnet_5_5_coverage_prompt(self):
        res, cov = score("sonnet-prompt2")
        self.assertEqual((res["report"]["claims_extracted"], res["report"]["claims_accepted"]), (60, 55))
        self.assertEqual((cov["covered"], cov["voted"]), (26, 29))

    def test_no_accepted_fact_in_any_run_contradicts_the_citys_vote_record(self):
        for run in ("opus", "sonnet-prompt1", "sonnet-prompt2"):
            res, _ = score(run)
            self.assertEqual([c["id"] for c in res["accepted"] if c["code_checks"]["api"] == "disagree"], [], run)


if __name__ == "__main__":
    unittest.main()
