"""What every source adapter must provide. Adding a city = one new module that fills this in.

A source turns "what's new since last night" into documents on disk:

    data/raw/<doc_id>/meta.json       who/what/when + links back to the original
    data/raw/<doc_id>/source.txt      the document text, with "=== page N ===" markers
    data/raw/<doc_id>/api_items.json  structured records the source already publishes
                                      (agenda items, outcomes, roll calls), or [] if none

Everything downstream reads only these three files, so the agents never know
which city or platform a document came from.
"""

import json
import os
from dataclasses import asdict, dataclass, field

from pipeline import paths


@dataclass
class DocRef:
    doc_id: str          # stable and filesystem-safe, e.g. "kc-19561-minutes"
    source: str          # adapter name, e.g. "kansascity"
    body: str            # "Council", "Finance, Governance and Public Safety Committee", ...
    date: str            # meeting date, YYYY-MM-DD
    kind: str            # "minutes" or "agenda"
    pdf_url: str
    detail_url: str = ""
    extra: dict = field(default_factory=dict)


class Source:
    name = "base"

    def list_new(self, since, until, seen):
        """Return DocRefs for documents dated in [since, until) whose doc_id is not in `seen`."""
        raise NotImplementedError

    def fetch(self, ref):
        """Return (source_text, api_items) for one DocRef."""
        raise NotImplementedError


def write_raw(ref, text, api_items):
    d = paths.raw_dir(ref.doc_id)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(asdict(ref), f, indent=2)
    with open(os.path.join(d, "source.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(d, "api_items.json"), "w", encoding="utf-8") as f:
        json.dump(api_items, f, indent=2)
    return d


def read_raw(doc_id):
    d = paths.raw_dir(doc_id)
    with open(os.path.join(d, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    with open(os.path.join(d, "source.txt"), encoding="utf-8") as f:
        text = f.read()
    with open(os.path.join(d, "api_items.json"), encoding="utf-8") as f:
        items = json.load(f)
    return meta, text, items
