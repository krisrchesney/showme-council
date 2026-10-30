"""Save the compact item rows the agenda-vs-minutes matcher needs, for offline tests. Free: API calls only.

    python scripts/refresh_rows_fixture.py [--since 2026-04-01] [--events 19561 19539 19521 19460]

Writes tests/fixtures/kansascity/rows/events.json and rows.json: every row of the named meetings, plus the rows of
every matter on those meetings at the other meetings (Council and the three standing committees) since --since, so
"held N times before this meeting" can be computed from rows alone.
"""

import argparse
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import fetch, paths  # noqa: E402
from pipeline.compare import compact_row  # noqa: E402
from pipeline.sources.legistar import BASE, KC_BODIES  # noqa: E402

DEFAULT_EVENTS = [19561, 19539, 19521, 19460]


def events_between(since, until):
    flt = f"EventDate ge datetime'{since}' and EventDate lt datetime'{until}'"
    q = urllib.parse.urlencode({"$filter": flt, "$orderby": "EventDate"})
    return [e for e in fetch.get_json(f"{BASE}/kansascity/events?{q}") if e["EventBodyName"].strip() in KC_BODIES]


def event_meta(e):
    return {"event_id": e["EventId"], "date": e["EventDate"][:10], "body": e["EventBodyName"].strip(),
            "agenda_status": e.get("EventAgendaStatusName"), "agenda_published": e.get("EventAgendaLastPublishedUTC"),
            "minutes_status": e.get("EventMinutesStatusName"), "minutes_published": e.get("EventMinutesLastPublishedUTC")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-04-01")
    ap.add_argument("--events", type=int, nargs="*", default=DEFAULT_EVENTS)
    a = ap.parse_args()

    target = {eid: fetch.get_json(f"{BASE}/kansascity/events/{eid}") for eid in a.events}
    last = max(e["EventDate"][:10] for e in target.values())
    window = events_between(a.since, last + "T23:59:59")
    window_ids = {e["EventId"] for e in window} | set(target)
    by_event = {}
    for eid in sorted(window_ids):
        by_event[eid] = [compact_row(eid, i) for i in fetch.get_json(f"{BASE}/kansascity/events/{eid}/eventitems")]
    wanted = {r["matter_file"] for eid in a.events for r in by_event[eid] if r["matter_file"]}

    rows, events = [], []
    meta_by_id = {e["EventId"]: e for e in window}
    meta_by_id.update(target)
    for eid, rs in by_event.items():
        keep = rs if eid in a.events else [r for r in rs if r["matter_file"] in wanted]
        if keep:
            rows.extend(keep)
            events.append(event_meta(meta_by_id[eid]))
    out = os.path.join(paths.FIXTURES, "kansascity", "rows")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "events.json"), "w", encoding="utf-8") as f:
        json.dump(sorted(events, key=lambda e: e["date"]), f, indent=0)
    with open(os.path.join(out, "rows.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=0)
    print(f"wrote {out}: {len(events)} meetings, {len(rows)} rows, {len(wanted)} matters on the {len(a.events)} named meetings")


if __name__ == "__main__":
    main()
