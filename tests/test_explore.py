"""T-21: the explorer site and the multi-topic rules (offline: the checked-in rows fixture, no network, no model)."""

import json
import os
import re
import tempfile
import unittest

from pipeline import explore, paths, topics

FIX = os.path.join(paths.ROOT, "tests", "fixtures", "kansascity", "rows")


def fixture_history(_dir):
    with open(os.path.join(FIX, "events.json"), encoding="utf-8") as f:
        events = json.load(f)
    with open(os.path.join(FIX, "rows.json"), encoding="utf-8") as f:
        rows = json.load(f)
    return events, rows


def sample_result():
    rows = []
    for i in range(10):
        rows.append({"id": f"s{i}", "title": "x", "rule": "contracts", "rules": ["contracts"], "model": "contracts" if i < 9 else "other"})
    for i in range(2):
        rows.append({"id": f"p{i}", "title": "x", "rule": "public_safety", "rules": ["public_safety"], "model": "other"})
    return {"n": len(rows), "rate": 0.8, "primary_rate": 0.8, "rows": rows}


class TopicRules(unittest.TestCase):
    def test_an_item_can_carry_several_topics_and_the_earliest_keyword_leads(self):
        t = "Authorizing the issuance of bonds for the Water Services Department"
        self.assertEqual(topics.topic_list(t)[0], "bonds_financing")
        self.assertIn("streets_utilities", topics.topic_list(t))
        self.assertEqual(topics.topic_of("Amending Chapter 88, the Zoning and Development Code"), "city_code")

    def test_paperwork_words_do_not_decide_the_topic(self):
        t = "Sponsor: City Manager's Office COMMITTEE SUBSTITUTE Setting a fee schedule; directing the City Clerk to record certain documents; and recognizing this ordinance as having an accelerated effective date. FINANCE COMMITTEE Advance and Do Pass"
        self.assertNotIn("ceremonial", topics.topic_list(t))
        self.assertNotIn("finance", topics.body_of(t))

    def test_street_names_in_addresses_are_not_a_topic(self):
        t = "Approving the plat of East Campus on about 35 acres generally located at the corner of Botts Road and Main Street"
        self.assertNotIn("streets_utilities", topics.topic_list(t))
        self.assertIn("land_use", topics.topic_list(t))

    def test_annual_report_notices_are_other_and_nothing_matches_gives_other(self):
        self.assertEqual(topics.topic_list("Notice to the City Clerk of the Zona Rosa Community Improvement District's Annual Report"), ["other"])
        self.assertEqual(topics.topic_list("A thing nobody has a rule for"), ["other"])

    def test_short_title_only_cuts_words_off(self):
        t = "Sponsor: Mayor X COMMITTEE SUBSTITUTE Approving the thing at length " + "word " * 80 + "FINANCE COMMITTEE Advance and Do Pass"
        s = topics.short_title(t, 100)
        self.assertTrue(s.startswith("Approving the thing"))
        self.assertLessEqual(len(s), 101)
        self.assertNotIn("COMMITTEE", s)


class Accuracy(unittest.TestCase):
    def test_found_and_lead_rates_per_topic(self):
        acc = explore.accuracy_from_sample(sample_result())
        self.assertEqual(acc["per_topic"]["contracts"]["lead_rate"], 0.9)
        self.assertEqual(acc["per_topic"]["public_safety"]["lead_rate"], 0.0)

    def test_weak_or_thin_topics_are_folded_and_the_reason_is_given(self):
        acc = explore.accuracy_from_sample(sample_result())
        acc["per_topic"]["public_safety"]["lead_n"] = 20
        acc["per_topic"]["public_safety"]["model_n"] = 12
        acc["per_topic"]["public_safety"]["found_rate"] = 0.9
        f = explore.folded_topics(acc)
        self.assertIn("public_safety", f)
        self.assertNotIn("contracts", f)
        self.assertEqual(explore.shown_topics("The police department", f), ["other"])
        self.assertEqual(explore.shown_topics("A contract with a vendor", f), ["contracts"])


class Site(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.site = explore.build_explorer("unused", "unused", accuracy=explore.accuracy_from_sample(sample_result()),
                                          built_at="2026-01-01 00:00 UTC", load_history=fixture_history)
        cls.html = {p: t for p, t in cls.site.pages.items() if p.endswith(".html")}

    def test_every_page_has_the_notice_the_credit_and_a_corrections_link(self):
        self.assertGreater(len(self.html), 20)
        for path, text in self.html.items():
            self.assertIn("Unofficial", text, path)
            self.assertIn("published through Legistar", text, path)
            self.assertIn("/issues", text, path)
            self.assertIn("name='viewport'", text, path)

    def test_the_main_pages_exist(self):
        for p in ("index.html", "meetings.html", "topics.html", "search.html", "trends.html", "about.html"):
            self.assertIn(p, self.site.pages)
        self.assertTrue(any(p.startswith("matter/") for p in self.html))
        self.assertTrue(any(p.startswith("meeting/") for p in self.html))
        self.assertIn("search.json", self.site.pages)

    def test_no_nightly_claim_until_a_schedule_exists_and_no_judging_words(self):
        for path, text in self.html.items():
            self.assertNotRegex(text, r"(?i)updated nightly", path)
            self.assertNotIn("forgotten", text.lower(), path)

    def test_no_page_ranks_or_profiles_people(self):
        for path, text in self.html.items():
            self.assertNotRegex(text.lower(), r"voting record of|voted (yes|no) (more|less)|most (absent|obstruct)", path)
        self.assertIn("does not show or compare how individual council members voted", self.html["about.html"])

    def test_nothing_private_is_in_the_pages(self):
        for path, text in list(self.site.pages.items()):
            self.assertNotRegex(text, r"[A-Za-z]:\\Users\\|claude\.ai/artifact|CLAUDE_CODE_OAUTH|sk-ant-", path)

    def test_local_links_resolve_to_pages_that_exist(self):
        for path, text in self.html.items():
            base = os.path.dirname(path)
            for href in re.findall(r"href='([^']+)'", text):
                if href.startswith(("http", "#", "mailto:")):
                    continue
                target = os.path.normpath(os.path.join(base, href.split("#")[0])).replace("\\", "/")
                self.assertIn(target, self.site.pages, f"{path} -> {href}")

    def test_a_meeting_without_a_summary_says_so_and_has_no_ai_badge_content(self):
        meeting = next(t for p, t in self.html.items() if p.startswith("meeting/"))
        self.assertIn("records alone", meeting)
        self.assertIn("badge code", meeting)
        self.assertNotIn("AI-written, checked", meeting)

    def test_matter_pages_show_the_path_and_the_city_wording(self):
        text = self.html["matter/260445.html"]
        self.assertIn("Its path through the Council", text)
        self.assertIn("Referred to a committee", text)
        self.assertIn("(referred)", text)

    def test_search_index_has_numbers_titles_and_topics(self):
        idx = json.loads(self.site.pages["search.json"])
        row = next(r for r in idx if r[0] == "260445")
        self.assertEqual(len(row), 6)
        self.assertTrue(row[1] and row[2])

    def test_writing_creates_the_files(self):
        with tempfile.TemporaryDirectory() as d:
            self.site.write(d)
            self.assertTrue(os.path.exists(os.path.join(d, "index.html")))
            self.assertTrue(os.path.exists(os.path.join(d, "style.css")))
            self.assertTrue(os.path.exists(os.path.join(d, "matter", "260445.html")))

    def test_charts_have_a_text_equivalent(self):
        t = self.html["trends.html"]
        self.assertIn("role='img'", t)
        self.assertIn("Show the numbers", t)


if __name__ == "__main__":
    unittest.main()
