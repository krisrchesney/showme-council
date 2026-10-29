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


def page(title, body):
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{e(title)}</title><style>{CSS}</style></head><body><main>{body}"
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
    stats = (f"<div class='card'><b>Fact-checker so far:</b> {tot_a} of {tot_x} extracted facts passed "
             f"({pct(tot_a / tot_x if tot_x else None)}) across {len(metrics)} documents."
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
