"""Planned versus recorded, from the city's own item rows. No model, no generated text.

Every agenda item row in Legistar carries two sequence numbers: `EventItemAgendaSequence` (set when the row is on the
agenda) and `EventItemMinutesSequence` (set when it is in the minutes). A matter gets one row per step, so the rows at a
meeting say what was planned and what happened to it, and the same matter's rows at earlier meetings say how many times
it has been held. docs/AGENDA-VS-MINUTES.md has the probe behind this.

"Planned" here is the clerk's final-revised docket: the API keeps one agenda version and it is published after the
meeting starts. The original plan is only recoverable from snapshots taken beforehand (scripts/snapshot_agendas.py).

Classes of a matter at one meeting:
  carried_through   on the agenda and the minutes record a decision (Passed, Adopted, Failed, Adv and Do Pass ...)
  advanced_on_floor on the agenda at an earlier step, then minutes-only rows advance it and it moves the same day
  deferred          held (Held on Docket, Hold on Agenda), re-referred, or referred when it had been seen before
  introduced        first appearance, ending introduced or referred: the normal start of a matter, not a deferral
  added             no row with an agenda sequence at this meeting (for example a reconsideration)
  agenda_no_minutes on the agenda but no row at all in the minutes
  receive_and_file  communications and items received and filed: not decisions
  other             a final step this module doesn't classify
"""

import datetime
import json
import os
import re

HELD = re.compile(r"\bheld\b|\bhold\b", re.I)
RE_REFERRED = re.compile(r"\bre-?referred\b", re.I)
REFERRED = re.compile(r"\breferred\b", re.I)
RECEIVED = re.compile(r"received and filed|receive and file", re.I)
DECIDED = re.compile(r"\b(passed|adopted|failed|approved)\b|\bdo pass\b", re.I)
ADVANCE = re.compile(r"move to advance", re.I)
INTRODUCED = re.compile(r"move to introduce", re.I)
MOTION = re.compile(r"^move to |waive charter|roll call", re.I)

CLASSES = ("carried_through", "advanced_on_floor", "deferred", "introduced", "added", "agenda_no_minutes",
           "receive_and_file", "other")


def compact_row(event_id, item):
    """The fields of an API event item that this module uses (and that the test fixtures keep)."""
    title = " ".join((item.get("EventItemTitle") or "").split())
    return {
        "event_id": event_id, "item_id": item.get("EventItemId"),
        "agenda_seq": item.get("EventItemAgendaSequence"), "minutes_seq": item.get("EventItemMinutesSequence"),
        "matter_file": (item.get("EventItemMatterFile") or "").strip() or None,
        "matter_id": item.get("EventItemMatterId"), "matter_guid": item.get("EventItemMatterGuid"),
        "matter_type": item.get("EventItemMatterType"),
        "action": item.get("EventItemActionName"), "passed": item.get("EventItemPassedFlagName"),
        "title": title[:1200], "mover": item.get("EventItemMover"),
    }


def action_kind(action):
    a = action or ""
    if not a.strip():
        return "none"
    if HELD.search(a):
        return "held"
    if RE_REFERRED.search(a):
        return "re_referred"
    if REFERRED.search(a):
        return "referred"
    if RECEIVED.search(a):
        return "received"
    if DECIDED.search(a):
        return "decided"
    if INTRODUCED.search(a):
        return "introduced"
    if ADVANCE.search(a):
        return "advance_motion"
    if MOTION.search(a):
        return "motion"
    return "other"


def _order(r):
    return (r["minutes_seq"] is None, r["minutes_seq"] or 0, r["agenda_seq"] or 0)


def build_index(rows, events):
    """Index the rows once so many meetings can be classified quickly (hundreds of meetings, thousands of matters)."""
    by_matter, by_event = {}, {}
    for r in rows:
        by_event.setdefault(r["event_id"], []).append(r)
        if r["matter_file"]:
            by_matter.setdefault(r["matter_file"], []).append(r)
    return {"meta": {e["event_id"]: e for e in events}, "by_matter": by_matter, "by_event": by_event}


def lifecycle(matter_file, rows, events, index=None):
    """Every step the rows record for one matter across meetings, oldest first:
    [{date, body, event_id, action, kind}]."""
    if index is not None:
        meta, candidates = index["meta"], index["by_matter"].get(matter_file, [])
    else:
        meta, candidates = {e["event_id"]: e for e in events}, [r for r in rows if r["matter_file"] == matter_file]
    steps = []
    for r in sorted((r for r in candidates if r["event_id"] in meta), key=_order):
        e = meta[r["event_id"]]
        if r["action"]:
            steps.append({"date": e["date"], "body": e["body"], "event_id": e["event_id"],
                          "action": r["action"], "kind": action_kind(r["action"])})
    return sorted(steps, key=lambda s: s["date"])


def _classify(rows_here, earlier_events):
    agenda = [r for r in rows_here if r["agenda_seq"] is not None]
    recorded = sorted((r for r in rows_here if r["minutes_seq"] is not None), key=lambda r: r["minutes_seq"])
    floor = [r for r in rows_here if r["agenda_seq"] is None and r["minutes_seq"] is not None]
    final = recorded[-1] if recorded else None
    kinds = [action_kind(r["action"]) for r in recorded]
    types = {r["matter_type"] for r in rows_here}
    if "Communication" in types or "received" in kinds:
        return "receive_and_file"
    if not agenda:
        return "added"
    if not recorded:
        return "agenda_no_minutes"
    if any(ADVANCE.search(r["action"] or "") for r in floor):
        return "advanced_on_floor"
    last = action_kind(final["action"])
    if last in ("held", "re_referred"):
        return "deferred"
    if last == "referred":
        return "deferred" if earlier_events else "introduced"
    if last == "decided":
        return "carried_through"
    if last == "introduced":
        return "introduced"
    return "other"


def classify_meeting(event_id, rows, events, index=None):
    """Classify every matter at one meeting. `rows` may include other meetings' rows (they supply the history).
    Pass `index=build_index(rows, events)` when classifying many meetings."""
    index = index or build_index(rows, events)
    here = index["meta"][event_id]
    here_rows = index["by_event"].get(event_id, [])
    by_matter = {}
    for r in here_rows:
        if r["matter_file"]:
            by_matter.setdefault(r["matter_file"], []).append(r)
    without_matter = sum(1 for r in here_rows if not r["matter_file"])

    matters = []
    for mf, rs in sorted(by_matter.items()):
        before = [s for s in lifecycle(mf, rows, events, index) if s["date"] < here["date"] and s["event_id"] != event_id]
        earlier_events = {s["event_id"] for s in before}
        agenda_rows = sorted((r for r in rs if r["agenda_seq"] is not None), key=_order)
        recorded = sorted((r for r in rs if r["minutes_seq"] is not None), key=lambda r: r["minutes_seq"])
        all_dates = [s["date"] for s in before] + [here["date"]]
        first = min(all_dates)
        matters.append({
            "matter_file": mf, "matter_type": rs[0]["matter_type"], "title": rs[0]["title"],
            "matter_id": rs[0].get("matter_id"), "matter_guid": rs[0].get("matter_guid"),
            "class": _classify(rs, earlier_events),
            "agenda_action": agenda_rows[0]["action"] if agenda_rows else None,
            "actions": [r["action"] for r in recorded],
            "final_action": recorded[-1]["action"] if recorded else None,
            # An ordinance first seen today that is also decided today skipped the usual path (introduce, committee,
            # return). Resolutions are excluded: honoring someone or recognizing a month is routinely adopted the day it appears.
            "ordinance_decided_on_first_appearance": (not earlier_events and rs[0]["matter_type"] == "Ordinance"
                                                      and any(action_kind(r["action"]) == "decided" for r in recorded)),
            "held_before": len({s["event_id"] for s in before if s["kind"] == "held"}),
            "held_dates": sorted({s["date"] for s in before if s["kind"] == "held"}),
            "re_referred_before": len({s["event_id"] for s in before if s["kind"] == "re_referred"}),
            "meetings_before": len(earlier_events),
            "first_seen": first,
            "days_since_first_seen": (_days(here["date"]) - _days(first)),
        })
    counts = {c: sum(1 for m in matters if m["class"] == c) for c in CLASSES}
    return {"meeting": {k: here.get(k) for k in ("event_id", "date", "body", "agenda_status", "agenda_published",
                                                   "minutes_status", "minutes_published")},
            "matters": matters, "counts": counts,
            "ordinance_decided_on_first_appearance": sum(1 for m in matters if m["ordinance_decided_on_first_appearance"]), "rows_without_matter": without_matter,
            "matter_count": len(matters), "held_before_any": sum(1 for m in matters if m["held_before"] > 0)}


def rows_path(history_dir, event_id):
    return os.path.join(history_dir, "rows", f"{event_id}.json")


def load_history(history_dir):
    """(events, rows) from a backfill cache folder (scripts/backfill_rows.py)."""
    with open(os.path.join(history_dir, "events.json"), encoding="utf-8") as f:
        events = json.load(f)
    rows = []
    for m in events:
        p = rows_path(history_dir, m["event_id"])
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                rows.extend(json.load(f)["rows"])
    return events, rows


def _days(iso):
    y, m, d = (int(x) for x in iso.split("-"))
    return datetime.date(y, m, d).toordinal()
