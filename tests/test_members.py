"""T-23: model-written text may name a council member only in a recorded-vote statement the city's roll call confirms."""

import unittest

from pipeline import explore, labels, members
from pipeline.verify import code_checks, decide, split_pages

ROLL = [{"name": "Quinton Lucas", "vote": "Aye"}, {"name": "Kevin O'Neill", "vote": "Aye"}, {"name": "Wes Rogers", "vote": "Out"},
        {"name": "Melissa Robinson", "vote": "Abstain"}, {"name": "Ryana Parks-Shaw", "vote": "Nay"},
        {"name": "Melissa Patterson Hazley", "vote": "Aye"}, {"name": "Kevin  McManus", "vote": "Aye"}]
ITEMS = [
    {"EventItemMatterFile": "260898", "votes": ROLL},
    {"EventItemMatterFile": "260899", "votes": ROLL},
    {"EventItemMatterFile": "260905", "votes": [dict(v, vote="Aye") for v in ROLL]},
    {"EventItemMatterFile": "260906", "votes": None},
]


def ok(text, items=ITEMS, extra=()):
    return members.check_text(text, items, extra)[0]


class VoteStatements(unittest.TestCase):
    def test_a_vote_the_roll_call_confirms_passes(self):
        t = "Ordinances 260898 and 260899, on ending the TIF plans, both passed. Parks-Shaw voted Nay on both."
        self.assertTrue(ok(t))
        self.assertTrue(ok("Councilmember Parks-Shaw voted Nay on Ordinance 260898."))
        self.assertTrue(ok("Ryana Parks-Shaw voted against Ordinance 260899."))

    def test_several_members_and_the_citys_other_words(self):
        self.assertTrue(ok("Robinson abstained on Ordinance 260898 and 260899."))
        self.assertTrue(ok("Rogers was absent on Ordinance 260898."))
        self.assertTrue(ok("Lucas and O'Neill voted Aye on Ordinance 260905."))
        self.assertTrue(ok("Patterson Hazley and McManus voted Aye on Ordinance 260905."))

    def test_the_way_facts_are_phrased_with_the_votes_trailing_the_item(self):
        self.assertTrue(ok("Ordinance 260898 passed, with Parks-Shaw voting Nay, Robinson abstaining and Rogers out."))
        self.assertTrue(ok("Ordinance 260899 on ending the TIF plan passed, with Parks-Shaw voting Nay."))
        self.assertFalse(ok("Ordinance 260898 passed, with Parks-Shaw voting Aye."))
        self.assertFalse(ok("Ordinance 260898 passed, with Lucas out."))
        self.assertFalse(ok("Ordinance 260898 passed, which Parks-Shaw opposed, with Robinson abstaining."))
        self.assertFalse(ok("Ordinance 260898 passed, with Parks-Shaw voting Nay as usual."))

    def test_a_name_with_the_wrong_vote_is_rejected(self):
        self.assertFalse(ok("Parks-Shaw voted Aye on Ordinance 260898."))
        self.assertFalse(ok("Robinson voted Nay on Ordinance 260899."))
        self.assertFalse(ok("Lucas voted Nay on Ordinance 260905."))
        self.assertFalse(ok("Parks-Shaw voted Nay on both. Ordinances 260905 and 260898 passed."))

    def test_a_vote_with_no_roll_call_or_no_item_is_rejected(self):
        self.assertFalse(ok("Parks-Shaw voted Nay on Ordinance 260906."))     # an item whose roll call is empty
        self.assertFalse(ok("Parks-Shaw voted Nay on Ordinance 260111."))     # an item not in the meeting
        self.assertFalse(ok("Parks-Shaw voted Nay."))                         # no item named
        self.assertFalse(ok("Parks-Shaw voted Nay on Ordinance 260898.", items=None))
        self.assertFalse(ok("Parks-Shaw voted Nay on Ordinance 260898.", items=[]))

    def test_the_rest_about_a_person_is_rejected(self):
        for t in ("Parks-Shaw opposed the plan because it favors developers.",
                  "Councilmember Lucas championed Ordinance 260905.",
                  "Parks-Shaw voted Nay on Ordinance 260898, as she often does.",
                  "Parks-Shaw voted Nay on Ordinance 260898 because of the cost.",
                  "Lucas sponsored Ordinance 260905.",
                  "Parks-Shaw was the only one to vote Nay on Ordinance 260898, unlike Lucas.",
                  "Mayor Lucas said the plan was a gift to the city.",
                  "Parks-Shaw voted Nay on 260898 and then spoke against it."):
            self.assertFalse(ok(t, extra=("260898",)), t)

    def test_text_that_names_nobody_passes_and_a_street_or_word_is_not_a_member(self):
        self.assertTrue(ok("Council passed Ordinance 260905, a $1,000,000 agreement."))
        self.assertTrue(ok("Parks and Recreation will rebuild the playground at Barry Road Park.", items=ITEMS))
        self.assertTrue(ok("Appointing Marilyn Sanders as City Clerk."))
        self.assertEqual(members.mentions("Rea and French voted", ["Crispin Rea", "Lindsay French"]), {"Crispin Rea", "Lindsay French"})

    def test_the_roster_includes_names_seen_in_the_roll_call(self):
        items = [{"EventItemMatterFile": "260905", "votes": [{"name": "Newly Elected", "vote": "Aye"}]}]
        self.assertTrue(ok("Elected voted Aye on Ordinance 260905.", items=items))
        self.assertFalse(ok("Elected championed Ordinance 260905.", items=items))


CLAIM = {"id": "c1", "type": "vote", "statement": "Parks-Shaw voted Nay on Ordinance 260898.", "quote": "x" * 30, "page": 1,
         "matter_file": "260898", "outcome": None, "amount_usd": None, "date": None}
META = {"doc_id": "kc-1-minutes", "body": "Council", "kind": "minutes", "date": "2026-10-29"}
PAGES = split_pages("=== page 1 ===\n" + "x" * 30)


class InThePipeline(unittest.TestCase):
    def test_a_fact_naming_a_member_needs_the_roll_call(self):
        self.assertNotIn("member_named", code_checks(CLAIM, PAGES, META, ITEMS)["reasons"])
        bad = dict(CLAIM, statement="Parks-Shaw voted Aye on Ordinance 260898.")
        self.assertIn("member_named", code_checks(bad, PAGES, META, ITEMS)["reasons"])
        why = dict(CLAIM, statement="Parks-Shaw opposed Ordinance 260898 because of the cost.")
        self.assertIn("member_named", code_checks(why, PAGES, META, ITEMS)["reasons"])

    def decide(self, text, headline="Council minutes, 2026-10-29", items=ITEMS):
        claims = [dict(CLAIM, statement="Ordinance 260898 passed.")]
        checks = {"c1": {"reasons": [], "passed": True}}
        summary = {"headline": headline, "sentences": [{"text": text, "claim_ids": ["c1"]}]}
        verdicts = {"claims": [{"id": "c1", "verdict": "SUPPORTED"}],
                    "sentences": [{"index": 0, "verdict": "FAITHFUL"}, {"index": 1, "verdict": "FAITHFUL"}]}
        return decide(META, claims, checks, summary, verdicts, items)

    def test_a_published_sentence_with_a_verified_vote_is_marked_and_the_rest_are_dropped(self):
        good = self.decide("Ordinance 260898 passed. Parks-Shaw voted Nay on it.")
        self.assertEqual(len(good["published_sentences"]), 1)
        self.assertTrue(good["published_sentences"][0]["members_verified"])
        bad = self.decide("Ordinance 260898 passed, which Parks-Shaw opposed because of the cost.")
        self.assertEqual(bad["published_sentences"], [])
        self.assertIn("member_named", bad["dropped_sentences"][0]["dropped_because"])
        wrong = self.decide("Ordinance 260898 passed. Lucas voted Nay on it.")
        self.assertEqual(wrong["published_sentences"], [])
        self.assertNotIn("members_verified", self.decide("Ordinance 260898 passed.")["published_sentences"][0])

    def test_a_headline_that_names_a_member_falls_back_to_the_plain_one(self):
        r = self.decide("Ordinance 260898 passed.", headline="Parks-Shaw loses again")
        self.assertEqual(r["headline"], "Council minutes, 2026-10-29")

    def test_with_no_roll_calls_at_all_a_named_sentence_is_dropped(self):
        r = self.decide("Ordinance 260898 passed. Parks-Shaw voted Nay on it.", items=None)
        self.assertEqual(r["published_sentences"], [])


class Labels(unittest.TestCase):
    def test_an_item_description_never_names_a_member(self):
        meeting = {"event_id": 1, "body": "Council", "date": "2026-10-29"}
        title = "Sponsor: Mayor Quinton Lucas Approving a plan for the Plaza"
        ms = [{"matter_file": "260445", "title": title}]

        def runner(name, schema, payload, out_dir, loop_cap, model=None):
            usage = {"tokens_in": 1, "tokens_out": 1, "num_turns": 1, "duration_s": 1.0, "api_equiv_usd": 0.0, "models": []}
            if name == "labeler":
                return {"labels": [{"matter_file": "260445", "label": "Mayor Lucas wants a plan for the Plaza"}]}, usage
            return {"claims": [{"id": c["id"], "verdict": "SUPPORTED", "reason": "r"} for c in payload["claims"]], "sentences": []}, usage
        out, _ = labels.make_labels(meeting, ms, "unused", runner=runner)
        self.assertFalse(out["260445"]["shown"])
        self.assertIn("member_named", out["260445"]["why_not"])


class ExplorerBackstop(unittest.TestCase):
    def doc(self):
        c1 = {"id": "c1", "statement": "Ordinance 260898 passed.", "code_checks": {"api": "agree"}}
        c2 = {"id": "c2", "statement": "Parks-Shaw voted Nay on Ordinance 260898.", "code_checks": {"api": "agree", "member_check": None}}
        c3 = {"id": "c3", "statement": "Parks-Shaw voted Nay on Ordinance 260899.", "code_checks": {"api": "agree"}}     # an older record
        s = [{"text": "Ordinance 260898 passed.", "claim_ids": ["c1"]},
             {"text": "Parks-Shaw voted Nay on Ordinance 260898.", "claim_ids": ["c2"], "members_verified": True},
             {"text": "Parks-Shaw voted Nay on Ordinance 260899.", "claim_ids": ["c3"]}]
        return {"claims": [c1, c2, c3], "sentences": s}

    def test_an_unmarked_sentence_or_fact_that_names_a_member_is_left_out(self):
        d = explore.member_safe(self.doc())
        self.assertEqual([c["id"] for c in d["claims"]], ["c1", "c2"])
        self.assertEqual([x["claim_ids"] for x in d["sentences"]], [["c1"], ["c2"]])


if __name__ == "__main__":
    unittest.main()
