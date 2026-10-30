"""Builds the static public site from data/published/*.json. No templates, no build step.

Only accepted claims and published sentences are in data/published, so nothing the
fact-checker rejected can reach the site. Each page shows its own pass/reject counts.
"""

import html
import json
import os

from pipeline import paths

CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6a65;--line:#e3e1da;--accent:#1f5f8b;--ok:#2f7d4f;--bad:#a3412f;--card:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe6;--muted:#a09e96;--line:#34332f;--accent:#7fb6dc;--ok:#7cc79a;--bad:#e08b78;--card:#1e1e1c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:760px;margin:0 auto;padding:24px 16px 64px}a{color:var(--accent)}
h1{font-size:1.6rem;margin:.2em 0}h2{font-size:1.15rem;margin:1.6em 0 .4em}
.muted{color:var(--muted);font-size:.9rem}.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 16px;margin:12px 0}
.pill{display:inline-block;font-size:.8rem;padding:1px 8px;border-radius:99px;border:1px solid var(--line);color:var(--muted)}
.ok{color:var(--ok)}.bad{color:var(--bad)}blockquote{margin:6px 0;padding:4px 10px;border-left:3px solid var(--line);color:var(--muted);font-size:.92rem}
sup a{text-decoration:none}table{border-collapse:collapse;width:100%;font-size:.92rem}td,th{border-bottom:1px solid var(--line);padding:6px 4px;text-align:left}
footer{margin-top:48px;font-size:.85rem;color:var(--muted)}
"""

FOOTER = ("Unofficial summaries written by AI and checked against the source text by a second AI "
          "and by code. Always confirm with the official record linked on each page. "
          "Source records: City of Kansas City, Missouri, published through Legistar. "
          "Not affiliated with any city.")


def e(s):
    return html.escape(str(s if s is not None else ""))


EXTRA_CSS = """
.ai{font-size:.72rem;border:1px solid var(--line);border-radius:99px;padding:0 7px;margin-right:6px;color:var(--muted)}
.code{font-size:.72rem;border:1px solid var(--line);border-radius:99px;padding:0 7px;margin-right:6px;color:var(--ok)}
.item{padding:10px 14px}.item .num{font-weight:600}.legend{border-left:4px solid var(--accent)}
table.counts td:first-child{width:62%}.n{font-variant-numeric:tabular-nums;text-align:right}
"""


def page(title, body, extra_css=""):
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{e(title)}</title><style>{CSS}{extra_css}</style></head><body><main>{body}"
            f"<footer>{e(FOOTER)}</footer></main></body></html>")


def pct(x):
    return "n/a" if x is None else f"{round(100 * x)}%"


def load_published():
    docs = []
    if os.path.isdir(paths.PUBLISHED):
        for name in sorted(os.listdir(paths.PUBLISHED)):
            if name.endswith(".json"):
                with open(os.path.join(paths.PUBLISHED, name), encoding="utf-8") as f:
                    docs.append(json.load(f))
    docs.sort(key=lambda d: (d["meta"]["date"], d["meta"]["doc_id"]), reverse=True)
    return docs


def doc_page(d):
    m, r = d["meta"], d["report"]
    claim_no = {c["id"]: i for i, c in enumerate(d["claims"], 1)}
    sents = []
    for s in d["sentences"]:
        refs = "".join(f"<sup><a href='#{e(cid)}'>[{claim_no[cid]}]</a></sup>" for cid in s["claim_ids"] if cid in claim_no)
        sents.append(f"<p>{e(s['text'])}{refs}</p>")
    claims = []
    for c in d["claims"]:
        claims.append(
            f"<div class='card' id='{e(c['id'])}'><b>[{claim_no[c['id']]}]</b> {e(c['statement'])}"
            f"<blockquote>&ldquo;{e(c['quote'])}&rdquo;</blockquote>"
            f"<span class='muted'>Page {e(c['page'])} of the <a href='{e(m['pdf_url'])}'>official {e(m['kind'])}</a>"
            f"{' &middot; matches the city&rsquo;s vote record' if c['code_checks']['api'] == 'agree' else ''}</span></div>")
    body = (
        f"<p class='muted'><a href='../index.html'>&larr; All meetings</a></p>"
        f"<span class='pill'>{e(m['body'])}</span> <span class='pill'>{e(m['kind'])}</span>"
        f"<h1>{e(d['headline'])}</h1><p class='muted'>{e(m['date'])}</p>"
        + ("".join(sents) or "<p class='muted'>No summary sentence passed the fact-check for this document.</p>")
        + f"<div class='card muted'>Fact-check: <b class='ok'>{r['claims_accepted']}</b> of {r['claims_extracted']} "
          f"extracted facts passed ({pct(r['claim_pass_rate'])}); {r['claims_rejected']} were rejected and are not shown. "
          f"{r['sentences_published']} of {r['sentences_written']} summary sentences passed. "
          + (f"These facts cover {r['coverage']['covered']} of the {r['coverage']['voted']} items the Council voted on. "
             if r.get("coverage") else "")
          + f"<a href='{e(m['detail_url'] or m['pdf_url'])}'>Official record</a></div>"
        + "<h2>Facts and their sources</h2>" + ("".join(claims) or "<p class='muted'>None passed.</p>"))
    return page(f"{d['headline']} | showme-council", body)


def index_page(docs, metrics):
    rows = []
    for d in docs:
        m, r = d["meta"], d["report"]
        rows.append(f"<div class='card'><span class='muted'>{e(m['date'])} &middot; {e(m['body'])} {e(m['kind'])}</span><br>"
                    f"<a href='doc/{e(m['doc_id'])}.html'><b>{e(d['headline'])}</b></a><br>"
                    f"<span class='muted'>{r['claims_accepted']} checked facts &middot; {pct(r['claim_pass_rate'])} of extracted facts passed</span></div>")
    tot_x = sum(x["claims_extracted"] for x in metrics)
    tot_a = sum(x["claims_accepted"] for x in metrics)
    reasons = {}
    for x in metrics:
        for k, v in x.get("reject_reasons", {}).items():
            reasons[k] = reasons.get(k, 0) + v
    rtable = "".join(f"<tr><td>{e(k)}</td><td>{v}</td></tr>" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]))
    cov = [x["coverage"] for x in metrics if x.get("coverage")]
    cov_v, cov_c = sum(c["voted"] for c in cov), sum(c["covered"] for c in cov)
    can = [x["canary"] for x in metrics if x.get("canary")]
    can_t, can_c = sum(c["total"] for c in can), sum(c["checker_caught"] for c in can)
    stats = (f"<div class='card'><b>Fact-checker so far:</b> {tot_a} of {tot_x} extracted facts passed "
             f"({pct(tot_a / tot_x if tot_x else None)}) across {len(metrics)} documents."
             + (f" <b>Planted-error test:</b> the fact-checker caught {can_c} of {can_t} deliberately false facts slipped into its input." if can_t else "")
             + (f" <b>Coverage:</b> {cov_c} of {cov_v} recorded votes have at least one checked fact ({pct(cov_c / cov_v)})." if cov_v else "")
             + (f"<table><tr><th>Why facts were rejected</th><th>Count</th></tr>{rtable}</table>" if rtable else "")
             + "</div>")
    body = ("<h1>What Kansas City Council decided</h1>"
            "<p class='muted'>Plain-language summaries of Council and committee records, updated nightly. "
            "Every fact links to the sentence in the official document it came from.</p>"
            + stats + ("".join(rows) or "<p class='muted'>Nothing published yet.</p>"))
    return page("showme-council: Kansas City Council, checked", body)


def build_site(out_dir=None):
    out = out_dir or paths.SITE
    os.makedirs(os.path.join(out, "doc"), exist_ok=True)
    docs = load_published()
    metrics = []
    if os.path.exists(paths.METRICS):
        with open(paths.METRICS, encoding="utf-8") as f:
            metrics = [json.loads(line) for line in f if line.strip()]
    for d in docs:
        with open(os.path.join(out, "doc", f"{d['meta']['doc_id']}.html"), "w", encoding="utf-8") as f:
            f.write(doc_page(d))
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_page(docs, metrics))
    return out, len(docs)


# ---------------------------------------------------------------- planned vs happened (T-17, local preview only)
COMPARE_GROUPS = [
    ("carried_through", "Planned and decided", "On the agenda, and the minutes record a decision."),
    ("advanced_on_floor", "Moved ahead at the meeting", "On the agenda at an earlier step, then advanced and acted on the same day."),
    ("added", "Added at the meeting", "Not on the agenda; the minutes record action on it."),
    ("deferred", "Held or sent back", "Held on the docket or agenda, or referred back to a committee."),
    ("introduced", "Newly introduced", "First appearance, introduced or referred to a committee. Not yet a decision."),
    ("agenda_no_minutes", "On the agenda, no row in the minutes", "Listed on the agenda; the minutes have no row for it."),
    ("receive_and_file", "Received and filed", "Communications and notices. Not decisions."),
    ("other", "Other", "A final step this page does not classify."),
]


def _legistar_link(m):
    if m.get("matter_id") and m.get("matter_guid"):
        return f"https://kansascity.legistar.com/LegislationDetail.aspx?ID={m['matter_id']}&GUID={m['matter_guid']}"
    return None


def _compare_item(m, labels):
    lab = (labels or {}).get(m["matter_file"])
    link = _legistar_link(m)
    head = f"<span class='num'>{e(m['matter_file'])}</span>" + (f" <a href='{e(link)}'>official record</a>" if link else "")
    if lab and lab.get("shown"):
        desc = f"<span class='ai'>AI-written</span><i>{e(lab['label'])}</i>"
    else:
        t = m["title"]
        desc = f"<span class='muted'>Official title:</span> {e(t[:300])}{'&hellip;' if len(t) > 300 else ''}"
    steps = []
    if m.get("agenda_action"):
        steps.append(f"agenda row: {e(m['agenda_action'])}")
    if m["actions"]:
        steps.append("recorded: " + " &rarr; ".join(e(a) for a in m["actions"] if a))
    facts = " &middot; ".join(steps)
    hist = ""
    if m["held_before"]:
        hist = (f"<br><span class='muted'>Held {m['held_before']} time{'s' if m['held_before'] != 1 else ''} before: "
                f"{', '.join(e(d) for d in m['held_dates'])}. First seen {e(m['first_seen'])} "
                f"({m['days_since_first_seen']} days earlier).</span>")
    elif m["meetings_before"]:
        hist = f"<br><span class='muted'>Seen at {m['meetings_before']} earlier meeting(s); first seen {e(m['first_seen'])}.</span>"
    flag = ""
    if m.get("ordinance_decided_on_first_appearance"):
        flag = "<br><span class='muted'>An ordinance decided on the day it first appeared.</span>"
    return f"<div class='card item'>{head}<br>{desc}<br><span class='muted'>{facts}</span>{hist}{flag}</div>"


def compare_page(result, labels=None, links=None):
    """Planned versus recorded for one meeting, from pipeline.compare.classify_meeting(). Local preview: not part of the site build."""
    mt, links = result["meeting"], links or {}
    counts = result["counts"]
    legend = (
        "<div class='card legend muted'><b>What is from where.</b> "
        "<span class='code'>city's record</span> The groups, counts, dates, actions and the \"held N times\" lines are computed by code "
        "from the city's own item rows; nothing about them is written by a model. "
        "<span class='ai'>AI-written</span> The short description in italics is written by a model from the item's official title and "
        "shown only if code and a second AI check agree it says nothing the title doesn't. Where a description failed that check, or "
        "none was written, the official title is shown instead.</div>")
    note = (
        f"<div class='card muted'><b>What &ldquo;planned&rdquo; means.</b> The city keeps one agenda version, the clerk's "
        f"<i>{e(mt.get('agenda_status') or '')}</i> docket, last published {e(str(mt.get('agenda_published') or '')[:16])} UTC. "
        f"The minutes were published {e(str(mt.get('minutes_published') or '')[:16])} UTC. So &ldquo;planned&rdquo; here is that final "
        f"docket, not necessarily the original plan. This page shows what the city's records say and does not judge it.</div>")
    rows = "".join(f"<tr><td>{e(title)}<br><span class='muted'>{e(desc)}</span></td><td class='n'>{counts[k]}</td></tr>"
                   for k, title, desc in COMPARE_GROUPS if counts.get(k))
    table = (f"<table class='counts'><tr><th>What happened to the item</th><th class='n'>Items</th></tr>{rows}"
             f"<tr><td><b>All items</b></td><td class='n'><b>{result['matter_count']}</b></td></tr></table>")
    sections = []
    for key, title, desc in COMPARE_GROUPS:
        ms = [m for m in result["matters"] if m["class"] == key]
        if ms:
            if key == "deferred":
                ms.sort(key=lambda m: -m["held_before"])
            sections.append(f"<h2>{e(title)} ({len(ms)})</h2><p class='muted'>{e(desc)}</p>" + "".join(_compare_item(m, labels) for m in ms))
    ext = []
    if links.get("site_url"):
        ext.append(f"<a href='{e(links['site_url'])}'>meeting page</a>")
    if links.get("agenda_file"):
        ext.append(f"<a href='{e(links['agenda_file'])}'>agenda (PDF)</a>")
    if links.get("minutes_file"):
        ext.append(f"<a href='{e(links['minutes_file'])}'>minutes (PDF)</a>")
    body = (f"<h1>{e(mt['body'])}, {e(mt['date'])}: planned and what happened</h1>"
            f"<p class='muted'>Preview, not published. {' &middot; '.join(ext)}</p>"
            + legend + note + "<h2>At a glance</h2>" + table + "".join(sections))
    return page(f"{mt['body']} {mt['date']}: planned and what happened", body, EXTRA_CSS)


# ---------------------------------------------------------------- trends over time (T-19, local preview only)
TOPIC_NAMES = {"ceremonial": "Ceremonial", "bonds_financing": "Bonds and financing", "grants": "Grants", "budget_funds": "Budget and funds",
               "land_use": "Zoning and land use", "contracts": "Contracts", "streets_utilities": "Streets and utilities",
               "public_safety": "Public safety", "housing": "Housing", "parks_recreation": "Parks and recreation",
               "city_code": "City code and pay", "boards_appointments": "Boards and appointments", "other": "Other"}


def _pct(x):
    return "n/a" if x is None else f"{round(100 * x)}%"


def _days(m):
    return "n/a" if m["median_days_to_passage"] is None else f"{round(m['median_days_to_passage'])} (n={m['passage_n']})"


def _shade(x):
    if x is None:
        return ""
    return f" style='background:rgba(31,95,139,{min(0.55, x * 1.2):.2f})'"


def trends_page(t, accuracy=None):
    """Counts over time at the Council, from pipeline.trends.trend_tables(). Every number is computed by code from the city's rows."""
    if not t["meetings"]:
        return page("Council trends", "<h1>Council trends</h1><p class='muted'>No Council meetings in the data.</p>", EXTRA_CSS)
    acc_note = ("Topics are assigned by keyword rules (code). I checked them by asking a model to tag a sample of "
                f"{accuracy['n']} titles, balanced across topics: the rules agree with it on {_pct(accuracy['rate'])} of the sample, "
                f"and on about {_pct(accuracy.get('weighted_rate', accuracy['rate']))} across all items once each topic is weighted by how common it is. "
                "A model's tag is not the truth either, so treat the topic columns as a rough grouping."
                if accuracy else "Topics are assigned by keyword rules (code). Their accuracy has not been measured yet.")
    legend = (
        "<div class='card legend muted'><b>What is from where.</b> <span class='code'>city's record</span> Every number on this page is "
        "counted by code from the city's own item rows for Council meetings; no text on it is written by a model. "
        f"{e(acc_note)}</div>")
    defs = (
        "<div class='card muted'><b>How to read it.</b> <i>Items</i> are matters on a Council agenda, counted once per meeting. "
        "<i>Deferred share</i> is deferred items out of decided plus deferred (newly introduced items and communications are left out). "
        "<i>Held again</i> counts deferred items that had already been held at an earlier meeting. <i>Days to passage</i> is the median "
        f"from a matter's first row to the meeting where an ordinance passed, only for matters first seen after {e(t['burn_in_until'])} "
        "(a matter introduced before the data starts would look quicker than it was). A quarter with few items can swing a lot: "
        "look at the counts before the percentages. The way the city records steps has changed over the years, and the newest meeting's "
        "minutes may not be posted yet, so compare across years with care. This page does not judge the Council; it counts what "
        "the city's records show.</div>")
    qrows = "".join(
        f"<tr><td>{e(q)}</td><td class='n'>{m['meetings']}</td><td class='n'>{m['items']}</td><td class='n'>{m['decided']}</td>"
        f"<td class='n'>{m['deferred']}</td><td class='n'{_shade(m['deferred_share'])}>{_pct(m['deferred_share'])}</td>"
        f"<td class='n'>{m['held_again']}</td><td class='n'>{_days(m)}</td><td class='n'>{m['first_day_ordinances']}</td></tr>"
        for q, m in t["by_quarter"].items())
    quarter_table = ("<table><tr><th>Quarter</th><th class='n'>Meetings</th><th class='n'>Items</th><th class='n'>Decided</th>"
                     "<th class='n'>Deferred</th><th class='n'>Deferred share</th><th class='n'>Held again</th>"
                     "<th class='n'>Days to passage</th><th class='n'>Ordinances decided on first appearance</th></tr>" + qrows + "</table>")
    trows = "".join(
        f"<tr><td>{e(TOPIC_NAMES.get(k, k))}</td><td class='n'>{m['items']}</td><td class='n'>{m['deferred']}</td>"
        f"<td class='n'{_shade(m['deferred_share'])}>{_pct(m['deferred_share'])}</td><td class='n'>{m['held_again']}</td>"
        f"<td class='n'>{_days(m)}</td></tr>" for k, m in sorted(t["by_topic"].items(), key=lambda kv: -kv[1]["items"]) if m["items"])
    topic_table = ("<table><tr><th>Topic</th><th class='n'>Items</th><th class='n'>Deferred</th><th class='n'>Deferred share</th>"
                   "<th class='n'>Held again</th><th class='n'>Days to passage</th></tr>" + trows + "</table>")
    years = list(t["by_year_topic"])
    head = "".join(f"<th class='n'>{y}</th>" for y in years)
    yrows = ""
    for topic in t["topics"]:
        if not any(t["by_year_topic"][y][topic]["items"] for y in years):
            continue
        cells = "".join(
            f"<td class='n'{_shade(t['by_year_topic'][y][topic]['deferred_share'])}>"
            f"{_pct(t['by_year_topic'][y][topic]['deferred_share'])}<br><span class='muted'>of {t['by_year_topic'][y][topic]['decided'] + t['by_year_topic'][y][topic]['deferred']}</span></td>"
            for y in years)
        yrows += f"<tr><td>{e(TOPIC_NAMES.get(topic, topic))}</td>{cells}</tr>"
    year_table = f"<table><tr><th>Topic</th>{head}</tr>{yrows}</table>"
    other = " &middot; ".join(f"{y}: {_pct(v)}" for y, v in t["other_share_by_year"].items())
    body = (f"<h1>Council trends: what was decided and what was deferred</h1>"
            f"<p class='muted'>Preview, not published. {t['meetings']} Council meetings, {e(t['span'][0])} to {e(t['span'][1])}, {t['items']:,} items.</p>"
            + legend + defs + "<h2>Each quarter</h2>" + quarter_table
            + "<h2>By topic, all years</h2>" + topic_table
            + "<h2>Deferred share by topic and year</h2><p class='muted'>Shading shows the share; the small number is the count it is a share of.</p>" + year_table
            + f"<h2>How much the topic rules could not place</h2><p class='muted'>Share of items in the &ldquo;Other&rdquo; bucket, by year: {other}</p>")
    return page("Council trends", body, EXTRA_CSS)
