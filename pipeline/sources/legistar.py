"""Legistar Web API adapter (Kansas City now; Columbia is the same code with client="gocolumbiamo").

API: https://webapi.legistar.com/v1/<client>/...  JSON, no key, OData-style $filter.
Used endpoints:
    /events?$filter=EventDate ge datetime'...'      meetings, with agenda/minutes PDF links
    /events/<id>/eventitems                          agenda items: matter file, action, pass/fail
    /eventitems/<id>/votes                           roll call per member

The transport is swappable so tests run from tests/fixtures/<client>/ with no network.
"""

import json
import os
import urllib.parse

from pipeline import fetch, paths
from pipeline.pdftext import pdf_to_text
from pipeline.sources.base import DocRef, Source

BASE = "https://webapi.legistar.com/v1"

# Full Council plus the three standing committees: where votes and spending happen.
# Boards and commissions are skipped to keep nightly cost predictable (see DESIGN.md "Cost").
KC_BODIES = {
    "Council",
    "Finance, Governance and Public Safety Committee",
    "Neighborhood Planning and Development Committee",
    "Transportation, Infrastructure and Operations Committee",
}

ITEM_FIELDS = (
    "EventItemId", "EventItemAgendaSequence", "EventItemMatterFile", "EventItemMatterName",
    "EventItemMatterType", "EventItemTitle", "EventItemActionName", "EventItemPassedFlagName",
    "EventItemTally", "EventItemMover", "EventItemSeconder",
)


class LiveTransport:
    def __init__(self, client):
        self.base = f"{BASE}/{client}"

    def events(self, since, until):
        flt = f"EventDate ge datetime'{since}' and EventDate lt datetime'{until}'"
        q = urllib.parse.urlencode({"$filter": flt, "$orderby": "EventDate"})
        return fetch.get_json(f"{self.base}/events?{q}")

    def event_items(self, event_id):
        return fetch.get_json(f"{self.base}/events/{event_id}/eventitems?AgendaNote=1&MinutesNote=1")

    def votes(self, item_id):
        return fetch.get_json(f"{self.base}/eventitems/{item_id}/votes")

    def pdf_text(self, url):
        return pdf_to_text(fetch.get_bytes(url))


class FixtureTransport:
    """Reads the cached files in tests/fixtures/<client>/ (made by scripts/refresh_fixture.py)."""

    def __init__(self, client, root=None):
        self.dir = os.path.join(root or paths.FIXTURES, client)

    def _load(self, name):
        with open(os.path.join(self.dir, name), encoding="utf-8") as f:
            return json.load(f)

    def events(self, since, until):
        return [e for e in self._load("events.json") if since <= e["EventDate"][:10] < until]

    def event_items(self, event_id):
        return self._load(f"eventitems_{event_id}.json")

    def votes(self, item_id):
        votes = self._load("votes.json")
        return votes.get(str(item_id), [])

    def pdf_text(self, url):
        name = os.path.basename(urllib.parse.urlparse(url).path).rsplit(".", 1)[0] + ".txt"
        with open(os.path.join(self.dir, name), encoding="utf-8") as f:
            return f.read()


class LegistarSource(Source):
    def __init__(self, client="kansascity", prefix="kc", bodies=KC_BODIES, transport=None):
        self.name = client
        self.prefix = prefix
        self.bodies = bodies
        self.t = transport or LiveTransport(client)

    def list_new(self, since, until, seen):
        refs = []
        for e in self.t.events(since, until):
            if e.get("EventBodyName", "").strip() not in self.bodies:
                continue
            # Minutes are the record of what happened; an agenda is only what was planned.
            # When minutes appear later, they become a second document for the same meeting.
            for kind, url in (("minutes", e.get("EventMinutesFile")), ("agenda", e.get("EventAgendaFile"))):
                if not url:
                    continue
                doc_id = f"{self.prefix}-{e['EventId']}-{kind}"
                if doc_id in seen:
                    continue
                refs.append(DocRef(
                    doc_id=doc_id, source=self.name, body=e["EventBodyName"].strip(),
                    date=e["EventDate"][:10], kind=kind, pdf_url=url,
                    detail_url=e.get("EventInSiteURL") or "",
                    extra={"event_id": e["EventId"]},
                ))
        return refs

    def fetch(self, ref):
        text = self.t.pdf_text(ref.pdf_url)
        items = []
        for it in self.t.event_items(ref.extra["event_id"]):
            row = {k: it.get(k) for k in ITEM_FIELDS}
            # Roll calls only exist once the meeting has happened, so only for minutes.
            if ref.kind == "minutes" and it.get("EventItemPassedFlagName"):
                row["votes"] = [
                    {"name": v.get("VotePersonName"), "vote": v.get("VoteValueName")}
                    for v in self.t.votes(it["EventItemId"])
                ]
            items.append(row)
        return text, items
