"""T-20: agenda snapshots keep every real revision, never overwrite, and write nothing in a dry run."""

import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import snapshot_agendas as sa  # noqa: E402

TODAY = datetime.date(2026, 11, 2)


def event(i, date, body="Council", file="x.pdf", status="Final", published="2026-11-03T15:00:00"):
    return {"EventId": i, "EventDate": date + "T00:00:00", "EventBodyName": body, "EventAgendaFile": file,
            "EventAgendaStatusName": status, "EventAgendaLastPublishedUTC": published}


def item(i, matter, seq, action=None):
    return {"EventItemId": i, "EventItemAgendaSequence": seq, "EventItemMinutesSequence": None, "EventItemMatterFile": matter,
            "EventItemMatterId": i, "EventItemMatterType": "Ordinance", "EventItemActionName": action, "EventItemTitle": "t " + matter}


class FakeApi:
    def __init__(self, events, items):
        self.e, self.i = events, items

    def events(self, since, until):
        return [e for e in self.e if since <= e["EventDate"][:10] < until]

    def items(self, event_id):
        return self.i[event_id]


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="showme-snap-")
        self.now = datetime.datetime(2026, 11, 3, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def api(self, **kw):
        return FakeApi([event(1, "2026-11-05", **kw)], {1: [item(10, "100", 1), item(11, "101", 2)]})

    def test_a_first_look_is_planned_and_a_dry_run_writes_nothing(self):
        res = sa.plan(self.api(), self.out, TODAY, 7)
        self.assertEqual([r["action"] for r in res], ["save"])
        self.assertEqual(os.listdir(self.out), [])

    def test_saving_writes_one_file_per_version(self):
        res = sa.plan(self.api(), self.out, TODAY, 7)
        path = sa.save(self.out, res[0], self.now)
        with open(path, encoding="utf-8") as f:
            snap = json.load(f)
        self.assertEqual((snap["event"]["event_id"], len(snap["rows"])), (1, 2))
        self.assertTrue(snap["fetched_at"].startswith("2026-11-03T12:00:00"))     # with a UTC offset

    def test_an_unchanged_agenda_is_skipped(self):
        sa.save(self.out, sa.plan(self.api(), self.out, TODAY, 7)[0], self.now)
        self.assertEqual([r["action"] for r in sa.plan(self.api(), self.out, TODAY, 7)], ["unchanged"])

    def test_a_revision_is_a_new_version_and_the_old_one_is_kept(self):
        first = sa.plan(self.api(), self.out, TODAY, 7)[0]
        sa.save(self.out, first, self.now)
        revised = FakeApi([event(1, "2026-11-05", status="Final-Revised", published="2026-11-05T21:10:00")],
                          {1: [item(10, "100", 1), item(11, "101", 2), item(12, "102", 3)]})
        second = sa.plan(revised, self.out, TODAY, 7)[0]
        self.assertEqual(second["action"], "save")
        sa.save(self.out, second, self.now + datetime.timedelta(hours=30))
        files = sorted(os.listdir(os.path.join(self.out, "1")))
        self.assertEqual(len(files), 2)
        with open(os.path.join(self.out, "1", files[0]), encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)["rows"]), 2)           # the original plan is still there

    def test_a_snapshot_is_never_overwritten(self):
        res = sa.plan(self.api(), self.out, TODAY, 7)[0]
        sa.save(self.out, res, self.now)
        with self.assertRaises(FileExistsError):
            sa.save(self.out, res, self.now)

    def test_only_the_covered_bodies_with_an_agenda_file_and_inside_the_window(self):
        api = FakeApi([event(1, "2026-11-05"), event(2, "2026-11-05", body="Parks Board"), event(3, "2026-11-06", file=None),
                       event(4, "2026-11-20"), event(5, "2026-11-06", body="Finance, Governance and Public Safety Committee")],
                      {1: [item(10, "100", 1)], 5: [item(50, "500", 1)]})
        self.assertEqual(sorted(r["event"]["event_id"] for r in sa.plan(api, self.out, TODAY, 7)), [1, 5])

    def test_the_script_never_calls_a_model(self):
        with open(sa.__file__, encoding="utf-8") as f:
            src = f.read()
        for word in ("run_agent", "anthropic", "pipeline.agents"):
            self.assertNotIn(word, src)


if __name__ == "__main__":
    unittest.main()
