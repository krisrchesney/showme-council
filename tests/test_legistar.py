"""The Kansas City adapter, run against the cached real meeting (no network)."""

import unittest

from pipeline.sources.legistar import FixtureTransport, LegistarSource


def source():
    return LegistarSource("kansascity", prefix="kc", transport=FixtureTransport("kansascity"))


class ListNewTests(unittest.TestCase):
    def test_finds_minutes_and_agenda_for_the_council_meeting(self):
        refs = source().list_new("2026-10-22", "2026-10-23", seen=set())
        self.assertEqual({r.doc_id for r in refs}, {"kc-19561-minutes", "kc-19561-agenda"})
        m = next(r for r in refs if r.kind == "minutes")
        self.assertEqual((m.body, m.date), ("Council", "2026-10-22"))
        self.assertTrue(m.pdf_url.endswith("Meeting_Minutes.pdf"))

    def test_seen_documents_are_skipped(self):
        refs = source().list_new("2026-10-22", "2026-10-23", seen={"kc-19561-minutes"})
        self.assertEqual([r.doc_id for r in refs], ["kc-19561-agenda"])

    def test_date_window_is_half_open(self):
        self.assertEqual(source().list_new("2026-10-23", "2026-10-30", seen=set()), [])

    def test_bodies_outside_the_list_are_ignored(self):
        s = LegistarSource("kansascity", transport=FixtureTransport("kansascity"), bodies={"Parks Board"})
        self.assertEqual(s.list_new("2026-10-01", "2026-11-01", seen=set()), [])


class FetchTests(unittest.TestCase):
    def setUp(self):
        s = source()
        self.ref = next(r for r in s.list_new("2026-10-22", "2026-10-23", set()) if r.kind == "minutes")
        self.text, self.items = s.fetch(self.ref)

    def test_text_has_page_markers(self):
        self.assertTrue(self.text.startswith("=== page 1 ==="))
        self.assertIn("=== page 23 ===", self.text)

    def test_items_carry_outcomes_and_roll_calls(self):
        passed = [i for i in self.items if i["EventItemMatterFile"] == "260919"]
        self.assertEqual(passed[0]["EventItemPassedFlagName"], "Pass")
        votes = passed[0]["votes"]
        self.assertGreaterEqual(len(votes), 12)
        self.assertTrue(all(set(v) == {"name", "vote"} for v in votes))

    def test_items_without_a_vote_have_no_roll_call(self):
        referred = [i for i in self.items if i["EventItemMatterFile"] == "260931"]
        self.assertEqual(referred[0]["EventItemActionName"], "referred")
        self.assertNotIn("votes", referred[0])


if __name__ == "__main__":
    unittest.main()
