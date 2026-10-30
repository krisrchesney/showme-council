"""Trends over time, from the city's rows alone (T-19). Code only: no model, no generated text.

For every Council meeting in the cache, each matter is classified (pipeline/compare.py) and given a topic by keyword rules
(pipeline/topics.py). This module counts. Definitions, so nothing here is a judgement call hidden in a number:

  items            matters on a Council agenda, counted once per meeting they appear at
  decided          carried through, advanced on the floor, or added at the meeting
  deferred         held, re-referred, or referred back (see compare.py); deferred share = deferred / (decided + deferred)
  held again       deferred items that had already been held at least once at an earlier meeting
  days to passage  from the matter's first row in the data to the meeting where an ordinance passed. Only for matters first seen
                   at least BURN_IN_DAYS after the data starts, because a matter introduced before the data begins would look
                   quicker than it was
  first-day ordinances  ordinances decided at the meeting where they first appear
"""

import datetime
import statistics

from pipeline.compare import action_kind, build_index, classify_meeting
from pipeline.topics import TOPICS, topic_of

BURN_IN_DAYS = 120
DECIDED = ("carried_through", "advanced_on_floor", "added")
BODIES = ("Council",)


def quarter(date):
    return f"{date[:4]} Q{(int(date[5:7]) - 1) // 3 + 1}"


def _passed(final_action):
    a = (final_action or "").lower()
    return action_kind(final_action) == "decided" and ("passed" in a)


def appearances(events, rows, bodies=BODIES):
    """One record per (meeting, matter) for the meetings of `bodies`."""
    idx = build_index(rows, events)
    out = []
    for e in sorted(events, key=lambda e: (e["date"], e["event_id"])):
        if e["body"] not in bodies or e["event_id"] not in idx["by_event"]:
            continue
        for m in classify_meeting(e["event_id"], rows, events, idx)["matters"]:
            out.append({"event_id": e["event_id"], "date": e["date"], "quarter": quarter(e["date"]), "year": int(e["date"][:4]),
                        "matter_file": m["matter_file"], "matter_type": m["matter_type"], "topic": topic_of(m["title"]),
                        "class": m["class"], "held_before": m["held_before"], "first_seen": m["first_seen"],
                        "days": m["days_since_first_seen"], "first_day_ordinance": m["ordinance_decided_on_first_appearance"],
                        "passed": _passed(m["final_action"]), "title": m["title"]})
    return out


def summarize(items, burn_in_until=None):
    decided = sum(1 for a in items if a["class"] in DECIDED)
    deferred = sum(1 for a in items if a["class"] == "deferred")
    days = [a["days"] for a in items
            if a["matter_type"] == "Ordinance" and a["passed"] and (burn_in_until is None or a["first_seen"] >= burn_in_until)]
    return {
        "items": len(items), "decided": decided, "deferred": deferred,
        "deferred_share": round(deferred / (decided + deferred), 3) if (decided + deferred) else None,
        "held_again": sum(1 for a in items if a["class"] == "deferred" and a["held_before"] >= 1),
        "introduced": sum(1 for a in items if a["class"] == "introduced"),
        "first_day_ordinances": sum(1 for a in items if a["first_day_ordinance"]),
        "median_days_to_passage": statistics.median(days) if days else None, "passage_n": len(days),
    }


def trend_tables(events, rows):
    items = appearances(events, rows)
    if not items:
        return {"meetings": 0, "items": 0, "span": None, "burn_in_until": None, "by_quarter": {}, "by_topic": {}, "by_year_topic": {},
                "topics": TOPICS, "other_share_by_year": {}}
    dates = sorted({a["date"] for a in items})
    data_start = min(e["date"] for e in events)
    burn = (datetime.date.fromisoformat(data_start) + datetime.timedelta(days=BURN_IN_DAYS)).isoformat()
    by_q, by_t, by_yt, other = {}, {}, {}, {}
    for key in sorted({a["quarter"] for a in items}):
        sel = [a for a in items if a["quarter"] == key]
        by_q[key] = dict(summarize(sel, burn), meetings=len({a["event_id"] for a in sel}))
    for t in TOPICS:
        sel = [a for a in items if a["topic"] == t]
        by_t[t] = summarize(sel, burn)
    for y in sorted({a["year"] for a in items}):
        by_yt[y] = {t: summarize([a for a in items if a["year"] == y and a["topic"] == t], burn) for t in TOPICS}
        ys = [a for a in items if a["year"] == y]
        other[y] = round(sum(1 for a in ys if a["topic"] == "other") / len(ys), 3)
    return {"meetings": len({a["event_id"] for a in items}), "items": len(items), "span": (dates[0], dates[-1]), "burn_in_until": burn,
            "by_quarter": by_q, "by_topic": by_t, "by_year_topic": by_yt, "topics": TOPICS, "other_share_by_year": other}
