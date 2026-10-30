"""T-19: keyword topics, counts over time, and the sampled check of the rules (offline: synthetic rows, stand-in model)."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from pipeline import paths, topics, trends
from pipeline.site import trends_page

sys.path.insert(0, os.path.join(paths.ROOT, "scripts"))
import topic_sample  # noqa: E402


def row(event, matter, action, agenda=None, minutes=None, mtype="Ordinance", title="Authorizing a contract with a vendor"):
    return {"event_id": event, "item_id": None, "agenda_seq": agenda, "minutes_seq": minutes, "matter_file": matter,
            "matter_id": 1, "matter_type": mtype, "action": action, "passed": None, "title": title, "mover": None}


def ev(i, date, body="Council"):
    return {"event_id": i, "date": date, "body": body}


EVENTS = [ev(1, "2026-01-08"), ev(4, "2026-01-20", "Finance, Governance and Public Safety Committee"), ev(2, "2026-02-12"), ev(3, "2026-04-09")]
ROWS = [
    # A: introduced, advanced by the committee, passed at the Council five weeks after it first appeared
    row(1, "A", "referred", 1, 1), row(4, "A", "Adv and Do Pass", 1, 1), row(2, "A", "Passed", 1, 1),
    # B: held twice, then passed
    row(1, "B", "Held on Docket", 2, 2, title="Approving the Brooke Hills Fourth Plat"),
    row(2, "B", "Held on Docket", 2, 2, title="Approving the Brooke Hills Fourth Plat"),
    row(3, "B", "Passed", 2, 2, title="Approving the Brooke Hills Fourth Plat"),
    # C: a new ordinance planned for consideration, advanced and passed the same day
    row(3, "C", "Move to Consider", 3, 3, title="Appropriating $50,000 from the Unappropriated Fund Balance"),
    row(3, "C", "Move to Advance", None, 4, title="Appropriating $50,000 from the Unappropriated Fund Balance"),
    row(3, "C", "Passed", None, 5, title="Appropriating $50,000 from the Unappropriated Fund Balance"),
]


class TopicRuleTests(unittest.TestCase):
    CASES = {
        "RESOLUTION - Recognizing October 2026 as Breast Cancer Awareness Month": "ceremonial",
        "Authorizing the issuance of not to exceed $100,000,000 Sanitary Sewer System Revenue Bonds": "bonds_financing",
        "Authorizing the acceptance of a $486,054.54 grant from the United States Department of Homeland Security": "grants",
        "Appropriating $50,000.00 from the Unappropriated Fund Balance of the Development Services Fund": "budget_funds",
        "Approving the Brooke Hills Fourth Plat": "land_use",
        "Vacating the sidewalk right-of-way in the Country Club Plaza area": "land_use",
        "Authorizing the Manager of Procurement Services to execute a one (1) year contract": "contracts",
        "Directing the Director of Public Works to repair the 63rd Street bridge": "streets_utilities",
        "Authorizing a pilot program for police patrols": "public_safety",
        "Establishing a program to help tenants avoid eviction": "housing",
        "Naming the new playground in the park": "parks_recreation",
        "Amending Chapter 2, Code of Ordinances, by repealing Section 2-1079 to adjust minimum pay": "city_code",
        "Appointing members to the Board of Zoning Adjustment": "boards_appointments",
        "Setting the date for a public hearing": "other",
    }

    def test_each_rule_fires_on_a_typical_title(self):
        for title, want in self.CASES.items():
            self.assertEqual(topics.topic_of(title), want, title)

    def test_order_matters_the_first_match_wins(self):
        self.assertEqual(topics.topic_of("Recognizing the Parks Department for its work"), "ceremonial")
        self.assertEqual(topics.topic_of("Authorizing sewer revenue bonds"), "bonds_financing")

    def test_a_sponsors_department_name_cannot_decide_the_topic(self):
        self.assertEqual(topics.topic_of("Sponsor: Director of Water Services Department Approving a pay plan"), "city_code")
        self.assertEqual(topics.topic_of("Sponsor: Director of Fire Department Authorizing the acceptance of a grant"), "grants")

    def test_every_topic_has_a_description_and_the_schema_lists_exactly_these_topics(self):
        self.assertEqual(set(topics.DESCRIPTIONS), set(topics.TOPICS))
        with open(os.path.join(paths.SCHEMAS_DIR, "topic_tagger.json"), encoding="utf-8") as f:
            enum = json.load(f)["properties"]["tags"]["items"]["properties"]["topic"]["enum"]
        self.assertEqual(enum, topics.TOPICS)

    def test_no_model_is_involved(self):
        with open(topics.__file__, encoding="utf-8") as f:
            src = f.read()
        for word in ("run_agent", "anthropic", "subprocess"):
            self.assertNotIn(word, src)


class TrendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = trends.trend_tables(EVENTS, ROWS)

    def test_only_council_meetings_are_counted(self):
        self.assertEqual(self.t["meetings"], 3)
        self.assertEqual(len(trends.appearances(EVENTS, ROWS)), 6)       # A at 2 meetings, B at 3, C at 1; the committee's row is not an appearance

    def test_a_quarter_counts_items_decided_deferred_and_held_again(self):
        q1 = self.t["by_quarter"]["2026 Q1"]
        self.assertEqual((q1["meetings"], q1["items"], q1["decided"], q1["deferred"], q1["held_again"]), (2, 4, 1, 2, 1))
        self.assertAlmostEqual(q1["deferred_share"], 2 / 3, places=3)
        self.assertEqual(q1["introduced"], 1)

    def test_the_new_ordinance_decided_on_its_first_day_is_counted(self):
        q2 = self.t["by_quarter"]["2026 Q2"]
        self.assertEqual((q2["items"], q2["decided"], q2["deferred"], q2["first_day_ordinances"]), (2, 2, 0, 1))
        self.assertEqual(q2["deferred_share"], 0.0)

    def test_days_to_passage_leave_out_matters_first_seen_inside_the_burn_in(self):
        self.assertEqual(self.t["burn_in_until"], "2026-05-08")
        self.assertIsNone(self.t["by_quarter"]["2026 Q1"]["median_days_to_passage"])       # A was first seen on 2026-01-08
        items = trends.appearances(EVENTS, ROWS)
        self.assertEqual(trends.summarize(items, None)["median_days_to_passage"], 35)       # without the burn-in it is A's 35 days

    def test_topics_group_the_items(self):
        self.assertEqual(self.t["by_topic"]["land_use"]["items"], 3)
        self.assertEqual(self.t["by_topic"]["budget_funds"]["items"], 1)
        self.assertEqual(self.t["by_topic"]["contracts"]["items"], 2)

    def test_the_share_of_other_is_reported_by_year(self):
        self.assertEqual(self.t["other_share_by_year"], {2026: 0.0})

    def test_no_data_does_not_crash(self):
        self.assertEqual(trends.trend_tables([], [])["meetings"], 0)

    def test_the_module_never_touches_a_model(self):
        with open(trends.__file__, encoding="utf-8") as f:
            src = f.read()
        for word in ("run_agent", "anthropic", "subprocess"):
            self.assertNotIn(word, src)


class TrendsPageTests(unittest.TestCase):
    def setUp(self):
        self.t = trends.trend_tables(EVENTS, ROWS)

    def test_the_page_says_every_number_is_counted_by_code_and_nothing_is_ai_written(self):
        html = trends_page(self.t)
        self.assertIn("counted by code", html)
        self.assertIn("no text on it is written by a model", html)
        self.assertNotIn("class='ai'", html)

    def test_it_shows_the_counts_and_the_shares(self):
        html = trends_page(self.t)
        self.assertIn("2026 Q1", html)
        self.assertIn("67%", html)

    def test_it_reports_the_measured_accuracy_of_the_topic_rules_when_there_is_one(self):
        self.assertIn("agree with it on 74%", trends_page(self.t, {"n": 300, "rate": 0.74}))
        self.assertIn("has not been measured yet", trends_page(self.t))

    def test_it_never_says_forgotten_or_neglected(self):
        html = trends_page(self.t).lower()
        for word in ("forgot", "neglect"):
            self.assertNotIn(word, html)

    def test_it_is_not_part_of_the_public_build(self):
        with open(os.path.join(paths.ROOT, ".github", "workflows", "nightly.yml"), encoding="utf-8") as f:
            self.assertNotIn("trends", f.read().lower())


def fake_tagger(answer):
    def runner(name, schema, payload, out_dir, loop_cap):
        usage = {"tokens_in": 100, "tokens_out": 10, "num_turns": 2, "duration_s": 1.0}
        return {"tags": [{"id": i["id"], "topic": answer(i)} for i in payload["items"]]}, usage
    return runner


class TopicSampleTests(unittest.TestCase):
    def matters(self):
        t = {}
        for n in range(30):
            t[f"c{n}"] = "Recognizing a person"
            t[f"b{n}"] = "Authorizing bonds"
            t[f"o{n}"] = "Setting a date"
        t["g1"] = "Accepting a grant"
        return t

    def test_the_sample_covers_every_topic_that_has_items_and_is_repeatable(self):
        s1 = topic_sample.build_sample(self.matters(), 40, 7)
        s2 = topic_sample.build_sample(self.matters(), 40, 7)
        self.assertEqual(s1, s2)
        self.assertEqual({r for _, _, r in s1}, {"ceremonial", "bonds_financing", "other", "grants"})
        self.assertLessEqual(len(s1), 40)

    def test_the_estimate_is_shown_before_anything_is_run(self):
        est = topic_sample.estimate_tokens(topic_sample.build_sample(self.matters(), 40, 7))
        self.assertEqual(est["calls"], 1)
        self.assertGreater(est["tokens_in"], 1500)

    def test_agreement_is_measured_overall_and_per_rule_topic(self):
        sample = [("1", "Recognizing a person", "ceremonial"), ("2", "Authorizing bonds", "bonds_financing"), ("3", "Setting a date", "other")]
        res = topic_sample.compare_tags(sample, {"s0": "ceremonial", "s1": "contracts", "s2": "other"})
        self.assertEqual((res["n"], res["agree"], res["rate"]), (3, 2, 0.667))
        self.assertEqual(res["per_rule_topic"]["bonds_financing"]["rate"], 0.0)
        self.assertEqual([r["id"] for r in res["rows"] if not r["agree"]], ["s1"])

    def test_a_balanced_sample_is_weighted_by_how_common_each_topic_is(self):
        per = {"a": {"rate": 1.0}, "b": {"rate": 0.0}}
        self.assertEqual(topic_sample.weighted_rate(per, {"a": 90, "b": 10}), 0.9)
        self.assertEqual(topic_sample.weighted_rate(per, {"a": 10, "b": 90}), 0.1)
        self.assertEqual(topic_sample.weighted_rate(per, {}), None)

    def test_the_model_gets_ids_and_titles_only_not_the_rules_answer(self):
        seen = []

        def runner(name, schema, payload, out_dir, loop_cap):
            seen.append(payload)
            return fake_tagger(lambda i: "other")(name, schema, payload, out_dir, loop_cap)
        sample = [("1", "Recognizing " + "x" * 800, "ceremonial")]
        res = topic_sample.run_sample(sample, tempfile.gettempdir(), runner=runner)
        self.assertEqual(set(seen[0]["items"][0]), {"id", "title"})
        self.assertEqual(len(seen[0]["items"][0]["title"]), topic_sample.TITLE_CHARS)
        self.assertNotIn("ceremonial", json.dumps(seen[0]["items"]))
        self.assertEqual(res["usage"], {"tokens_in": 100, "tokens_out": 10, "turns": 2, "seconds": 1.0})

    def test_without_run_no_model_is_called(self):
        d = tempfile.mkdtemp(prefix="showme-hist-")
        with open(os.path.join(d, "events.json"), "w", encoding="utf-8") as f:
            json.dump(EVENTS, f)
        os.makedirs(os.path.join(d, "rows"))
        for e in EVENTS:
            with open(os.path.join(d, "rows", f"{e['event_id']}.json"), "w", encoding="utf-8") as f:
                json.dump({"rows": [r for r in ROWS if r["event_id"] == e["event_id"]]}, f)
        buf = io.StringIO()
        with mock.patch.object(topic_sample, "run_agent", side_effect=AssertionError("called a model")), redirect_stdout(buf):
            topic_sample.main(["--history", d, "--n", "10"])
        self.assertIn("plan only: no model called", buf.getvalue())
        self.assertIn("estimate if run", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
