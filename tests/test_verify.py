"""The code half of the fact-check. These encode what "supported" means mechanically."""

import glob
import json
import os
import unittest

from pipeline import paths
from pipeline.verify import (FUZZY_MIN, MIN_QUOTE_CHARS, api_check, code_checks, decide, find_quote,
                             normalize, numbers_check, split_pages)
from tests.helpers import STUB

FIX = os.path.join(paths.FIXTURES, "kansascity")
META = {"doc_id": "kc-19561-minutes", "body": "Council", "kind": "minutes", "date": "2026-10-22"}


def load(name):
    with open(os.path.join(STUB, name), encoding="utf-8") as f:
        return json.load(f)


def minutes_pages():
    with open(glob.glob(os.path.join(FIX, "*Minutes.txt"))[0], encoding="utf-8") as f:
        return split_pages(f.read())


class QuoteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = minutes_pages()

    def test_thresholds_have_not_been_loosened(self):
        # Changing these needs a ticket that says so (CLAUDE.md "Never").
        self.assertGreaterEqual(FUZZY_MIN, 0.92)
        self.assertGreaterEqual(MIN_QUOTE_CHARS, 20)

    def test_exact_quote_across_line_breaks(self):
        q = "Authenticated Ordinance 260919 A motion was made that this Ordinance be Passed"
        match, _, page = find_quote(q, self.pages)
        self.assertEqual((match, page), ("exact", 13))

    def test_dollar_spacing_and_curly_quotes_normalize(self):
        self.assertEqual(normalize("$ 1,100,000.00  “Do  Pass”"), '$1,100,000.00 "do pass"')

    def test_small_extraction_noise_is_fuzzy_match(self):
        q = "Authenticated Ordinanse 260919 A motion was made that this Ordinance be Passed"
        self.assertEqual(find_quote(q, self.pages)[0], "fuzzy")

    def test_invented_quote_is_not_found(self):
        self.assertEqual(find_quote("The Council approved a 5 percent property tax increase.", self.pages)[0], "none")

    def test_quote_with_changed_number_is_not_exact(self):
        q = "expend an amount not to exceed $ 9,100,000.00 for the purpose of audio and video"
        self.assertNotEqual(find_quote(q, self.pages)[0], "exact")


class NumberTests(unittest.TestCase):
    def test_amount_must_be_in_quote(self):
        c = {"statement": "Spends up to $2,100,000.00.", "quote": "not to exceed $ 1,100,000.00 for", "amount_usd": 2100000.0}
        self.assertEqual(numbers_check(c, META), ["2100000"])

    def test_matching_amount_passes(self):
        c = {"statement": "Spends up to $1,100,000.00.", "quote": "not to exceed $ 1,100,000.00 for", "amount_usd": 1100000}
        self.assertEqual(numbers_check(c, META), [])

    def test_meeting_date_parts_are_allowed(self):
        c = {"statement": "On October 22, 2026 the Council passed 260919.", "quote": "Authenticated Ordinance 260919"}
        self.assertEqual(numbers_check(c, META), [])


class ApiTests(unittest.TestCase):
    ITEMS = [{"EventItemMatterFile": "260919", "EventItemActionName": "Passed", "EventItemPassedFlagName": "Pass"},
             {"EventItemMatterFile": "260931", "EventItemActionName": "referred", "EventItemPassedFlagName": None}]

    def test_agree_disagree_unchecked(self):
        self.assertEqual(api_check({"matter_file": "260919", "outcome": "passed"}, self.ITEMS), "agree")
        self.assertEqual(api_check({"matter_file": "260931", "outcome": "passed"}, self.ITEMS), "disagree")
        self.assertEqual(api_check({"matter_file": "260931", "outcome": "referred"}, self.ITEMS), "agree")
        self.assertEqual(api_check({"matter_file": "999999", "outcome": "passed"}, self.ITEMS), "unchecked")
        self.assertEqual(api_check({"matter_file": None, "outcome": None}, self.ITEMS), "unchecked")


class DecideTests(unittest.TestCase):
    """The stub outputs plant one error of each kind; each must be caught for the right reason."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(FIX, "eventitems_19561.json"), encoding="utf-8") as f:
            items = json.load(f)
        pages = minutes_pages()
        cls.claims = load("extractor.json")["claims"]
        cls.checks = {c["id"]: code_checks(c, pages, META, items) for c in cls.claims}
        cls.result = decide(META, cls.claims, cls.checks, load("summarizer.json"), load("fact-checker.json"))

    def test_only_fully_supported_claims_are_accepted(self):
        self.assertEqual([c["id"] for c in self.result["accepted"]], ["c1", "c2", "c3"])

    def test_each_planted_error_is_rejected_for_its_reason(self):
        why = {c["id"]: c["reject_reasons"] for c in self.result["rejected"]}
        self.assertIn("number_not_in_quote", why["c4"])    # $2.1M claimed, quote says $1.1M
        self.assertIn("quote_not_found", why["c5"])        # invented quote
        self.assertIn("api_disagrees", why["c6"])          # API says referred, claim says passed
        self.assertEqual(why["c7"], ["checker_partial"])   # code can't see "unanimously"; the checker can

    def test_sentence_citing_a_rejected_claim_is_dropped_even_if_faithful(self):
        published = [s["claim_ids"] for s in self.result["published_sentences"]]
        self.assertEqual(published, [["c1"], ["c2"], ["c3"]])

    def test_unfaithful_headline_falls_back_to_plain_title(self):
        self.assertEqual(self.result["headline"], "Council minutes, 2026-10-22")

    def test_metric(self):
        r = self.result["report"]
        self.assertEqual((r["claims_extracted"], r["claims_accepted"], r["claim_pass_rate"]), (7, 3, 0.429))
        self.assertEqual(r["sentence_pass_rate"], 0.75)

    def test_missing_verdict_is_a_rejection(self):
        res = decide(META, self.claims[:1], self.checks, {"headline": "", "sentences": []}, {"claims": [], "sentences": []})
        self.assertEqual(res["rejected"][0]["reject_reasons"], ["checker_missing"])

    def test_zero_claims(self):
        res = decide(META, [], {}, {"headline": "", "sentences": []}, {"claims": [], "sentences": []})
        self.assertIsNone(res["report"]["claim_pass_rate"])


if __name__ == "__main__":
    unittest.main()
