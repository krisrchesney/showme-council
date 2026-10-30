"""Save upcoming agendas before the city revises them (T-20). Free: API calls only, no model.

    python scripts/snapshot_agendas.py --out DIR [--days 7] [--from 2026-10-29] [--save]

The Legistar API keeps one agenda version per meeting and the clerk republishes it ("Final-Revised") around and after
the meeting, so for a past meeting the original plan is gone. This saves what the agenda looks like NOW for each
meeting in the next --days days (Council and the three standing committees), as one file per version:

    DIR/<event_id>/<fetched-at>.json   {fetched_at, event: {...}, rows: [compact item rows]}

A version identical to the latest saved one (same status, publish time and rows) is skipped, so a nightly run keeps
every real revision and nothing else. Nothing is ever overwritten. Without --save it only prints what it would do.
Scheduled by .github/workflows/snapshots.yml (twice a day), onto its own `snapshots` branch, append-only.
"""

import argparse
import datetime
import hashlib
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline import fetch  # noqa: E402
from pipeline.compare import compact_row  # noqa: E402
from pipeline.sources.legistar import BASE, KC_BODIES  # noqa: E402


class LiveApi:
    def events(self, since, until):
        flt = f"EventDate ge datetime'{since}' and EventDate lt datetime'{until}'"
        q = urllib.parse.urlencode({"$filter": flt, "$orderby": "EventDate"})
        return fetch.get_json(f"{BASE}/kansascity/events?{q}")

    def items(self, event_id):
        return fetch.get_json(f"{BASE}/kansascity/events/{event_id}/eventitems")


def fingerprint(event, rows):
    """What makes one agenda version different from another."""
    ident = sorted((r["item_id"], r["agenda_seq"], r["matter_file"], r["action"]) for r in rows)
    return hashlib.sha256(json.dumps([event["agenda_status"], event["agenda_published"], ident], default=str).encode()).hexdigest()[:16]


def latest_fingerprint(out_dir, event_id):
    d = os.path.join(out_dir, str(event_id))
    if not os.path.isdir(d):
        return None
    files = sorted(f for f in os.listdir(d) if f.endswith(".json"))
    if not files:
        return None
    with open(os.path.join(d, files[-1]), encoding="utf-8") as f:
        return json.load(f).get("fingerprint")


def plan(api, out_dir, today, days):
    """What a run would do: [{event, rows, fingerprint, action}] where action is 'save' or 'unchanged'."""
    until = (today + datetime.timedelta(days=days + 1)).isoformat()
    results = []
    for e in api.events(today.isoformat(), until):
        body = e["EventBodyName"].strip()
        if body not in KC_BODIES or not e.get("EventAgendaFile"):
            continue
        rows = [compact_row(e["EventId"], i) for i in api.items(e["EventId"])]
        event = {"event_id": e["EventId"], "date": e["EventDate"][:10], "body": body, "agenda_file": e["EventAgendaFile"],
                 "agenda_status": e.get("EventAgendaStatusName"), "agenda_published": e.get("EventAgendaLastPublishedUTC")}
        fp = fingerprint(event, rows)
        results.append({"event": event, "rows": rows, "fingerprint": fp,
                        "action": "unchanged" if latest_fingerprint(out_dir, e["EventId"]) == fp else "save"})
    return results


def save(out_dir, result, now):
    d = os.path.join(out_dir, str(result["event"]["event_id"]))
    os.makedirs(d, exist_ok=True)
    name = now.strftime("%Y%m%dT%H%M%SZ") + ".json"
    path = os.path.join(d, name)
    if os.path.exists(path):
        raise FileExistsError(path)      # never overwrite a snapshot
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"fetched_at": now.isoformat(timespec="seconds"), "fingerprint": result["fingerprint"],
                   "event": result["event"], "rows": result["rows"]}, f, indent=0)
    return path


def run(api, out_dir, today, days, now, save_files=False, remote=None, branch="snapshots", push=False, log=print):
    """One snapshot pass. With a remote, the branch's earlier snapshots are restored first (so unchanged agendas are skipped)
    and, with push, the new files are added to the branch append-only. Returns the plan."""
    import publish_data
    if remote:
        publish_data.restore_branch(out_dir, remote, branch)
    results = plan(api, out_dir, today, days)
    if not results:
        log(f"no meeting with an agenda file between {today} and {today + datetime.timedelta(days=days)}")
    new = 0
    for r in results:
        e = r["event"]
        verb = r["action"] if not save_files else ("saved" if r["action"] == "save" else "unchanged")
        log(f"{e['date']} {e['body'][:44]:44} agenda {e['agenda_status']}, published {str(e['agenda_published'])[:16]}, "
            f"{len(r['rows'])} rows, {sum(1 for x in r['rows'] if x['agenda_seq'] is not None)} on the agenda -> "
            f"{'would ' if not save_files else ''}{verb}")
        if save_files and r["action"] == "save":
            save(out_dir, r, now)
            new += 1
    if not save_files:
        log("dry run: nothing written (add --save to write)")
    elif remote and push and new:
        committed, added, pushed = publish_data.commit_tree(out_dir, remote, branch, f"Agenda snapshots: {new} new version(s)")
        log(f"{'pushed' if pushed else 'not pushed'}: {len(added)} file(s) on the {branch} branch")
    elif remote and push:
        log("nothing new to push")
    return results


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--remote", default=None, help="git remote URL holding the snapshots branch; earlier snapshots are restored from it")
    ap.add_argument("--branch", default="snapshots")
    ap.add_argument("--push", action="store_true", help="with --save and --remote: add new snapshots to the branch (append-only)")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--from", dest="start", default=None, help="first date to look at (default: today, UTC)")
    ap.add_argument("--save", action="store_true", help="write the snapshots (default: only print the plan)")
    a = ap.parse_args(argv)
    now = datetime.datetime.now(datetime.timezone.utc)
    today = datetime.date.fromisoformat(a.start) if a.start else now.date()
    run(LiveApi(), a.out, today, a.days, now, a.save, a.remote, a.branch, a.push)


if __name__ == "__main__":
    main()
