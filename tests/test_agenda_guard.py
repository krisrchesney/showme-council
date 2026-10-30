"""T-3: an agenda is a plan, never an outcome."""

import json
import os
import unittest

from pipeline import paths
from pipeline.run import process
from pipeline.verify import agenda_states_outcome, code_checks, split_pages
from tests.helpers import STUB, TempDataTest

AGENDA = {"kind": "agenda", "body": "Council", "date": "2026-10-22", "doc_id": "kc-19561-agenda"}
MINUTES = dict(AGENDA, kind="minutes", doc_id="kc-19561-minutes")


def claim(statement, outcome=None):
    return {"id": "c1", "type": "vote", "statement": statement, "outcome": outcome, "matter_file": None,
            "amount_usd": None, "quote": "Authorizing the City Manager to expend an amount not to exceed", "page": 1}


class RejectedOnAnAgendaTests(unittest.TestCase):
    def test_statements_that_read_as_decisions(self):
        for s in ("Ordinance 260919 passed.", "The Council approved the contract.", "Ordinance 260920 authorizes a $1.1M upgrade.",
                  "The resolution was adopted as substituted.", "The bill failed.", "Members voted to advance it.",
                  "The ordinance was enacted."):
            self.assertTrue(agenda_states_outcome(claim(s), AGENDA), s)

    def test_a_recorded_outcome_is_never_allowed_on_an_agenda(self):
        for o in ("passed", "adopted", "failed", "held", "referred", "advanced"):
            self.assertTrue(agenda_states_outcome(claim("Ordinance 260919 is listed on the agenda.", o), AGENDA), o)

    def test_the_reason_is_reported_by_the_code_checks(self):
        pages = {1: "authorizing the city manager to expend an amount not to exceed"}
        ck = code_checks(claim("Ordinance 260919 passed."), pages, AGENDA, [])
        self.assertIn("agenda_states_outcome", ck["reasons"])
        self.assertFalse(ck["passed"])


class AllowedOnAnAgendaTests(unittest.TestCase):
    def test_plan_wording_is_fine(self):
        for s in ("Ordinance 260919 is scheduled for a vote.", "Ordinance 260919 is listed on the agenda.",
                  "The ordinance would authorize spending up to $1,100,000.", "The council is scheduled to vote on the contract.",
                  "The resolution proposes to appropriate $50,000.", "Ordinance 260920 is slated to be adopted.",
                  "A hearing is planned for November 5."):
            self.assertFalse(agenda_states_outcome(claim(s), AGENDA), s)

    def test_the_same_words_are_fine_in_minutes(self):
        for s in ("Ordinance 260919 passed.", "The Council approved the contract."):
            self.assertFalse(agenda_states_outcome(claim(s, "passed"), MINUTES), s)

    def test_an_other_outcome_is_not_a_recorded_result(self):
        self.assertFalse(agenda_states_outcome(claim("A hearing is listed.", "other"), AGENDA))


class PromptsTellTheModelTests(unittest.TestCase):
    def prompt(self, name):
        with open(os.path.join(paths.AGENTS_DIR, name + ".md"), encoding="utf-8") as f:
            return f.read()

    def test_extractor_and_summarizer_say_agendas_are_plans(self):
        self.assertIn('is scheduled for', self.prompt("extractor"))
        self.assertIn('never "passed"', self.prompt("extractor"))
        self.assertIn("scheduled to vote", self.prompt("summarizer"))


class AgendaThroughThePipelineTests(TempDataTest):
    def test_the_fixture_agenda_text_exists_and_has_no_results(self):
        with open(os.path.join(paths.FIXTURES, "kansascity", "19561_A_Council_26-10-22_Docket_-_City_Council.txt"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("=== page 1 ===", text)
        self.assertNotIn("A motion was made that this Ordinance be Passed", text)     # it is a plan: no recorded motions

    def test_the_stub_claims_that_state_outcomes_publish_nothing_from_an_agenda(self):
        from pipeline import run
        run.ingest("kansascity", "2026-10-22", "2026-10-23", fixture=True, kinds=("agenda",))
        rep = process("kc-19561-agenda", stub_dir=STUB)
        with open(os.path.join(paths.WORK, "kc-19561-agenda", "report.json"), encoding="utf-8") as f:
            full = json.load(f)
        self.assertEqual(rep["claims_accepted"], 0)
        outcomes = {c["id"]: c["reject_reasons"] for c in full["rejected"]}
        self.assertIn("agenda_states_outcome", outcomes["c1"])      # "The Council passed Ordinance 260919."
        self.assertIn("agenda_states_outcome", outcomes["c2"])      # "...authorizes the City Manager to spend..."


if __name__ == "__main__":
    unittest.main()
