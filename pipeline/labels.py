"""Plain-language labels for agenda item titles (T-17). Model-written, and shown only if they pass the same checks facts do.

A label is a short description of what an item IS ("An ordinance to spend up to $1,100,000 on ..."). It is built so that the
checks that already guard facts can guard it too: the label is treated as a claim and the item's official title is its quote.

  code      every number in the label is in the title, the label never reads as a decision (the agenda guard),
            and the title really is in the source text
  checker   the fact-checker agent reads the label against the title and must say SUPPORTED

Both must pass. A label that fails either is not shown; the page shows the official title instead. Nothing here is verified by
anything else: the page says plainly that labels are AI-written.
"""

import re

from pipeline.agents import run_agent
from pipeline.verify import agenda_states_outcome, code_checks, split_pages

BATCH = 60
MAX_WORDS = 30     # the prompt asks for 25; a little slack before a label counts as too long


def _batches(items, n=BATCH):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _summarize(usages):
    tin = sum(u.get("tokens_in", 0) for u in usages)
    tout = sum(u.get("tokens_out", 0) for u in usages)
    return {"tokens_in": tin, "tokens_out": tout, "turns": sum(u.get("num_turns", 0) for u in usages),
            "seconds": round(sum(u.get("duration_s", 0.0) for u in usages), 1),
            "api_equiv_usd": round(sum(u.get("api_equiv_usd", 0.0) for u in usages), 4)}


def make_labels(meeting, matters, out_dir, loop_cap=1.5, runner=run_agent, model=None):
    """Labels for the matters of one meeting.

    Returns ({matter_file: {"label": str, "shown": bool, "why_not": [reasons]}}, usage dict).
    `runner` is run_agent (a real headless call) or a stand-in in tests."""
    meta = {"doc_id": f"labels-{meeting['event_id']}", "body": meeting["body"], "kind": "agenda", "date": meeting["date"]}
    titles = [{"matter_file": m["matter_file"], "title": m["title"]} for m in matters if m["title"]]
    usages, written = [], {}
    for batch in _batches(titles):
        out, usage = runner("labeler", "labeler", {"meeting": meta, "titles": batch}, out_dir, loop_cap, model=model)
        usages.append(usage)
        for item in out.get("labels", []):
            written[item["matter_file"]] = item["label"]

    by_file = {t["matter_file"]: t["title"] for t in titles}
    labels = {mf: {"label": lab, "shown": False, "why_not": []} for mf, lab in written.items() if mf in by_file}
    for mf in by_file:
        if mf not in labels:
            labels[mf] = {"label": "", "shown": False, "why_not": ["no_label_returned"]}

    source = "=== page 1 ===\n" + "\n".join(by_file.values())
    pages = split_pages(source)
    claims, checks = [], {}
    for n, (mf, entry) in enumerate(labels.items(), 1):
        if not entry["label"]:
            continue
        claim = {"id": f"l{n}", "type": "other", "statement": entry["label"], "quote": by_file[mf], "page": 1,
                 "matter_file": None, "outcome": None, "amount_usd": None, "date": None}
        ck = code_checks(claim, pages, meta, [])
        if len(entry["label"].split()) > MAX_WORDS:
            ck["reasons"].append("label_too_long")
        if agenda_states_outcome(claim, meta):          # the same guard that stops an agenda reading as a decision
            ck["reasons"].append("states_an_outcome")
        entry["why_not"] = [r for r in ck["reasons"] if r not in entry["why_not"]]
        entry["_id"] = claim["id"]
        claims.append(dict(claim, code_checks={k: ck[k] for k in ("quote_match", "numbers_missing_from_quote", "matter", "api")}))
        checks[claim["id"]] = mf

    verdicts = {}
    for batch in _batches(claims):
        out, usage = runner("fact-checker", "fact_checker", {"meta": meta, "source": source, "claims": batch, "sentences": []},
                            out_dir, loop_cap, model=model)
        usages.append(usage)
        for v in out.get("claims", []):
            verdicts[v["id"]] = v
    for entry in labels.values():
        cid = entry.pop("_id", None)
        if cid is None:
            continue
        v = verdicts.get(cid)
        if v is None:
            entry["why_not"].append("checker_missing")
        elif v["verdict"] != "SUPPORTED":
            entry["why_not"].append("checker_" + v["verdict"].lower())
        entry["shown"] = not entry["why_not"]
    return labels, _summarize(usages)
