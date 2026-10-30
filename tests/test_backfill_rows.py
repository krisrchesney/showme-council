"""T-18: the backfill resumes, copes with an empty meeting and a failed one, and reports a changed row count."""

import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import backfill_rows as br  # noqa: E402

D = datetime.date


def event(i, date, body="Council", agenda="a.pdf", minutes="m.pdf"):
    return {"EventId": i, "EventDate": date + "T00:00:00", "EventBodyName": body, "EventAgendaFile": agenda,
            "EventMinutesFile": minutes, "EventAgendaStatusName": "Final", "EventMinutesStatusName": "Final"}


def item(i, matter, aseq=1, mseq=1, action="Passed"):
    return {"EventItemId": i, "EventItemAgendaSequence": aseq, "EventItemMinutesSequence": mseq, "EventItemMatterFile": matter,
            "EventItemMatterId": i, "EventItemMatterType": "Ordinance", "EventItemActionName": action, "EventItemTitle": "t"}


class FakeApi:
    def __init__(self, events, items):
        self.e, self.i, self.calls, self.boom = events, items, [], set()

    def events(self, since, until):
        return [e for e in self.e if since <= e["EventDate"][:10] < until]

    def items(self, event_id):
        self.calls.append(event_id)
        if event_id in self.boom:
            raise RuntimeError("HTTP 500")
        return self.i[event_id]


class BackfillTests(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="showme-bf-")
        self.events = [event(1, "2026-01-08"), event(2, "2026-01-15"), event(3, "2026-02-05"),
                       event(4, "2026-02-06", body="Parks Board"), event(5, "2026-02-07", agenda=None, minutes=None)]
        self.items = {1: [item(10, "100"), item(11, "101")], 2: [], 3: [item(30, "300")]}

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def run_it(self, api, **kw):
        return br.backfill(api, self.out, D(2026, 1, 1), D(2026, 3, 1), **kw)

    def test_only_covered_bodies_with_a_file_are_fetched(self):
        api = FakeApi(self.events, self.items)
        rep = self.run_it(api)
        self.assertEqual(sorted(api.calls), [1, 2, 3])
        self.assertEqual((rep["meetings"], rep["fetched"], rep["rows"]), (3, 3, 3))

    def test_a_second_run_fetches_nothing_that_is_cached(self):
        api = FakeApi(self.events, self.items)
        self.run_it(api)
        api.calls.clear()
        rep = self.run_it(api)
        self.assertEqual((api.calls, rep["fetched"], rep["cached"]), ([], 0, 3))
        self.assertEqual(rep["rows"], 3)

    def test_an_interrupted_run_resumes_with_only_the_missing_meetings(self):
        api = FakeApi(self.events, self.items)
        api.boom = {3}
        first = self.run_it(api)
        self.assertEqual([f["event_id"] for f in first["failed"]], [3])
        api.boom, api.calls = set(), []
        second = self.run_it(api)
        self.assertEqual((api.calls, second["fetched"], second["cached"], second["failed"]), ([3], 1, 2, []))

    def test_a_meeting_with_no_items_is_cached_and_reported(self):
        rep = self.run_it(FakeApi(self.events, self.items))
        self.assertEqual(rep["no_items"], [2])
        with open(br.rows_path(self.out, 2), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["row_count"], 0)

    def test_a_changed_row_count_is_reported_on_refresh(self):
        api = FakeApi(self.events, self.items)
        self.run_it(api)
        api.i = {**self.items, 1: [item(10, "100"), item(11, "101"), item(12, "102")]}
        rep = self.run_it(api, refresh=True)
        self.assertEqual(rep["changed"], [{"event_id": 1, "date": "2026-01-08", "was": 2, "now": 3}])
        self.assertEqual(rep["fetched"], 3)

    def test_the_cache_loads_back_as_events_and_rows(self):
        self.run_it(FakeApi(self.events, self.items))
        events, rows = br.load_cache(self.out)
        self.assertEqual([e["event_id"] for e in events], [1, 2, 3])
        self.assertEqual(sorted(r["matter_file"] for r in rows), ["100", "101", "300"])
        self.assertEqual({r["event_id"] for r in rows}, {1, 3})

    def test_quarters_cover_the_range_without_gaps(self):
        qs = list(br.quarters(D(2021, 1, 1), D(2022, 2, 15)))
        self.assertEqual(qs[0], (D(2021, 1, 1), D(2021, 4, 1)))
        self.assertEqual(qs[-1], (D(2022, 1, 1), D(2022, 2, 15)))
        for (a, b), (c, d) in zip(qs, qs[1:]):
            self.assertEqual(b, c)

    def test_the_script_never_calls_a_model(self):
        with open(br.__file__, encoding="utf-8") as f:
            src = f.read()
        for word in ("run_agent", "anthropic", "pipeline.agents"):
            self.assertNotIn(word, src)


if __name__ == "__main__":
    unittest.main()
