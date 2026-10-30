"""T-16: planned versus recorded, computed from the city's own rows (four saved meetings, no model, no network)."""

import json
import os
import re
import unittest

from pipeline import compare, paths
from pipeline.compare import CLASSES, action_kind, classify_meeting, lifecycle

ROWS_DIR = os.path.join(paths.FIXTURES, "kansascity", "rows")


def load(name):
    with open(os.path.join(ROWS_DIR, name), encoding="utf-8") as f:
        return json.load(f)


EVENTS, ROWS = load("events.json"), load("rows.json")
OCT22, OCT08, OCT01, SEP08 = 19561, 19539, 19521, 19460


def matter(result, mf):
    return next(m for m in result["matters"] if m["matter_file"] == mf)


def row(event, matter_file, action, agenda=None, minutes=None, mtype="Ordinance"):
    return {"event_id": event, "item_id": None, "agenda_seq": agenda, "minutes_seq": minutes, "matter_file": matter_file,
            "matter_id": 1, "matter_type": mtype, "action": action, "passed": None, "title": "t", "mover": None}


def ev(i, date, body="Council"):
    return {"event_id": i, "date": date, "body": body}


class FourSavedMeetingsTests(unittest.TestCase):
    """Counts pinned against the saved rows. Totals: 47, 34, 31 and 5 matters."""

    @classmethod
    def setUpClass(cls):
        cls.r = {e: classify_meeting(e, ROWS, EVENTS) for e in (OCT22, OCT08, OCT01, SEP08)}

    def counts(self, eid):
        return tuple(self.r[eid]["counts"][c] for c in CLASSES)

    def test_class_counts(self):
        #       carried, advanced, deferred, introduced, added, agenda-no-minutes, receive-and-file, other
        self.assertEqual(self.counts(OCT22), (27, 2, 1, 15, 0, 0, 2, 0))
        self.assertEqual(self.counts(OCT08), (7, 2, 2, 23, 0, 0, 0, 0))
        self.assertEqual(self.counts(OCT01), (18, 2, 0, 10, 1, 0, 0, 0))
        self.assertEqual(self.counts(SEP08), (3, 0, 2, 0, 0, 0, 0, 0))

    def test_every_matter_is_in_exactly_one_class(self):
        for r in self.r.values():
            self.assertEqual(sum(r["counts"].values()), r["matter_count"])
        self.assertEqual([self.r[e]["matter_count"] for e in (OCT22, OCT08, OCT01, SEP08)], [47, 34, 31, 5])

    def test_planned_for_introduction_or_consideration_but_passed_the_same_day(self):
        for mf, planned in (("260947", "Move To Introduce"), ("260946", "Move to Consider")):
            m = matter(self.r[OCT22], mf)
            self.assertEqual((m["class"], m["agenda_action"], m["actions"][-1]), ("advanced_on_floor", planned, "Passed"))
            self.assertTrue(m["ordinance_decided_on_first_appearance"])
        self.assertEqual(self.r[OCT22]["ordinance_decided_on_first_appearance"], 2)

    def test_amended_and_advanced_is_not_counted_as_skipping_the_usual_path(self):
        m = matter(self.r[OCT08], "260888")
        self.assertEqual(m["class"], "advanced_on_floor")
        self.assertFalse(m["ordinance_decided_on_first_appearance"])     # it had been seen at 2 earlier meetings
        self.assertEqual(m["meetings_before"], 2)

    def test_a_reconsideration_that_was_never_on_the_agenda_is_added(self):
        m = matter(self.r[OCT01], "260850")
        self.assertEqual((m["class"], m["agenda_action"]), ("added", None))
        self.assertEqual(m["actions"], ["Move to Reconsider", "Move to Advance", "Passed"])

    def test_a_planned_introduction_that_ended_referred_is_the_normal_start_not_a_deferral(self):
        m = matter(self.r[OCT01], "260893")
        self.assertEqual((m["class"], m["agenda_action"], m["final_action"]), ("introduced", "Move To Introduce", "referred"))

    def test_the_matter_held_the_most(self):
        m = matter(self.r[OCT22], "260445")
        self.assertEqual((m["class"], m["held_before"], m["first_seen"], m["days_since_first_seen"]), ("deferred", 8, "2026-05-07", 168))
        self.assertEqual(matter(self.r[OCT08], "260445")["held_before"], 7)

    def test_a_matter_can_be_held_many_times_and_then_pass(self):
        m = matter(self.r[OCT08], "260563")
        self.assertEqual((m["class"], m["held_before"]), ("carried_through", 6))

    def test_committee_holds_and_advances(self):
        r = self.r[SEP08]
        self.assertEqual(sorted(m["matter_file"] for m in r["matters"] if m["class"] == "deferred"), ["260729", "260834"])
        self.assertEqual(matter(r, "260729")["held_before"], 1)
        self.assertEqual(sorted(m["matter_file"] for m in r["matters"] if m["class"] == "carried_through"), ["260748", "260818", "260827"])

    def test_nothing_on_these_four_agendas_went_missing_from_the_minutes(self):
        self.assertEqual([self.r[e]["counts"]["agenda_no_minutes"] for e in self.r], [0, 0, 0, 0])

    def test_the_output_has_only_fields_the_city_supplied_or_counts_of_them(self):
        keys = set(self.r[OCT22]["matters"][0])
        self.assertEqual(keys, {"matter_file", "matter_type", "title", "class", "agenda_action", "actions", "final_action",
                                "ordinance_decided_on_first_appearance", "held_before", "re_referred_before", "meetings_before",
                                "first_seen", "days_since_first_seen"})
        row_titles = {r["matter_file"]: r["title"] for r in ROWS if r["matter_file"]}
        for m in self.r[OCT22]["matters"]:
            self.assertEqual(m["title"], row_titles[m["matter_file"]])      # copied from the row, never written

    def test_held_count_matches_the_citys_own_matter_history(self):
        # The per-matter history endpoint (checked live on 2026-10-29) lists 9 holds for 260445 up to and including 10-22,
        # one of them the committee's Hold on Agenda on 05-12. The rows give the same total.
        steps = lifecycle("260445", ROWS, EVENTS)
        self.assertEqual(sum(1 for s in steps if s["kind"] == "held"), 9)
        self.assertEqual((steps[0]["date"], steps[0]["action"]), ("2026-05-07", "referred"))
        self.assertEqual([s["date"] for s in steps if s["kind"] == "held"][:3], ["2026-05-12", "2026-05-21", "2026-06-11"])


class RuleTests(unittest.TestCase):
    def test_action_kinds_use_the_citys_wording(self):
        cases = {"Held on Docket": "held", "Hold on Agenda": "held", "Re-referred": "re_referred", "referred": "referred",
                 "received and filed": "received", "Passed as Substituted as Amended": "decided", "Adopted": "decided",
                 "Adv and Do Pass as Cmte Sub": "decided", "Move To Introduce": "introduced", "Move to Advance": "advance_motion",
                 "Move to Amend": "motion", "Roll Call": "motion", None: "none"}
        for action, kind in cases.items():
            self.assertEqual(action_kind(action), kind, action)

    def test_a_matter_on_the_agenda_with_no_minutes_row_is_reported(self):
        rows = [row(1, "100", "Move To Introduce", agenda=5)]
        r = classify_meeting(1, rows, [ev(1, "2026-01-01")])
        self.assertEqual(matter(r, "100")["class"], "agenda_no_minutes")

    def test_referred_is_a_deferral_only_if_the_matter_was_seen_before(self):
        events = [ev(1, "2026-01-01"), ev(2, "2026-02-01")]
        rows = [row(1, "100", "referred", agenda=1, minutes=1), row(2, "100", "referred", agenda=1, minutes=1)]
        self.assertEqual(matter(classify_meeting(1, rows, events), "100")["class"], "introduced")
        self.assertEqual(matter(classify_meeting(2, rows, events), "100")["class"], "deferred")

    def test_communications_and_received_items_are_not_decisions(self):
        rows = [row(1, "200", "received and filed", agenda=1, minutes=1, mtype="Communication"),
                row(1, "201", "received and filed", agenda=2, minutes=2)]
        r = classify_meeting(1, rows, [ev(1, "2026-01-01")])
        self.assertEqual([m["class"] for m in r["matters"]], ["receive_and_file", "receive_and_file"])

    def test_rows_without_a_matter_are_counted_not_classified(self):
        rows = [row(1, None, None, minutes=1), row(1, "300", "Passed", agenda=2, minutes=2)]
        r = classify_meeting(1, rows, [ev(1, "2026-01-01")])
        self.assertEqual((r["rows_without_matter"], r["matter_count"]), (1, 1))

    def test_a_hold_at_the_same_meeting_is_not_counted_as_before(self):
        events = [ev(1, "2026-01-01"), ev(2, "2026-02-01")]
        rows = [row(1, "400", "Held on Docket", agenda=1, minutes=1), row(2, "400", "Held on Docket", agenda=1, minutes=1)]
        self.assertEqual(matter(classify_meeting(2, rows, events), "400")["held_before"], 1)
        self.assertEqual(matter(classify_meeting(1, rows, events), "400")["held_before"], 0)

    def test_a_meeting_is_counted_once_even_with_several_held_rows(self):
        events = [ev(1, "2026-01-01"), ev(2, "2026-02-01")]
        rows = [row(1, "500", "Held on Docket", agenda=1, minutes=1), row(1, "500", "Held on Docket", agenda=9, minutes=9),
                row(2, "500", "Held on Docket", agenda=1, minutes=1)]
        self.assertEqual(matter(classify_meeting(2, rows, events), "500")["held_before"], 1)


class NoModelTests(unittest.TestCase):
    def test_the_module_never_touches_a_model_or_the_agents(self):
        with open(compare.__file__, encoding="utf-8") as f:
            src = f.read()
        imports = re.findall(r"(?m)^(?:from|import) (\S+)", src)
        self.assertEqual(sorted(set(imports)), ["datetime", "re"])        # only the standard library
        for word in ("run_agent", "anthropic", "subprocess", "urllib", "pipeline"):
            self.assertNotIn(word, src, word)


if __name__ == "__main__":
    unittest.main()
