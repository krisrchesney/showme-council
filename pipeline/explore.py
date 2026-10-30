"""The explorer site (T-21): a browsable static site built from the city's own records, mobile first. No templates, no build step.

Everything on it is one of two kinds, and every page says which:
  computed from the city's records (code): meetings, counts, dates, actions, how many times an item was held, topics, links.
  AI-written, checked: the plain-language summaries of a meeting and the short item descriptions. They appear only when they
  passed the code checks and a second AI's check (pipeline/verify.py, pipeline/labels.py).

Inputs: the cached history (scripts/backfill_rows.py), published summaries (data/published), optional labels files and the
topic accuracy file (scripts/topic_sample.py). No people are ranked, scored or profiled: no page looks at who voted how.
"""

import datetime
import html
import json
import os
import re
import statistics

from pipeline import members
from pipeline.compare import action_kind, build_index, classify_meeting
from pipeline.topics import DESCRIPTIONS, NAMES, TOPICS, short_title, topic_list

REPO = "https://github.com/krisrchesney/showme-council"
DATA_CREDIT = "Data: City of Kansas City, Missouri, published through Legistar."
NOTICE = ("Unofficial. Summaries are written by AI and checked against the source text by a second AI and by code. "
          "Always confirm with the official record linked on each page. Not affiliated with any city.")
BURN_IN_DAYS = 120
MIN_FOLD_N = 8
FOLD_BELOW = 0.5

CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#5f5e59;--line:#dedbd2;--accent:#1f5f8b;--ok:#2a7348;--bad:#a3412f;--card:#fff;--chip:#eef3f7}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe6;--muted:#a8a69e;--line:#38372f;--accent:#82bbe0;--ok:#7cc79a;--bad:#e08b78;--card:#1e1e1c;--chip:#232b31}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}
a{color:var(--accent)}a:focus-visible,button:focus-visible,input:focus-visible,summary:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.skip{position:absolute;left:-999px}.skip:focus{left:8px;top:8px;background:var(--card);padding:6px 10px;z-index:20}
nav.top{position:sticky;top:0;z-index:10;background:var(--bg);border-bottom:1px solid var(--line)}
nav.top .in{max-width:1080px;margin:0 auto;padding:0 12px;display:flex;align-items:center;gap:4px;overflow-x:auto;white-space:nowrap}
nav.top b{margin-right:8px}nav.top a{padding:12px 8px;text-decoration:none;color:var(--fg);font-size:.95rem}nav.top a[aria-current=page]{border-bottom:3px solid var(--accent)}
main{max-width:1080px;margin:0 auto;padding:16px 16px 56px}
h1{font-size:1.5rem;line-height:1.25;margin:.3em 0 .2em}h2{font-size:1.15rem;margin:1.6em 0 .4em}h3{font-size:1rem;margin:1.2em 0 .3em}
.crumbs{font-size:.88rem;color:var(--muted);margin:2px 0 6px}.muted{color:var(--muted);font-size:.9rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0}
.card.k{border-left:4px solid var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}.grid .card{margin:0}
.grid a.tile{display:block;text-decoration:none;color:var(--fg)}.tile b{display:block}.tile span{font-size:.85rem;color:var(--muted)}
.badge{display:inline-block;font-size:.72rem;border:1px solid var(--line);border-radius:99px;padding:0 8px;margin-right:6px;white-space:nowrap}
.badge.code{color:var(--ok)}.badge.ai{color:var(--muted)}
.chip{display:inline-block;font-size:.78rem;background:var(--chip);border-radius:6px;padding:1px 7px;margin:2px 4px 2px 0;text-decoration:none}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}table{border-collapse:collapse;width:100%;font-size:.92rem}
td,th{border-bottom:1px solid var(--line);padding:6px 6px;text-align:left;vertical-align:top}.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
blockquote{margin:6px 0;padding:4px 10px;border-left:3px solid var(--line);color:var(--muted);font-size:.92rem}
.search{display:flex;gap:8px;margin:10px 0}.search input{flex:1;font-size:16px;padding:10px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);min-width:0}
.search button{font-size:16px;padding:10px 14px;border:1px solid var(--accent);background:var(--accent);color:var(--bg);border-radius:8px}
ol.steps{list-style:none;padding:0;margin:8px 0;border-left:3px solid var(--line)}ol.steps li{padding:2px 0 10px 14px;position:relative}
ol.steps li:before{content:"";position:absolute;left:-8px;top:8px;width:11px;height:11px;border-radius:50%;background:var(--accent)}
ol.steps li.hold:before{background:var(--bad)}.row{padding:8px 0;border-bottom:1px solid var(--line)}.row:last-child{border:0}
.big{font-size:1.6rem;font-weight:650;line-height:1.1}.stats{display:flex;flex-wrap:wrap;gap:16px}.stats div{min-width:84px}
svg.chart{width:100%;height:auto;display:block}svg.chart text{fill:var(--muted);font-size:11px}svg.chart .bar{fill:var(--accent)}
footer{max-width:1080px;margin:0 auto;padding:0 16px 48px;font-size:.84rem;color:var(--muted)}
"""

CSS += """
main p,main li{max-width:75ch}
.cols{display:block}.split{display:block}.two{display:block}
.tile{transition:border-color .15s}.tile:hover{border-color:var(--accent)}
@media (min-width:900px){
 main{padding:28px 28px 72px}h1{font-size:2rem}.big{font-size:2rem}
 nav.top .in{padding:0 28px}nav.top a{padding:14px 12px}
 .cols{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:36px;align-items:start}
 .split{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:36px;align-items:start}
 .two{display:grid;grid-template-columns:1fr 1fr;gap:28px}
 .grid{grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px}.grid.compact{grid-template-columns:1fr 1fr}
 .split .facts>summary{display:none}
}
@media (min-width:1280px){main,footer,nav.top .in{max-width:1180px}}
"""
NAV = [("index.html", "Latest"), ("meetings.html", "Meetings"), ("topics.html", "Topics"), ("search.html", "Search"),
       ("trends.html", "Trends"), ("about.html", "How it works")]


def e(s):
    return html.escape(str(s if s is not None else ""))


def pct(x):
    return "n/a" if x is None else f"{round(100 * x)}%"


def plural(n, one, many=None):
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def badge_code(text="from the city's records"):
    return f"<span class='badge code'>{e(text)}</span>"


def badge_ai(text="AI-written, checked"):
    return f"<span class='badge ai'>{e(text)}</span>"


def slug(topic):
    return topic.replace("_", "-")


OPEN_WIDE = "<script>if(window.matchMedia&&matchMedia('(min-width:900px)').matches){document.querySelectorAll('details.facts').forEach(function(d){d.open=true})}</script>"


def member_safe(d):
    """A second line of defence for published summaries: a sentence or fact that names a council member is shown only if the run that
    wrote it verified it against the roll call (pipeline/members.py marked it). Anything older or unmarked is left out."""
    names = members.full_roster()
    claims = [c for c in d["claims"] if not members.mentions(c.get("statement", ""), names) or c.get("members_verified")]
    keep = {c["id"] for c in claims}
    sentences = [x for x in d["sentences"] if not members.mentions(x.get("text", ""), names) or x.get("members_verified")]
    sentences = [dict(x, claim_ids=[c for c in x["claim_ids"] if c in keep]) for x in sentences]
    return dict(d, claims=claims, sentences=sentences)


class Site:
    """Collects pages, then writes them. `prefix` is the relative path back to the site root for the page being built."""

    def __init__(self, built_at, records_through):
        self.pages = {"style.css": CSS}
        self.built_at, self.records_through = built_at, records_through

    def page(self, path, title, body, active=None, head_extra="", script=""):
        depth = path.count("/")
        up = "../" * depth
        nav = "".join(f"<a href='{up}{href}'{' aria-current=\"page\"' if href == active else ''}>{label}</a>" for href, label in NAV)
        foot = (f"<footer><p>{e(NOTICE)}</p><p>{e(DATA_CREDIT)} Records through {e(self.records_through)}; "
                f"site built {e(self.built_at)}. Something wrong? <a href='{REPO}/issues'>Send a correction</a>. "
                f"<a href='{up}about.html'>How this works and how accurate it is</a>.</p></footer>")
        self.pages[path] = (
            f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>{e(title)} | showme-council</title>"
            f"<link rel='stylesheet' href='{up}style.css'>{head_extra}</head><body><a class='skip' href='#main'>Skip to content</a>"
            f"<nav class='top' aria-label='Main'><div class='in'><b>showme-council</b>{nav}</div></nav>"
            f"<main id='main'>{body}</main>{foot}{script}</body></html>")

    def write(self, out):
        for path, text in self.pages.items():
            full = os.path.join(out, *path.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)


# ---------------------------------------------------------------------------------------------------------------- the data model
def plain_step(action, passed, council):
    """The city's action wording in plain words. The city's own wording is always shown next to it."""
    kind = action_kind(action)
    a = (action or "").strip()
    if kind == "held":
        return "Held"
    if kind == "re_referred":
        return "Sent back to a committee"
    if kind == "referred":
        return "Referred to a committee"
    if kind == "received":
        return "Received and filed"
    if kind == "introduced":
        return "Introduced"
    if kind == "decided":
        if passed == "Fail" or re.search(r"\bfail", a, re.I):
            return "Failed"
        if re.search(r"adv and do pass|^do pass", a, re.I) and not council:
            return "Advanced by the committee"
        if re.search(r"adv and do pass", a, re.I):
            return "Advanced to a vote"
        return "Adopted" if re.search(r"adopt", a, re.I) else "Passed"
    if kind == "advance_motion":
        return "Moved ahead"
    return a or "Listed"


def build_model(events, rows):
    """Everything the pages need, from the cached history. Pure code."""
    idx = build_index(rows, events)
    ev = {x["event_id"]: x for x in events}
    meetings = []
    for x in sorted(events, key=lambda x: (x["date"], x["event_id"])):
        if x["body"] == "Council" and x["event_id"] in idx["by_event"]:
            c = classify_meeting(x["event_id"], rows, events, idx)
            meetings.append({"event": x, "result": c})
    matters = {}
    for mf, mrows in idx["by_matter"].items():
        steps = {}
        for r in mrows:
            x = ev.get(r["event_id"])
            if not x:
                continue
            s = steps.setdefault(r["event_id"], {"event_id": r["event_id"], "date": x["date"], "body": x["body"], "actions": []})
            if r["action"]:
                s["actions"].append((r["action"], r["passed"]))
        ordered = sorted(steps.values(), key=lambda s: (s["date"], s["event_id"]))
        latest = max(mrows, key=lambda r: (ev[r["event_id"]]["date"], r["event_id"]) if r["event_id"] in ev else ("", 0))
        first = mrows[0]
        held = sum(1 for s in ordered if any(action_kind(a) == "held" for a, _ in s["actions"]))
        matters[mf] = {"file": mf, "title": latest["title"] or first["title"] or "", "type": first["matter_type"] or latest["matter_type"],
                       "matter_id": first.get("matter_id"), "matter_guid": first.get("matter_guid"), "steps": ordered, "held": held,
                       "first": ordered[0]["date"] if ordered else None, "last": ordered[-1]["date"] if ordered else None}
    return {"idx": idx, "ev": ev, "meetings": meetings, "matters": matters}


def status_of(m):
    """Where the item stands, from its last step. Plain wording, city's data only."""
    for s in reversed(m["steps"]):
        council = s["body"] == "Council"
        for action, passed in reversed(s["actions"]):
            label = plain_step(action, passed, council)
            if label in ("Passed", "Adopted", "Failed") and council:
                return f"{label} on {s['date']}", "done"
            if label == "Held":
                return f"Held on {s['date']}", "held"
            if label in ("Received and filed",):
                return f"Received and filed on {s['date']}", "done"
            if label in ("Advanced by the committee", "Advanced to a vote"):
                return f"Advanced on {s['date']}", "open"
            if label in ("Referred to a committee", "Sent back to a committee", "Introduced"):
                return f"{label} on {s['date']}", "open"
    return "Listed", "open"


def legistar_link(m):
    if m.get("matter_id") and m.get("matter_guid"):
        return f"https://kansascity.legistar.com/LegislationDetail.aspx?ID={m['matter_id']}&GUID={m['matter_guid']}"
    return None


def shown_topics(title, folded):
    t = [x for x in topic_list(title) if x not in folded]
    return t or ["other"]


def accuracy_from_sample(res):
    """What the site shows about topic accuracy, from a fresh topic_sample.py result. Two numbers per topic:
    found: of the sampled items a model gave this as the main topic, how many the rules list under it (do the rules miss it?)
    lead:  of the sampled items the rules lead with this topic, how many the model gave it as the main topic."""
    rows = res["rows"]
    per = {}
    for r in rows:
        m = per.setdefault(r["model"], {"model_n": 0, "found": 0, "lead_n": 0, "lead_agree": 0})
        m["model_n"] += 1
        m["found"] += r["model"] in r["rules"]
    for r in rows:
        m = per.setdefault(r["rule"], {"model_n": 0, "found": 0, "lead_n": 0, "lead_agree": 0})
        m["lead_n"] += 1
        m["lead_agree"] += r["model"] == r["rule"]
    for m in per.values():
        m["found_rate"] = round(m["found"] / m["model_n"], 3) if m["model_n"] else None
        m["lead_rate"] = round(m["lead_agree"] / m["lead_n"], 3) if m["lead_n"] else None
    return {"n": res["n"], "rate": res["rate"], "primary_rate": res.get("primary_rate"), "per_topic": per,
            "usage": res.get("usage"), "seed": res.get("sample_seed")}


def folded_topics(accuracy):
    """Topics whose measured accuracy is too weak (or too thinly sampled to tell) are folded into Other, and the site says so."""
    out = {}
    for t, v in ((accuracy or {}).get("per_topic") or {}).items():
        if t == "other":
            continue
        if v["lead_n"] >= MIN_FOLD_N and v["lead_rate"] is not None and v["lead_rate"] < 0.3:
            out[t] = f"a model agreed it was the lead topic for only {pct(v['lead_rate'])} of {v['lead_n']} sampled items"
        elif v["model_n"] < MIN_FOLD_N and v["lead_n"] < MIN_FOLD_N:
            out[t] = f"too few sampled items ({v['model_n']}) to measure"
        elif v["model_n"] >= MIN_FOLD_N and v["found_rate"] is not None and v["found_rate"] < FOLD_BELOW + 0.1:
            out[t] = f"the rules found only {pct(v['found_rate'])} of the {v['model_n']} sampled items a model put here"
    return out


# ---------------------------------------------------------------------------------------------------------------- charts
def bars(values, title, desc, fmt=lambda v: f"{v:,}", width=360, height=190):
    """A bar chart as inline SVG with a text equivalent. values: [(label, number or None)]."""
    vals = [v for _, v in values if v is not None]
    if not vals:
        return "<p class='muted'>Not enough data.</p>"
    top = max(vals) or 1
    n = len(values)
    gap = 6
    bw = max(8, (width - 20 - gap * (n - 1)) / n)
    parts = []
    for i, (label, v) in enumerate(values):
        x = 10 + i * (bw + gap)
        if v is not None:
            h = (height - 50) * v / top
            parts.append(f"<rect class='bar' x='{x:.1f}' y='{height - 28 - h:.1f}' width='{bw:.1f}' height='{max(h, 1):.1f}' rx='2'/>"
                         f"<text x='{x + bw / 2:.1f}' y='{height - 32 - h:.1f}' text-anchor='middle'>{e(fmt(v))}</text>")
        parts.append(f"<text x='{x + bw / 2:.1f}' y='{height - 10}' text-anchor='middle'>{e(label)}</text>")
    rows = "".join(f"<tr><td>{e(l)}</td><td class='n'>{'n/a' if v is None else e(fmt(v))}</td></tr>" for l, v in values)
    return (f"<svg class='chart' viewBox='0 0 {width} {height}' role='img' aria-label='{e(title)}. {e(desc)}'>"
            f"<title>{e(title)}</title>{''.join(parts)}</svg>"
            f"<details><summary class='muted'>Show the numbers</summary><div class='scroll'><table><tr><th>{e('Period')}</th>"
            f"<th class='n'>{e(title)}</th></tr>{rows}</table></div></details>")


# ---------------------------------------------------------------------------------------------------------------- page pieces
def chips(file_topics, folded):
    return "".join(f"<a class='chip' href='../topic/{slug(t)}.html'>{e(NAMES[t])}</a>" for t in file_topics)


_BUILT = None


def item_link(m, up):
    """The item's page here if this build has one; otherwise the city's own record of it (so a trimmed build has no dead links)."""
    if _BUILT is None or m["file"] in _BUILT:
        return f"{up}matter/{m['file']}.html", False
    return legistar_link(m), True


def matter_row(m, folded, up, labels, extra=""):
    lab = labels.get(m["file"])
    desc = (f"{badge_ai()}<i>{e(lab['label'])}</i>" if lab and lab.get("shown") else e(short_title(m["title"], 200)))
    status, _ = status_of(m)
    tp = "".join(f"<span class='chip'>{e(NAMES[t])}</span>" for t in shown_topics(m["title"], folded))
    href, ext = item_link(m, up)
    num = (f"<a href='{e(href)}'><b>{e(m['file'])}</b></a>" + (" <span class='muted'>(city page)</span>" if ext else "")) if href else f"<b>{e(m['file'])}</b>"
    return (f"<div class='row'>{num} "
            f"<span class='muted'>{e(m['type'] or '')}</span><br>{desc}<br><span class='muted'>{e(status)}"
            f"{f' &middot; held {m['held']} time' + ('s' if m['held'] != 1 else '') if m['held'] else ''}</span>{extra}<br>{tp}</div>")


def counts_block(counts, total):
    decided = counts.get("carried_through", 0) + counts.get("advanced_on_floor", 0) + counts.get("added", 0)
    cell = lambda n, t: f"<div><span class='big'>{n}</span><br><span class='muted'>{e(t)}</span></div>"
    return (f"<div class='stats'>{cell(total, 'items on the agenda')}{cell(decided, 'decided')}"
            f"{cell(counts.get('deferred', 0), 'held or sent back')}{cell(counts.get('introduced', 0), 'newly introduced')}</div>")


# ---------------------------------------------------------------------------------------------------------------- the pages
def build_explorer(history_dir, out_dir, docs=None, metrics=None, labels=None, accuracy=None, built_at=None, load_history=None, trim=True, scheduled=False):
    from pipeline.compare import load_history as _lh
    events, rows = (load_history or _lh)(history_dir)
    model = build_model(events, rows)
    ev, meetings, matters = model["ev"], model["meetings"], model["matters"]
    labels, docs, metrics = labels or {}, docs or [], metrics or []
    folded = folded_topics(accuracy)
    records_through = max(x["date"] for x in events)
    built_at = built_at or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    site = Site(built_at, records_through)
    doc_by_event = {}
    for d in [member_safe(x) for x in docs]:
        mm = re.match(r"kc-(\d+)-", d["meta"]["doc_id"])
        if mm:
            doc_by_event[int(mm.group(1))] = d

    # ---- per-matter topics, restricted to matters that reached a Council agenda
    council_matters = {}
    for mt in meetings:
        for x in mt["result"]["matters"]:
            council_matters[x["matter_file"]] = True
    topic_of_matter = {f: shown_topics(matters[f]["title"], folded) for f in council_matters if f in matters}
    # a trimmed build writes pages for the items people are most likely to open: those at the latest meetings, those held
    # again and again right now, and those with an AI description. Everything else links to the city's own record.
    keep = {f for f in council_matters if f in matters}
    if trim:
        keep = set()
        for mt in meetings[-6:]:
            keep |= {y["matter_file"] for y in mt["result"]["matters"]}
        keep |= {f for f in council_matters if f in matters and matters[f]["held"] >= 2 and status_of(matters[f])[1] == "held"}
        keep |= {f for f in labels if f in matters}
        keep &= set(matters)
    global _BUILT
    _BUILT = keep if trim else None
    by_topic = {t: [matters[f] for f, ts in topic_of_matter.items() if t in ts] for t in TOPICS}

    # ---- matter pages
    for f in sorted(keep):
        m = matters.get(f)
        if not m:
            continue
        lab = labels.get(f)
        status, _ = status_of(m)
        steps = []
        for s in m["steps"]:
            council = s["body"] == "Council"
            acts = "; ".join(f"{plain_step(a, p, council)} <span class='muted'>({e(a)})</span>" for a, p in s["actions"]) or "Listed on the agenda"
            hold = " class='hold'" if any(action_kind(a) == "held" for a, _ in s["actions"]) else ""
            link = ev[s["event_id"]].get("site_url")
            where = f"<a href='{e(link)}'>{e(s['body'])}</a>" if link else e(s["body"])
            steps.append(f"<li{hold}><b>{e(s['date'])}</b> &middot; {where}<br>{acts}</li>")
        tp = "".join(f"<a class='chip' href='../topic/{slug(t)}.html'>{e(NAMES[t])}</a>" for t in topic_of_matter[f])
        official = legistar_link(m)
        desc = (f"<p>{badge_ai()}{e(lab['label'])}</p><p class='muted'>Official title: {e(short_title(m['title'], 600))}</p>"
                if lab and lab.get("shown") else f"<p>{e(short_title(m['title'], 600))}</p>")
        body = (f"<div class='crumbs'><a href='../index.html'>Home</a> &rsaquo; <a href='../search.html'>Items</a> &rsaquo; {e(f)}</div>"
                f"<h1>{e(m['type'] or 'Item')} {e(f)}</h1>{desc}<p>{tp}</p>"
                f"<div class='card k'>{badge_code()}<b>{e(status)}</b>"
                + (f"<br>Held {plural(m['held'], 'time')} before it moved." if m["held"] else "")
                + (f"<br><a href='{e(official)}'>The city's record of this item, with its votes</a>" if official else "") + "</div>"
                f"<h2>Its path through the Council and its committees {badge_code()}</h2><ol class='steps'>{''.join(steps)}</ol>"
                f"<p class='muted'>Each date links to the city's page for that meeting. The wording in brackets is the city's own.</p>")
        site.page(f"matter/{f}.html", f"{m['type'] or 'Item'} {f}", body)

    # ---- meeting pages
    meeting_rows = []
    for mt in meetings:
        x, res = mt["event"], mt["result"]
        d = doc_by_event.get(x["event_id"])
        links = []
        for key, label in (("site_url", "the city's meeting page"), ("agenda_file", "agenda (PDF)"), ("minutes_file", "minutes (PDF)")):
            if x.get(key):
                links.append(f"<a href='{e(x[key])}'>{label}</a>")
        summary = ""
        if d:
            claim_no = {c["id"]: i for i, c in enumerate(d["claims"], 1)}
            sents = "".join(f"<p>{e(s['text'])}" + "".join(
                f"<sup><a href='#{e(c)}'>[{claim_no[c]}]</a></sup>" for c in s["claim_ids"] if c in claim_no) + "</p>" for s in d["sentences"])
            cards = "".join(
                f"<div class='card' id='{e(c['id'])}'><b>[{claim_no[c['id']]}]</b> {e(c['statement'])}<blockquote>&ldquo;{e(c['quote'])}&rdquo;</blockquote>"
                f"<span class='muted'>Page {e(c['page'])} of the <a href='{e(d['meta']['pdf_url'])}'>official minutes</a></span></div>"
                for c in d["claims"])
            r = d["report"]
            summary = (f"<div class='split'><div><h2>What happened {badge_ai()}</h2>{sents}"
                       f"<div class='card muted'>{r['claims_accepted']} of {r['claims_extracted']} extracted facts passed the check; the rest are not shown. "
                       f"These facts cover {r['coverage']['covered']} of the {r['coverage']['voted']} items the Council voted on. "
                       f"Each [number] jumps to the sentence in the official minutes it came from.</div>"
                       f"</div><div><h2>Facts and their sources</h2><details class='facts'><summary>Show the {len(d['claims'])} facts</summary>{cards}</details></div></div>")
        else:
            reason = ("The minutes for this meeting are not posted yet." if not x.get("minutes_file")
                      else "No AI summary has been written for this meeting yet.")
            summary = (f"<h2>What happened</h2><p class='muted'>{reason} The list below is built from the city's item records alone, "
                       f"so it has no summary sentences.</p>")
        counts = res["counts"]
        groups = []
        order = [("carried_through", "Decided as planned"), ("advanced_on_floor", "Moved ahead at the meeting"), ("added", "Added at the meeting"),
                 ("deferred", "Held or sent back"), ("introduced", "Newly introduced"), ("receive_and_file", "Received and filed"),
                 ("agenda_no_minutes", "On the agenda, no minutes row"), ("other", "Other")]
        for key, title in order:
            ms = [matters[y["matter_file"]] for y in res["matters"] if y["class"] == key and y["matter_file"] in matters]
            if ms:
                ms.sort(key=lambda m: -m["held"])
                groups.append(f"<h3>{e(title)} ({len(ms)})</h3><div class='card'>" + "".join(
                    matter_row(m, folded, "../", labels) for m in ms) + "</div>")
        note = (f"<div class='card muted'><b>What &ldquo;planned&rdquo; means.</b> The city keeps one agenda version for a meeting, the clerk's "
                f"<i>{e(x.get('agenda_status') or '')}</i> docket, last published {e(str(x.get('agenda_published') or '')[:16])} UTC. "
                f"So &ldquo;planned&rdquo; is that final docket, not necessarily the original plan. This page shows what the records say and does not judge it.</div>")
        body = (f"<div class='crumbs'><a href='../index.html'>Home</a> &rsaquo; <a href='../meetings.html'>Meetings</a> &rsaquo; {e(x['date'])}</div>"
                f"<h1>City Council, {e(x['date'])}</h1><p class='muted'>{' &middot; '.join(links)}</p>"
                f"<div class='card k'>{badge_code()}{counts_block(counts, res['matter_count'])}</div>{summary}"
                f"<h2>The agenda, item by item {badge_code()}</h2>{note}{''.join(groups)}")
        site.page(f"meeting/{x['event_id']}.html", f"Council {x['date']}", body, script=OPEN_WIDE if d else "")
        meeting_rows.append((x, res, d))

    # ---- meetings list
    years = {}
    for x, res, d in sorted(meeting_rows, key=lambda t: (t[0]["date"], t[0]["event_id"]), reverse=True):
        years.setdefault(x["date"][:4], []).append((x, res, d))
    lst = []
    for y, items in years.items():
        rws = "".join(f"<tr><td><a href='meeting/{x['event_id']}.html'>{e(x['date'])}</a></td><td class='n'>{res['matter_count']}</td>"
                      f"<td class='n'>{res['counts'].get('deferred', 0)}</td><td>{'AI summary' if d else ('records only' if x.get('minutes_file') else 'agenda only')}</td></tr>"
                      for x, res, d in items)
        lst.append(f"<h2>{e(y)}</h2><div class='scroll'><table><tr><th>Meeting</th><th class='n'>Items</th><th class='n'>Held</th><th>On this site</th></tr>{rws}</table></div>")
    n_sum = len(doc_by_event)
    site.page("meetings.html", "Meetings", (
        f"<h1>City Council meetings</h1><p class='muted'>{len(meeting_rows)} meetings, {meeting_rows[-1][0]['date'] if False else min(x['date'] for x, _, _ in meeting_rows)} to "
        f"{records_through}. {n_sum} {'has' if n_sum == 1 else 'have'} an AI-written summary so far; the rest show the city's own item records "
        f"(what was on the agenda, what happened to each item). {badge_code()}</p>{''.join(lst)}"), active="meetings.html")

    # ---- topics
    held_now = sorted([m for m in matters.values() if m["file"] in council_matters and status_of(m)[1] == "held"], key=lambda m: -m["held"])
    year_now = records_through[:4]
    tiles = []
    for t in TOPICS:
        ms = by_topic[t]
        if t in folded or not ms or t == "other":
            continue
        recent = sum(1 for m in ms if m["last"] and m["last"] >= f"{int(year_now) - 1}{records_through[4:]}")
        tiles.append(f"<a class='tile card' href='topic/{slug(t)}.html'><b>{e(NAMES[t])}</b><span>{plural(len(ms), 'item')} &middot; {recent:,} active in the last year</span></a>")
    for t in TOPICS:
        if t in folded or not by_topic[t] or t == "other":
            continue
        ms = by_topic[t]
        yr = {}
        for m in ms:
            if m["first"]:
                yr[m["first"][:4]] = yr.get(m["first"][:4], 0) + 1
        chart = bars([(y, yr[y]) for y in sorted(yr)], f"{NAMES[t]}: new items per year",
                     "Number of items first seen on a Council agenda in each year; the first and last years are partial.")
        acc = ((accuracy or {}).get("per_topic") or {}).get(t)
        acc_line = (f"<p class='muted'>Topics come from keyword rules on the official title (code), so this lists items that mention the subject. "
                    f"On a fresh sample of {accuracy['n']} titles, the rules found {pct(acc['found_rate'])} of the {acc['model_n']} items a model "
                    f"called mainly about this, and a model agreed on the lead topic for {pct(acc['lead_rate'])} of the {acc['lead_n']} items the rules led with it for. "
                    f"Items can have more than one topic.</p>" if acc and acc['model_n'] else "")
        held = sorted(ms, key=lambda m: -m["held"])[:8]
        recent = sorted(ms, key=lambda m: (m["last"] or "", m["file"]), reverse=True)[:25]
        body = (f"<div class='crumbs'><a href='../index.html'>Home</a> &rsaquo; <a href='../topics.html'>Topics</a> &rsaquo; {e(NAMES[t])}</div>"
                f"<h1>{e(NAMES[t])}</h1><p>{e(DESCRIPTIONS[t])}. {plural(len(ms), 'item')} since {min(m['first'] for m in ms if m['first'])}. {badge_code()}</p>"
                f"<h2>New items per year</h2>{chart}{acc_line}"
                f"<h2>Held the most times</h2><div class='card'>{''.join(matter_row(m, folded, '../', labels) for m in held if m['held'])}</div>"
                f"<h2>Most recent activity</h2><div class='card'>{''.join(matter_row(m, folded, '../', labels) for m in recent)}</div>")
        site.page(f"topic/{slug(t)}.html", NAMES[t], body)
    fold_note = ""
    if folded:
        fold_note = ("<div class='card muted'><b>Topics left out.</b> These are shown under Other because the keyword rules for them were not reliable enough: " +
                     "; ".join(f"{e(NAMES[t])} ({e(why)})" for t, why in folded.items()) + ".</div>")
    if by_topic["other"]:
        t = "other"
        ms = by_topic[t]
        recent = sorted(ms, key=lambda m: (m["last"] or "", m["file"]), reverse=True)[:25]
        site.page("topic/other.html", "Other", f"<div class='crumbs'><a href='../index.html'>Home</a> &rsaquo; <a href='../topics.html'>Topics</a> &rsaquo; Other</div>"
                  f"<h1>Other</h1><p>Items no topic rule matched, plus items whose topic was too unreliable to show. {plural(len(ms), 'item')}.</p>"
                  f"<div class='card'>{''.join(matter_row(m, folded, '../', labels) for m in recent)}</div>")
        tiles.append(f"<a class='tile card' href='topic/other.html'><b>Other</b><span>{plural(len(ms), 'item')}</span></a>")
    site.page("topics.html", "Topics", (
        f"<h1>Topics</h1><p class='muted'>Every Council item, sorted by what it is about. An item can be in more than one topic, so the counts add up to "
        f"more than the number of items. Topics come from keyword rules on the official title {badge_code('code')} and their accuracy is measured on the "
        f"<a href='about.html'>how it works</a> page.</p><div class='grid'>{''.join(tiles)}</div>{fold_note}"), active="topics.html")

    # ---- search
    index = [[f, short_title(matters[f]["title"], 140), "|".join(NAMES[t] for t in topic_of_matter[f]), matters[f]["last"], status_of(matters[f])[0],
              item_link(matters[f], "")[0] or ""] for f in sorted(topic_of_matter) if f in matters]
    site.pages["search.json"] = json.dumps(index, separators=(",", ":"))
    script = """<script>
(function(){var q=document.getElementById('q'),out=document.getElementById('out'),data=null;
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function run(){if(!data)return;var t=q.value.toLowerCase().split(/\\s+/).filter(Boolean);if(!t.length){out.innerHTML='<p class="muted">Type an item number (like 260445), a word from a title, or a topic.</p>';return}
var hits=[];for(var i=0;i<data.length&&hits.length<60;i++){var d=data[i],s=(d[0]+' '+d[1]+' '+d[2]).toLowerCase();if(t.every(function(w){return s.indexOf(w)>-1}))hits.push(d)}
out.innerHTML=hits.length?hits.map(function(d){return '<div class="row">'+(d[5]?'<a href="'+esc(d[5])+'"><b>'+esc(d[0])+'</b></a>'+(d[5].indexOf('http')===0?' <span class="muted">(city page)</span>':''):'<b>'+esc(d[0])+'</b>')+'<br>'+esc(d[1])+'<br><span class="muted">'+esc(d[4])+' &middot; '+esc(d[2]).split('|').join(', ')+'</span></div>'}).join(''):'<p class="muted">Nothing matched.</p>'}
var p=new URLSearchParams(location.search).get('q');if(p)q.value=p;
fetch('search.json').then(function(r){return r.json()}).then(function(j){data=j;run()}).catch(function(){out.innerHTML='<p class="muted">Search could not load.</p>'});
q.addEventListener('input',run)})();
</script>"""
    site.page("search.html", "Search", (
        f"<h1>Search items</h1><form class='search' role='search' onsubmit='return false'><input id='q' type='search' aria-label='Search' "
        f"placeholder='Item number, a word, or a topic' autocomplete='off'></form><div id='out'><noscript>Search needs JavaScript. "
        f"You can still browse by <a href='topics.html'>topic</a> or <a href='meetings.html'>meeting</a>.</noscript></div>"
        f"<p class='muted'>Searches the {len(index):,} items that reached a Council agenda.</p>"), active="search.html", script=script)

    # ---- trends
    latest_with_min = [m for m in meeting_rows if m[0].get("minutes_file")]
    data_start = min(x["date"] for x in events)
    burn = (datetime.date.fromisoformat(data_start) + datetime.timedelta(days=BURN_IN_DAYS)).isoformat()
    by_year = {}
    for x, res, d in meeting_rows:
        yb = by_year.setdefault(x["date"][:4], {"meetings": 0, "items": 0, "decided": 0, "deferred": 0, "days": []})
        yb["meetings"] += 1
        for y in res["matters"]:
            yb["items"] += 1
            yb["decided"] += y["class"] in ("carried_through", "advanced_on_floor", "added")
            yb["deferred"] += y["class"] == "deferred"
            m = matters.get(y["matter_file"])
            if (m and y["matter_type"] == "Ordinance" and y["first_seen"] >= burn and y["class"] in ("carried_through", "advanced_on_floor", "added")
                    and re.search(r"passed|adopt", y["final_action"] or "", re.I)):
                yb["days"].append(y["days_since_first_seen"])
    yrs = sorted(by_year)
    share = [(y, round(100 * by_year[y]["deferred"] / (by_year[y]["deferred"] + by_year[y]["decided"]))
              if (by_year[y]["deferred"] + by_year[y]["decided"]) else None) for y in yrs]
    med = [(y, statistics.median(by_year[y]["days"]) if len(by_year[y]["days"]) >= 5 else None) for y in yrs]
    site.page("trends.html", "Trends", (
        f"<h1>Trends over time</h1><p class='muted'>Counted by code from the city's item records for {len(meeting_rows)} Council meetings. {badge_code()} "
        f"This page counts; it does not judge the Council. The city has changed how it records steps over the years, and {year_now} is a partial year, so compare across years with care.</p>"
        f"<div class='two'><div><h2>Items held or sent back, as a share of items held or decided</h2>"
        + bars(share, "Percent of held-or-decided items that were held", "Per year, held or sent back items divided by held plus decided items.",
               fmt=lambda v: f"{v}%")
        + f"</div><div><h2>Typical days from first appearance to passage (ordinances)</h2><p class='muted'>Median, only for ordinances first seen at least {BURN_IN_DAYS} days after the data starts ({data_start}), and only years with at least 5 such ordinances.</p>"
        + bars(med, "Median days to passage", "Per year, the median number of days between an ordinance's first appearance and the meeting where it passed.",
               fmt=lambda v: f"{v:g}")
        + f"</div></div><h2>Items per year</h2>" + bars([(y, by_year[y]["items"]) for y in yrs], "Items on Council agendas", "Per year, items on Council agendas, counted once per meeting."))
        , active="trends.html")

    # ---- about / accuracy
    tot_x = sum(x["claims_extracted"] for x in metrics)
    tot_a = sum(x["claims_accepted"] for x in metrics)
    reasons = {}
    for x in metrics:
        for k, v in x.get("reject_reasons", {}).items():
            reasons[k] = reasons.get(k, 0) + v
    cov = [x["coverage"] for x in metrics if x.get("coverage")]
    can = [x["canary"] for x in metrics if x.get("canary")]
    fact = ""
    if tot_x:
        fact = (f"<p>Across {len(metrics)} summarized meeting{'s' if len(metrics) != 1 else ''} so far, {tot_a} of {tot_x} extracted facts passed ({pct(tot_a / tot_x)}). "
                + (f"The summaries cover {sum(c['covered'] for c in cov)} of {sum(c['voted'] for c in cov)} recorded votes. " if cov else "")
                + (f"In a planted-error test the fact-checker caught {sum(c['checker_caught'] for c in can)} of {sum(c['total'] for c in can)} deliberately false facts. " if can else "")
                + "</p>" + (f"<div class='scroll'><table><tr><th>Why facts were rejected</th><th class='n'>Count</th></tr>"
                            + "".join(f"<tr><td>{e(k)}</td><td class='n'>{v}</td></tr>" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])) + "</table></div>" if reasons else ""))
    pl = (accuracy or {}).get("per_topic") or {}
    acc_rows = "".join(f"<tr><td>{e(NAMES[t])}</td><td class='n'>{pct(v['found_rate'])} ({v['model_n']})</td><td class='n'>{pct(v['lead_rate'])} ({v['lead_n']})</td>"
                       f"<td>{'shown' if t not in folded else 'folded into Other'}</td></tr>"
                       for t, v in sorted(pl.items(), key=lambda kv: -(kv[1]["lead_rate"] or 0)) if t != "other")
    topic_acc = ""
    if accuracy:
        topic_acc = (f"<p>I asked a model to tag {accuracy['n']} titles that the rules had not been tuned on, and compared. The model's one main topic was "
                     f"among the rules' topics for the item {pct(accuracy['rate'])} of the time, and the same as the rules' lead topic {pct(accuracy.get('primary_rate'))} of the time. "
                     f"A model's tag is not the truth either, so this measures agreement, not correctness. Per topic: <b>Found</b> is how many of the items a model "
                     f"put under the topic the rules also list there (number sampled in brackets); <b>Lead</b> is how often a model agrees when the rules lead with that topic.</p>"
                     f"<div class='scroll'><table><tr><th>Topic</th><th class='n'>Found</th><th class='n'>Lead</th><th>On this site</th></tr>{acc_rows}</table></div>")
    site.page("about.html", "How it works", (
        f"<h1>How this works, and how far to trust it</h1>"
        f"<h2>Where it comes from</h2><p>Every fact starts in the City of Kansas City's own records: the Legistar item data and the posted minutes and agenda PDFs. {DATA_CREDIT} "
        f"A job reads them ({'it runs every night' if scheduled else 'run by hand so far; a nightly schedule is planned'}); a model drafts plain-language facts; a second model and code check each fact against the quote it came from. "
        f"Only facts that pass are shown, and each links to the page of the official document.</p>"
        f"<h2>Two kinds of content</h2><p>{badge_code()} counts, dates, votes outcomes, how often an item was held, topics and links are computed by code from the city's data. "
        f"{badge_ai()} the meeting summaries and short item descriptions are written by a model and shown only after the checks above.</p>"
        f"<h2>Fact-checker results</h2>{fact or '<p class="muted">No meeting has been summarized yet.</p>'}"
        f"<h2>Topic accuracy</h2>{topic_acc or '<p class="muted">Not measured yet.</p>'}{fold_note}"
        f"<h2>Coverage</h2><p>{len(meetings)} Council meetings from {min(x['date'] for x, _, _ in meeting_rows)} to {records_through} have item records here. "
        f"{n_sum} {'has' if n_sum == 1 else 'have'} an AI-written summary. Everything else is the city's data, organized.</p>"
        f"<h2>Known limits</h2><ul><li>The city republishes an agenda as a &ldquo;Final-Revised&rdquo; docket after the meeting starts, so &ldquo;planned&rdquo; means that final docket, not always the original plan.</li>"
        f"<li>Keyword topics are imperfect, and an item can be in several. Topics that measured poorly are folded into Other.</li>"
        f"<li>The way the city records steps has changed over the years; compare across years with care.</li>"
        f"<li>Votes: this site links to the city's roll calls and does not show or compare how individual council members voted.</li>"
        f"<li>Models can still be wrong in ways the checks miss. Confirm anything important in the official record.</li></ul>"
        f"<h2>Corrections</h2><p>Found a mistake? <a href='{REPO}/issues'>Open an issue</a> with the page and what is wrong. The code and the checks are public: <a href='{REPO}'>the repository</a>.</p>"),
        active="how-it-works")

    # ---- home
    last = latest_with_min[-1] if latest_with_min else (meeting_rows[-1] if meeting_rows else None)
    newest = meeting_rows[-1] if meeting_rows else None
    home = ["<h1>What Kansas City Council did</h1><p>Every Council item and meeting since "
            f"{data_start[:4]}, from the city's own records, with plain-language summaries that are fact-checked. "
            f"{badge_code()}{badge_ai()}<a href='about.html'>What the badges mean</a></p>",
            "<form class='search' role='search' action='search.html'><input name='q' type='search' aria-label='Search items' placeholder='Search an item number, a word or a topic'>"
            "<button type='submit'>Search</button></form>"]
    left, right = [], []
    if last:
        x, res, d = last
        headline = (f"<p>{badge_ai()}</p>" + "".join(f"<p>{e(t['text'])}</p>" for t in d["sentences"][:3])) if d else "<p class='muted'>No AI summary yet for this meeting; the counts below are from the city's records.</p>"
        left.append(f"<h2>Latest meeting with minutes: {e(x['date'])}</h2><div class='card k'>{headline}{counts_block(res['counts'], res['matter_count'])}"
                    f"<p><a href='meeting/{x['event_id']}.html'>See everything that happened</a></p></div>")
    if newest and newest is not last:
        x, res, _ = newest
        left.append(f"<p class='muted'>The agenda for {e(x['date'])} ({plural(res['matter_count'], 'item')}) is posted; minutes are not yet. "
                    f"<a href='meeting/{x['event_id']}.html'>See the agenda</a>.</p>")
    wl = [m for m in held_now if m["held"] >= 3][:6]
    if wl:
        left.append("<h2>Held again and again</h2><p class='muted'>Items whose latest step is a hold, with the most holds so far. "
                    f"{badge_code()}</p><div class='card'>" + "".join(matter_row(m, folded, "", labels) for m in wl) + "</div>")
    right.append(f"<h2>Topics</h2><div class='grid compact'>{''.join(tiles[:6])}</div><p><a href='topics.html'>All topics</a></p>")
    recent = list(reversed(meeting_rows))[:6]
    right.append("<h2>Recent meetings</h2><div class='card'>" + "".join(
        f"<div class='row'><a href='meeting/{x['event_id']}.html'>{e(x['date'])}</a> <span class='muted'>&middot; {plural(res['matter_count'], 'item')}, "
        f"{res['counts'].get('deferred', 0)} held &middot; {'AI summary' if d else ('records only' if x.get('minutes_file') else 'agenda only')}</span></div>"
        for x, res, d in recent) + "</div><p><a href='meetings.html'>All meetings</a></p>")
    home.append(f"<div class='cols'><div>{''.join(left)}</div><div>{''.join(right)}</div></div>")
    site.page("index.html", "Latest", "".join(home), active="index.html")
    return site
