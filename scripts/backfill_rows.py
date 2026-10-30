"""Backfill the city's item rows for every meeting since 2021 (T-18). Free: API calls only, no model.

    python scripts/backfill_rows.py --out history [--since 2021-01-01] [--until TODAY] [--refresh]

For Council and the three standing committees, every meeting that has an agenda or minutes file gets its item rows
(compact form, see pipeline/compare.py) cached once:

    OUT/events.json           one entry per meeting: id, date, body, agenda/minutes status and publish times, links
    OUT/rows/<event_id>.json  {event_id, fetched_at, row_count, rows: [...]}

Resumable: a meeting already cached is skipped. With --refresh every meeting is fetched again and any whose row count
changed is reported (the city does revise records after the fact). A meeting that fails is reported and the run goes on;
run it again to retry just those. The cache is local input for the comparison and trends pages and is not published.
"""

import argparse
import datetime
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import fetch  # noqa: E402
from pipeline.compare import compact_row, load_history as load_cache, rows_path  # noqa: E402,F401
from pipeline.sources.legistar import BASE, KC_BODIES  # noqa: E402


class LiveApi:
    def events(self, since, until):
        flt = f"EventDate ge datetime'{since}' and EventDate lt datetime'{until}'"
        q = urllib.parse.urlencode({"$filter": flt, "$orderby": "EventDate", "$top": 1000})
        return fetch.get_json(f"{BASE}/kansascity/events?{q}")

    def items(self, event_id):
        return fetch.get_json(f"{BASE}/kansascity/events/{event_id}/eventitems")


def event_meta(e):
    return {"event_id": e["EventId"], "date": e["EventDate"][:10], "body": e["EventBodyName"].strip(),
            "agenda_status": e.get("EventAgendaStatusName"), "agenda_published": e.get("EventAgendaLastPublishedUTC"),
            "minutes_status": e.get("EventMinutesStatusName"), "minutes_published": e.get("EventMinutesLastPublishedUTC"),
            "agenda_file": e.get("EventAgendaFile"), "minutes_file": e.get("EventMinutesFile"),
            "site_url": e.get("EventInSiteURL")}


def quarters(since, until):
    d = since
    while d < until:
        nxt = datetime.date(d.year + (d.month + 2) // 12, (d.month + 2) % 12 + 1, 1)
        yield d, min(nxt, until)
        d = nxt


def list_meetings(api, since, until):
    out = {}
    for a, b in quarters(since, until):
        for e in api.events(a.isoformat(), b.isoformat()):
            if e["EventBodyName"].strip() in KC_BODIES and (e.get("EventAgendaFile") or e.get("EventMinutesFile")):
                out[e["EventId"]] = event_meta(e)
    return sorted(out.values(), key=lambda m: (m["date"], m["event_id"]))


def backfill(api, out_dir, since, until, refresh=False, progress=None):
    meetings = list_meetings(api, since, until)
    os.makedirs(os.path.join(out_dir, "rows"), exist_ok=True)
    rep = {"meetings": len(meetings), "fetched": 0, "cached": 0, "no_items": [], "changed": [], "failed": [], "rows": 0}
    for n, m in enumerate(meetings, 1):
        path = rows_path(out_dir, m["event_id"])
        old = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                old = json.load(f)
            if not refresh:
                rep["cached"] += 1
                rep["rows"] += old["row_count"]
                continue
        try:
            rows = [compact_row(m["event_id"], i) for i in api.items(m["event_id"])]
        except Exception as e:  # one bad meeting must not stop the run
            rep["failed"].append({"event_id": m["event_id"], "date": m["date"], "error": str(e)[:120]})
            continue
        if not rows:
            rep["no_items"].append(m["event_id"])
        if old is not None and old["row_count"] != len(rows):
            rep["changed"].append({"event_id": m["event_id"], "date": m["date"], "was": old["row_count"], "now": len(rows)})
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"event_id": m["event_id"], "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                       "row_count": len(rows), "rows": rows}, f)
        os.replace(tmp, path)
        rep["fetched"] += 1
        rep["rows"] += len(rows)
        if progress and n % 50 == 0:
            progress(f"  {n}/{len(meetings)} meetings")
    with open(os.path.join(out_dir, "events.json"), "w", encoding="utf-8") as f:
        json.dump(meetings, f)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--since", default="2021-01-01")
    ap.add_argument("--until", default=None)
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args(argv)
    until = datetime.date.fromisoformat(a.until) if a.until else datetime.date.today() + datetime.timedelta(days=1)
    rep = backfill(LiveApi(), a.out, datetime.date.fromisoformat(a.since), until, a.refresh, progress=print)
    print(f"{rep['meetings']} meetings: {rep['fetched']} fetched, {rep['cached']} already cached, {rep['rows']:,} rows in all")
    if rep["no_items"]:
        print(f"  {len(rep['no_items'])} meetings have no item rows: {rep['no_items'][:10]}")
    for c in rep["changed"]:
        print(f"  CHANGED {c['date']} event {c['event_id']}: {c['was']} rows -> {c['now']}")
    for f_ in rep["failed"]:
        print(f"  FAILED {f_['date']} event {f_['event_id']}: {f_['error']}")
    return 1 if rep["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
