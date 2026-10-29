"""T-11: a claimed outcome is compared with the city's own wording for it, not with a single English word."""

import unittest

from pipeline.verify import api_check


def item(action, flag=None, matter="1"):
    return [{"EventItemMatterFile": matter, "EventItemActionName": action, "EventItemPassedFlagName": flag}]


def check(outcome, action, flag=None):
    return api_check({"matter_file": "1", "outcome": outcome}, item(action, flag))


class AgreeTests(unittest.TestCase):
    def test_held_matches_every_way_the_city_says_it(self):
        for action in ("Held on Docket", "Hold on Agenda", "Held in Committee", "held"):
            self.assertEqual(check("held", action), "agree", action)

    def test_referred_matches_referred_and_re_referred(self):
        for action in ("referred", "Re-referred", "Referred to committee"):
            self.assertEqual(check("referred", action), "agree", action)

    def test_advanced_matches_a_committee_advancing_it(self):
        for action in ("Adv and Do Pass", "Adv and Do Pass as Cmte Sub", "Move to Advance"):
            self.assertEqual(check("advanced", action), "agree", action)

    def test_passed_and_adopted_still_match_including_as_substituted(self):
        self.assertEqual(check("passed", "Passed", "Pass"), "agree")
        self.assertEqual(check("passed", "Passed as Substituted as Amended", "Pass"), "agree")
        self.assertEqual(check("adopted", "Adopted as Substituted", "Pass"), "agree")
        self.assertEqual(check("failed", "Failed", "Fail"), "agree")


class DisagreeTests(unittest.TestCase):
    """Wrong claims must still be caught, in every direction."""

    def test_each_wrong_pairing_is_a_disagreement(self):
        wrong = [("held", "Passed", "Pass"), ("held", "referred", None), ("referred", "Hold on Agenda", None),
                 ("referred", "Adopted", "Pass"), ("failed", "Passed", "Pass"), ("passed", "Held on Docket", None),
                 ("advanced", "Passed", "Pass"), ("advanced", "referred", None), ("adopted", "Hold on Agenda", None)]
        for outcome, action, flag in wrong:
            self.assertEqual(check(outcome, action, flag), "disagree", (outcome, action))

    def test_a_committee_advancing_an_item_is_not_the_council_passing_it(self):
        # Before T-11 the substring "pass" in "Adv and Do Pass" made a "passed" claim agree.
        self.assertEqual(check("passed", "Adv and Do Pass"), "disagree")
        self.assertEqual(check("adopted", "Adv and Do Pass as Cmte Sub"), "disagree")

    def test_pass_flag_alone_agrees_with_passed_but_not_with_held(self):
        self.assertEqual(check("passed", "Roll Call", "Pass"), "agree")
        self.assertEqual(check("held", "Roll Call", "Pass"), "disagree")


class UncheckableTests(unittest.TestCase):
    def test_other_missing_or_unrecorded_stays_unchecked(self):
        self.assertEqual(check("other", "Passed", "Pass"), "unchecked")
        self.assertEqual(api_check({"matter_file": "1", "outcome": None}, item("Passed")), "unchecked")
        self.assertEqual(api_check({"matter_file": None, "outcome": "passed"}, item("Passed")), "unchecked")
        self.assertEqual(api_check({"matter_file": "2", "outcome": "passed"}, item("Passed")), "unchecked")
        self.assertEqual(api_check({"matter_file": "1", "outcome": "passed"}, [{"EventItemMatterFile": "1"}]), "unchecked")

    def test_the_schema_allows_the_advanced_outcome(self):
        import json
        import os
        from pipeline import paths
        with open(os.path.join(paths.SCHEMAS_DIR, "extractor.json"), encoding="utf-8") as f:
            enum = json.load(f)["properties"]["claims"]["items"]["properties"]["outcome"]["enum"]
        self.assertIn("advanced", enum)


if __name__ == "__main__":
    unittest.main()
