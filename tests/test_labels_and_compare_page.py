"""T-17: the one-meeting comparison page and its AI-written labels (offline: fixture rows, stand-in model calls)."""

import json
import os
import re
import tempfile
import unittest
from unittest import mock

from pipeline import compare, labels, paths, run, site
from pipeline.site import build_site, compare_page
from tests.helpers import TempDataTest

FIX = os.path.join(paths.FIXTURES, "kansascity", "rows")
with open(os.path.join(FIX, "events.json"), encoding="utf-8") as _f:
    EVENTS = json.load(_f)
with open(os.path.join(FIX, "rows.json"), encoding="utf-8") as _f:
    ROWS = json.load(_f)
RESULT = compare.classify_meeting(19561, ROWS, EVENTS)
MEETING = RESULT["meeting"]
USAGE = {"tokens_in": 100, "tokens_out": 20, "num_turns": 2, "duration_s": 5.0, "api_equiv_usd": 0.01, "models": []}


def matters(*files):
    return [m for m in RESULT["matters"] if m["matter_file"] in files]


def fake_runner(label_for, verdict_for=lambda cid, claim: "SUPPORTED", seen=None):
    """Stand-in for run_agent: the labeler writes label_for(title) and the checker answers verdict_for(id, claim)."""
    def run_agent(name, schema, payload, out_dir, loop_cap, model=None):
        if seen is not None:
            seen.append((name, payload))
        if name == "labeler":
            return {"labels": [{"matter_file": t["matter_file"], "label": label_for(t)} for t in payload["titles"]]}, dict(USAGE)
        claims = [{"id": c["id"], "verdict": verdict_for(c["id"], c), "reason": "r"} for c in payload["claims"]]
        return {"claims": claims, "sentences": []}, dict(USAGE)
    return run_agent


class LabelChecksTests(unittest.TestCase):
    def make(self, label_for, verdict_for=lambda cid, c: "SUPPORTED", files=("260445", "260919", "260920"), seen=None):
        return labels.make_labels(MEETING, matters(*files), tempfile.gettempdir(), runner=fake_runner(label_for, verdict_for, seen))

    def title_of(self, mf):
        return next(m["title"] for m in RESULT["matters"] if m["matter_file"] == mf)

    def test_a_faithful_label_that_the_checker_supports_is_shown(self):
        labs, usage = self.make(lambda t: "An ordinance to establish a fund from certain tax revenues.", files=("260919",))
        self.assertTrue(labs["260919"]["shown"])
        self.assertEqual(labs["260919"]["why_not"], [])
        self.assertEqual((usage["tokens_in"], usage["tokens_out"], usage["turns"]), (200, 40, 4))   # labeler + checker

    def test_a_number_that_is_not_in_the_title_is_rejected_even_if_the_checker_says_yes(self):
        labs, _ = self.make(lambda t: "An ordinance to spend $9,999,999 on something.", files=("260920",))
        self.assertFalse(labs["260920"]["shown"])
        self.assertIn("number_not_in_quote", labs["260920"]["why_not"])

    def test_a_label_that_reads_as_a_decision_is_rejected(self):
        labs, _ = self.make(lambda t: "The Council passed an ordinance for audio and video upgrades.", files=("260920",))
        self.assertIn("states_an_outcome", labs["260920"]["why_not"])
        self.assertFalse(labs["260920"]["shown"])

    def test_a_label_the_checker_does_not_support_is_rejected(self):
        for verdict in ("PARTIAL", "UNSUPPORTED"):
            labs, _ = self.make(lambda t: "A plain description.", lambda cid, c: verdict, files=("260919",))
            self.assertFalse(labs["260919"]["shown"])
            self.assertIn("checker_" + verdict.lower(), labs["260919"]["why_not"])

    def test_one_failed_label_does_not_take_the_others_down(self):
        def lab(t):
            return "The council approved this." if t["matter_file"] == "260445" else "A plain description."
        labs, _ = self.make(lab)
        self.assertEqual({k: v["shown"] for k, v in labs.items()}, {"260445": False, "260919": True, "260920": True})

    def test_a_title_the_labeler_skipped_is_reported(self):
        def skip(name, schema, payload, out_dir, loop_cap, model=None):
            if name == "labeler":
                return {"labels": []}, dict(USAGE)
            return {"claims": [], "sentences": []}, dict(USAGE)
        labs, _ = labels.make_labels(MEETING, matters("260919"), tempfile.gettempdir(), runner=skip)
        self.assertEqual((labs["260919"]["shown"], labs["260919"]["why_not"]), (False, ["no_label_returned"]))

    def test_a_long_label_is_rejected(self):
        labs, _ = self.make(lambda t: " ".join(["word"] * 40), files=("260919",))
        self.assertIn("label_too_long", labs["260919"]["why_not"])

    def test_the_labeler_sees_titles_only_never_actions_or_outcomes(self):
        seen = []
        self.make(lambda t: "A plain description.", seen=seen, files=("260445",))
        name, payload = seen[0]
        self.assertEqual(name, "labeler")
        self.assertEqual(set(payload), {"meeting", "titles"})
        self.assertEqual(set(payload["titles"][0]), {"matter_file", "title"})
        self.assertNotIn("Held on Docket", json.dumps(payload))

    def test_the_checker_gets_the_title_as_the_quote_and_is_not_told_anything_else(self):
        seen = []
        self.make(lambda t: "A plain description.", seen=seen, files=("260919",))
        name, payload = next(s for s in seen if s[0] == "fact-checker")
        claim = payload["claims"][0]
        self.assertEqual(claim["quote"], self.title_of("260919"))
        self.assertEqual(payload["sentences"], [])
        self.assertIn(self.title_of("260919"), payload["source"])

    def test_the_labeler_prompt_forbids_outcomes(self):
        with open(os.path.join(paths.AGENTS_DIR, "labeler.md"), encoding="utf-8") as f:
            text = f.read()
        for word in ("passed", "approved", "adopted", "authorizes"):
            self.assertIn(word, text)
        self.assertIn("never what happened", text.lower().replace("\n", " ").replace("*", ""))
        self.assertIn("never say what happened to it", text.lower())


class ComparePageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        shown = {"260947": {"label": "An ordinance to do a thing.", "shown": True, "why_not": []},
                 "260919": {"label": "An ordinance about a fund.", "shown": True, "why_not": []},
                 "260920": {"label": "The council approved this.", "shown": False, "why_not": ["states_an_outcome"]}}
        cls.with_labels = compare_page(RESULT, shown, {"site_url": "https://example.test/m"})
        cls.without = compare_page(RESULT, None)

    def ai_items(self, html):
        return len(re.findall(r"<span class='ai'>AI-written</span><i>", html))

    def test_labels_appear_only_where_they_passed_and_are_tagged_ai_written(self):
        self.assertEqual(self.ai_items(self.with_labels), 2)
        self.assertIn("An ordinance to do a thing.", self.with_labels)
        self.assertNotIn("The council approved this.", self.with_labels)      # failed: the official title is shown instead
        self.assertEqual(self.ai_items(self.without), 0)

    def test_an_item_with_no_passing_label_shows_the_official_title(self):
        self.assertIn("Official title:", self.without)
        self.assertIn("Vacating the sidewalk", self.without)

    def test_the_page_says_what_is_code_verified_and_what_is_ai_written(self):
        for html in (self.with_labels, self.without):
            self.assertIn("city's record", html)
            self.assertIn("computed by code", html)
            self.assertIn("written by a model", html)
            self.assertIn("official title is shown instead", html)

    def test_the_page_says_planned_means_the_final_revised_docket(self):
        self.assertIn("not necessarily the original plan", self.without)
        self.assertIn("Final-Revised", self.without)

    def test_counts_match_the_matcher_exactly(self):
        for key, title, _ in site.COMPARE_GROUPS:
            n = RESULT["counts"][key]
            if n:
                self.assertRegex(self.without, rf"{re.escape(title)}\s*\({n}\)")
        self.assertIn(f"<b>{RESULT['matter_count']}</b>", self.without)

    def test_the_most_held_item_shows_its_dates_from_the_citys_rows(self):
        self.assertIn("Held 8 times before: 2026-05-12, 2026-05-21", self.without)
        self.assertIn("First seen 2026-05-07 (168 days earlier)", self.without)

    def test_the_word_forgotten_is_never_used(self):
        for html in (self.with_labels, self.without):
            self.assertNotIn("forgot", html.lower())

    def test_no_item_is_dropped_and_each_appears_once(self):
        for m in RESULT["matters"]:
            self.assertEqual(self.without.count(f"<span class='num'>{m['matter_file']}</span>"), 1, m["matter_file"])

    def test_the_two_real_skips_are_flagged_as_ordinances_decided_on_first_appearance(self):
        self.assertEqual(self.without.count("An ordinance decided on the day it first appeared."), 2)

    def test_it_is_not_part_of_the_public_build(self):
        with open(os.path.join(paths.ROOT, ".github", "workflows", "nightly.yml"), encoding="utf-8") as f:
            wf = f.read()
        self.assertNotIn("compare", wf.lower())
        with open(os.path.join(paths.ROOT, "pipeline", "run.py"), encoding="utf-8") as f:
            src = f.read()
        nightly_src = src[src.index("def nightly("):src.index("def main(")]
        self.assertNotIn("compare", nightly_src)
        self.assertNotIn("labels", nightly_src)


class CommandTests(TempDataTest):
    def history(self):
        d = tempfile.mkdtemp(prefix="showme-hist-")
        events = [dict(e, site_url="https://example.test/m", agenda_file=None, minutes_file=None) for e in EVENTS]
        with open(os.path.join(d, "events.json"), "w", encoding="utf-8") as f:
            json.dump(events, f)
        os.makedirs(os.path.join(d, "rows"))
        for e in EVENTS:
            with open(os.path.join(d, "rows", f"{e['event_id']}.json"), "w", encoding="utf-8") as f:
                json.dump({"event_id": e["event_id"], "rows": [r for r in ROWS if r["event_id"] == e["event_id"]]}, f)
        return d

    def test_compare_page_command_writes_a_local_file_and_calls_no_model(self):
        out = tempfile.mkdtemp(prefix="showme-prev-")
        with mock.patch.object(run, "run_agent", side_effect=AssertionError("called a model")):
            run.main(["compare-page", "19561", "--history", self.history(), "--out", out])
        with open(os.path.join(out, "compare-19561.html"), encoding="utf-8") as f:
            self.assertIn("planned and what happened", f.read())

    def test_compare_labels_command_saves_the_labels_and_the_usage(self):
        out = tempfile.mkdtemp(prefix="showme-prev-")
        fake = {"260919": {"label": "An ordinance about a fund.", "shown": True, "why_not": []}}
        usage = {"tokens_in": 10, "tokens_out": 2, "turns": 4, "seconds": 3.0, "api_equiv_usd": 0.0}
        with mock.patch.object(labels, "make_labels", return_value=(fake, usage)):
            run.main(["compare-labels", "19561", "--history", self.history(), "--out", out])
        with open(os.path.join(out, "labels-19561.json"), encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["usage"]["turns"], 4)
        with open(os.path.join(out, "compare-19561.html"), encoding="utf-8") as f:
            self.assertIn("An ordinance about a fund.", f.read())

    def test_the_public_site_build_has_no_comparison_pages(self):
        out, _ = build_site()
        self.assertEqual(sorted(os.listdir(out)), ["doc", "index.html"])
        with open(os.path.join(out, "index.html"), encoding="utf-8") as f:
            self.assertNotIn("planned and what happened", f.read())


if __name__ == "__main__":
    unittest.main()
