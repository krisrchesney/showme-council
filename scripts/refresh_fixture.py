"""Re-download the offline test fixture: one real Kansas City Council meeting.

    python scripts/refresh_fixture.py [--event-id 19561]

Writes tests/fixtures/kansascity/: events.json (that one event), eventitems_<id>.json,
votes.json (item id -> roll call) and the minutes text. Run it by hand when the
fixture should change. Tests never touch the network.
"""

import argparse
import datetime
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import paths  # noqa: E402
from pipeline.sources.legistar import ITEM_FIELDS, LiveTransport  # noqa: E402

EVENT_FIELDS = ("EventId", "EventBodyName", "EventDate", "EventTime", "EventAgendaFile",
                "EventMinutesFile", "EventInSiteURL", "EventLastModifiedUTC")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--event-id", type=int, default=19561)  # KC Council, 2026-10-22
    ap.add_argument("--date", default="2026-10-22")
    args = ap.parse_args()

    t = LiveTransport("kansascity")
    out = os.path.join(paths.FIXTURES, "kansascity")
    os.makedirs(out, exist_ok=True)

    day_after = (datetime.date.fromisoformat(args.date) + datetime.timedelta(days=1)).isoformat()
    events = [e for e in t.events(args.date, day_after) if e["EventId"] == args.event_id]
    if not events:
        sys.exit(f"event {args.event_id} not found on {args.date}")
    ev = events[0]
    items = t.event_items(args.event_id)
    votes = {str(i["EventItemId"]): [{k: v[k] for k in ("VotePersonName", "VoteValueName")} for v in t.votes(i["EventItemId"])]
             for i in items if i.get("EventItemPassedFlagName")}
    # Keep only the fields the adapter reads, so the fixture stays small and reviewable.
    events = [{k: e.get(k) for k in EVENT_FIELDS} for e in events]
    items = [{k: i.get(k) for k in ITEM_FIELDS} for i in items]

    def dump(name, obj):
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=1)

    dump("events.json", events)
    dump(f"eventitems_{args.event_id}.json", items)
    dump("votes.json", votes)
    url = ev["EventMinutesFile"]
    name = os.path.basename(urllib.parse.urlparse(url).path).rsplit(".", 1)[0] + ".txt"
    with open(os.path.join(out, name), "w", encoding="utf-8") as f:
        f.write(t.pdf_text(url))
    print(f"wrote {out}: {len(items)} items, {len(votes)} roll calls, minutes -> {name}")


if __name__ == "__main__":
    main()
