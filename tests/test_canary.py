"""Planted errors: how they are built, that the checker can't tell them apart, and that they never get published."""

import glob
import json
import os
import re
import unittest
from unittest import mock

from pipeline import canary, paths, run
from pipeline.run import process
from pipeline.sources.base import read_raw
from pipeline.verify import code_checks, split_pages
from tests.helpers import DOC_ID, TempDataTest

FIX = os.path.join(paths.FIXTURES, "kansascity")
META = {"doc_id": DOC_ID, "body": "Council", "kind": "minutes", "date": "2026-10-22"}
USAGE = {"tokens_in": 0, "tokens_out": 0, "num_turns": 0, "duration_s": 0.0, "api_equiv_usd": 0.0, "models": []}


def saved(name, run_name="opus"):
    with open(os.path.join(FIX, "runs", run_name, name + ".json"), encoding="utf-8") as f:
        return json.load(f)


class BuildingCanaryTests(TempDataTest):
    def setUp(self):
        super().setUp()
        run.ingest("kansascity", "2026-10-22", "2026-10-23", fixture=True)
        _, text, self.items = read_raw(DOC_ID)
        self.pages = split_pages(text)
        self.claims = saved("facts")["claims"]
        self.checks = {c["id"]: code_checks(c, self.pages, META, self.items) for c in self.claims}
        self.trusted = [c for c in self.claims if self.checks[c["id"]]["passed"]]
        self.fakes, self.info = canary.make_canaries(META, self.trusted, self.items, canary.next_number(self.claims))

    def test_builds_four_fakes_of_different_kinds_deterministically(self):
        self.assertEqual(len(self.fakes), 4)
        self.assertEqual(set(i["type"] for i in self.info.values()), set(canary.TYPES))
        again, _ = canary.make_canaries(META, self.trusted, self.items, canary.next_number(self.claims))
        self.assertEqual(self.fakes, again)

    def test_ids_continue_the_real_sequence_without_colliding(self):
        real = {c["id"] for c in self.claims}
        self.assertTrue(all(f["id"] not in real and re.fullmatch(r"c\d+", f["id"]) for f in self.fakes))
        self.assertEqual(self.fakes[0]["id"], "c38")

    def test_every_fake_is_false_and_nothing_marks_it_as_fake(self):
        src = {c["id"]: c for c in self.claims}
        for f in self.fakes:
            origin = src[self.info[f["id"]]["source_id"]]
            self.assertNotEqual(f["statement"], origin["statement"])
            self.assertEqual(f["quote"], origin["quote"])          # quote and matter number stay true
            self.assertEqual(f["matter_file"], origin["matter_file"])
            self.assertEqual(set(f), set(origin))                  # no extra "canary" field
            self.assertNotIn("canary", json.dumps(f).lower())

    def test_flip_outcome_contradicts_the_city_record_so_code_catches_it_too(self):
        f = next(f for f in self.fakes if self.info[f["id"]]["type"] == "flip_outcome")
        self.assertRegex(f["statement"], r"failed|rejected|approved")
        ck = code_checks(f, self.pages, META, self.items)
        self.assertIn("api_disagrees", ck["reasons"])

    def test_the_other_kinds_pass_every_code_check_so_only_the_checker_can_catch_them(self):
        for f in self.fakes:
            if self.info[f["id"]]["type"] not in ("flip_outcome", "swap_name"):
                ck = code_checks(f, self.pages, META, self.items)
                self.assertTrue(ck["passed"], (f["statement"], ck["reasons"]))

    def test_a_swapped_name_is_now_also_caught_by_code_because_the_roll_call_contradicts_it(self):
        f = next(f for f in self.fakes if self.info[f["id"]]["type"] == "swap_name")
        ck = code_checks(f, self.pages, META, self.items)
        self.assertIn("member_named", ck["reasons"])

    def test_overstate_only_for_a_vote_the_roll_call_shows_had_a_nay(self):
        f = next(f for f in self.fakes if self.info[f["id"]]["type"] == "overstate")
        self.assertIn("unanimously", f["statement"])
        self.assertTrue(any(v["vote"] == "Nay" for v in canary.roll_call(self.items, f["matter_file"])))

    def test_swap_name_puts_in_someone_who_voted_aye(self):
        f = next(f for f in self.fakes if self.info[f["id"]]["type"] == "swap_name")
        votes = canary.roll_call(self.items, f["matter_file"])
        ayes = {canary._surname(v["name"]) for v in votes if v["vote"] == "Aye"}
        nays = {canary._surname(v["name"]) for v in votes if v["vote"] == "Nay"}
        original = self.info[f["id"]]["original"]
        words = lambda s: set(re.findall(r"[A-Za-z']+", s))
        added, removed = words(f["statement"]) - words(original), words(original) - words(f["statement"])
        self.assertEqual((len(added), len(removed)), (1, 1))
        self.assertTrue(added <= ayes, (added, f["statement"]))       # the stand-in voted aye
        self.assertTrue(removed <= nays, (removed, original))         # the one removed voted no

    def test_no_overstate_when_nobody_voted_nay(self):
        items = [{"EventItemMatterFile": "1", "votes": [{"name": "A B", "vote": "Aye"}, {"name": "C D", "vote": "Aye"}]}]
        claim = {"id": "c1", "type": "vote", "matter_file": "1", "outcome": "passed", "statement": "Ordinance 1 passed.", "quote": "q"}
        fakes, info = canary.make_canaries(META, [claim], items, 2)
        self.assertNotIn("overstate", [i["type"] for i in info.values()])

    def test_score_counts_a_non_supported_verdict_as_caught(self):
        verdicts = {self.fakes[0]["id"]: {"verdict": "PARTIAL", "reason": "r"}, self.fakes[1]["id"]: {"verdict": "SUPPORTED", "reason": "r"}}
        rows = canary.score({k: self.info[k] for k in list(self.info)[:3]}, self.fakes, verdicts, {})
        self.assertEqual([r["checker_caught"] for r in rows], [True, False, False])
        self.assertEqual(rows[2]["checker_verdict"], "NO_VERDICT")
        self.assertEqual(canary.summary(rows)["checker_caught"], 1)


def fake_agents(mode, seen):
    """run_agent stand-in using the saved Opus outputs. The fact-checker answers real claims as Opus did and
    answers anything it doesn't recognise (the fakes) SUPPORTED if lenient, UNSUPPORTED if strict."""
    verd = saved("verdicts")
    by_id = {v["id"]: v for v in verd["claims"]}
    files = {"extractor": saved("facts"), "summarizer": saved("summary")}

    def fake(name, schema, payload, out_dir, loop_cap, stub_dir=None, timeout=900, model=None):
        if name != "fact-checker":
            return files[name], dict(USAGE)
        seen.append(payload)
        claims = [by_id.get(c["id"]) or {"id": c["id"], "verdict": "SUPPORTED" if mode == "lenient" else "UNSUPPORTED", "reason": "x"}
                  for c in payload["claims"]]
        return {"claims": claims, "sentences": verd["sentences"]}, dict(USAGE)
    return fake


class CanariesInTheRunTests(TempDataTest):
    def setUp(self):
        super().setUp()
        run.ingest("kansascity", "2026-10-22", "2026-10-23", fixture=True)

    def run_with(self, mode, **kw):
        seen = []
        with mock.patch.object(run, "run_agent", fake_agents(mode, seen)):
            rep = process(DOC_ID, **kw)
        return rep, seen

    def published(self):
        with open(os.path.join(paths.PUBLISHED, f"{DOC_ID}.json"), encoding="utf-8") as f:
            return f.read()

    def test_the_fakes_never_reach_the_published_page_or_the_saved_verdicts(self):
        rep, seen = self.run_with("lenient")      # even a checker that waves every fake through
        fake_ids = [c["id"] for c in seen[0]["claims"] if int(c["id"][1:]) > 37]
        self.assertEqual(len(fake_ids), 4)
        pub = self.published()
        for cid in fake_ids:
            self.assertNotIn(f'"{cid}"', pub)
        self.assertNotIn("unanimously", pub)
        with open(os.path.join(paths.WORK, DOC_ID, "verdicts.json"), encoding="utf-8") as f:
            self.assertEqual({v["id"] for v in json.load(f)["claims"]} & set(fake_ids), set())

    def test_the_real_results_are_identical_with_and_without_canaries(self):
        with_c, _ = self.run_with("lenient")
        without, seen = self.run_with("lenient", canaries=False)
        self.assertEqual(len(seen[0]["claims"]), 37)
        for k in ("claims_extracted", "claims_accepted", "claim_pass_rate", "reject_reasons", "sentences_published"):
            self.assertEqual(with_c[k], without[k], k)

    def test_the_checker_is_not_told_which_claims_are_fake(self):
        _, seen = self.run_with("lenient")
        self.assertNotIn("canary", json.dumps(seen[0]).lower())
        self.assertEqual(len(seen[0]["claims"]), 41)

    def test_a_lenient_checker_scores_zero_and_a_strict_one_scores_all(self):
        lenient, _ = self.run_with("lenient")
        self.assertEqual((lenient["canary"]["checker_caught"], lenient["canary"]["total"]), (0, 4))
        with open(os.path.join(paths.WORK, DOC_ID, "canary.json"), encoding="utf-8") as f:
            self.assertEqual([r["checker_caught"] for r in json.load(f)["rows"]], [False] * 4)
        self.assertNotIn("missed_by_checker", lenient["canary"])
        strict, _ = self.run_with("strict")
        self.assertEqual((strict["canary"]["checker_caught"], strict["canary"]["total"]), (4, 4))
        self.assertEqual(strict["canary"]["code_caught"], 2)      # the flipped outcome and the swapped name both contradict the city record

    def test_stub_runs_have_no_canaries(self):
        from tests.helpers import STUB
        rep = process(DOC_ID, stub_dir=STUB)
        self.assertIsNone(rep.get("canary"))

    def test_the_site_shows_the_catch_rate_and_the_report_says_it_in_words(self):
        rep, _ = self.run_with("strict")
        from pipeline.site import build_site
        out, _ = build_site()
        with open(os.path.join(out, "index.html"), encoding="utf-8") as f:
            self.assertIn("caught 4 of 4 deliberately false facts", f.read())
        self.assertIn("planted errors the fact-checker caught: 4 of 4", run.report_markdown(DOC_ID))


if __name__ == "__main__":
    unittest.main()
