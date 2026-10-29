"""Pipeline entry point.

    python -m pipeline.run ingest  --since 2026-10-20 [--until ...] [--limit 1] [--fixture]
    python -m pipeline.run estimate DOC_ID                 # expected cost, no model call
    python -m pipeline.run process DOC_ID [--stub DIR] [--max-usd 1.50]
    python -m pipeline.run nightly [--days 3] [--max-docs 4] [--max-usd 4.00] [--fixture] [--stub DIR]
    python -m pipeline.run build-site

Stages hand off through files (see DESIGN.md):
    ingest      -> data/raw/<doc>/{meta.json, source.txt, api_items.json}
    extractor   -> data/work/<doc>/facts.json
    code checks -> data/work/<doc>/checks.json
    summarizer  -> data/work/<doc>/summary.json
    fact-checker-> data/work/<doc>/verdicts.json
    decide      -> data/work/<doc>/report.json, data/published/<doc>.json, data/metrics.jsonl
    build-site  -> site/
"""

import argparse
import datetime
import json
import os
import sys

from pipeline import paths
from pipeline.agents import run_agent
from pipeline.site import build_site
from pipeline.sources import get_source
from pipeline.sources.base import read_raw, write_raw
from pipeline.verify import code_checks, decide, split_pages

# $ per million tokens, from the claude-api reference (cached 2026-10-06). Used only for estimates;
# real runs record the cost Claude Code reports.
PRICES = {"claude-opus-5-5": (4.00, 20.00), "claude-sonnet-5-5": (2.00, 10.00), "claude-haiku-5-5": (0.10, 0.50)}
CALL_OVERHEAD_TOKENS = 6000   # Claude Code's own system prompt + agent instructions, per call
MAX_TRIES = 3


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def load_state():
    if os.path.exists(paths.STATE):
        with open(paths.STATE, encoding="utf-8") as f:
            return json.load(f)
    return {"docs": {}}


def seen_ids(state):
    return {k for k, v in state["docs"].items() if v["status"] == "ok" or v.get("tries", 0) >= MAX_TRIES}


def ingest(source_name, since, until, limit=None, fixture=False):
    src = get_source(source_name, fixture=fixture)
    refs = src.list_new(since, until, seen_ids(load_state()))
    refs.sort(key=lambda r: (r.date, r.kind != "minutes"))
    out = []
    for ref in refs[:limit]:
        try:
            text, items = src.fetch(ref)
        except Exception as e:  # a scanned or missing PDF skips one document, not the night
            _mark(ref.doc_id, "error", f"ingest: {e}")
            print(f"skipped {ref.doc_id}: {e}", file=sys.stderr)
            continue
        write_raw(ref, text, items)
        out.append(ref.doc_id)
        print(f"ingested {ref.doc_id}: {len(text):,} chars, {len(items)} API items")
    return out


def estimate(doc_id, model="claude-opus-5-5"):
    """Rough cost of one document before spending anything. ~3.5 chars per token for this text."""
    _, text, _ = read_raw(doc_id)
    src_tok = len(text) / 3.5
    claims_tok = 6000                     # ~40 claims as JSON
    stages = {   # (input tokens, output tokens incl. thinking)
        "extractor": (CALL_OVERHEAD_TOKENS + src_tok, 9000),
        "summarizer": (CALL_OVERHEAD_TOKENS + claims_tok * 0.6, 2500),
        "fact-checker": (CALL_OVERHEAD_TOKENS + src_tok + claims_tok * 1.4, 6000),
    }
    pin, pout = PRICES[model]
    rows = {k: round((i * pin + o * pout) / 1e6, 3) for k, (i, o) in stages.items()}
    rows["total"] = round(sum(rows.values()), 2)
    rows["source_tokens"] = int(src_tok)
    return rows


def process(doc_id, stub_dir=None, max_usd=1.50):
    meta, text, api_items = read_raw(doc_id)
    pages = split_pages(text)
    wd = paths.work_dir(doc_id)
    spent, costs = 0.0, {}

    def call(name, schema, payload):
        nonlocal spent
        left = max_usd - spent
        if left <= 0.05:
            raise RuntimeError(f"budget ${max_usd:.2f} used up before {name}")
        out, usage = run_agent(name, schema, payload, wd, left, stub_dir=stub_dir)
        spent += usage.get("cost_usd") or 0.0
        costs[name] = usage
        _dump(os.path.join(wd, f"{name}.usage.json"), usage)
        return out

    # 1. extractor: source -> claims
    facts = call("extractor", "extractor", {"meta": meta, "source": text})
    claims, ids = [], set()
    for c in facts.get("claims", []):
        if c["id"] in ids:            # duplicate ids would make verdicts ambiguous
            c = dict(c, id=f"{c['id']}_{len(claims)}")
        ids.add(c["id"])
        claims.append(c)
    _dump(os.path.join(wd, "facts.json"), {"claims": claims})

    # 2. code checks (free, deterministic)
    checks = {c["id"]: code_checks(c, pages, meta, api_items) for c in claims}
    _dump(os.path.join(wd, "checks.json"), checks)

    # 3. summarizer: claims only, never the source
    slim = [{k: c[k] for k in ("id", "type", "statement", "matter_file", "outcome", "amount_usd", "date")} for c in claims]
    summary = call("summarizer", "summarizer", {"meta": meta, "claims": slim}) if claims else {"headline": "", "sentences": []}
    _dump(os.path.join(wd, "summary.json"), summary)

    # 4. fact-checker: source + claims (+ code results) + sentences; headline goes last
    sentences = [{"index": i, "text": s["text"], "claim_ids": s["claim_ids"]} for i, s in enumerate(summary["sentences"])]
    cited = sorted({cid for s in summary["sentences"] for cid in s["claim_ids"]})
    sentences.append({"index": len(sentences), "text": summary.get("headline", ""), "claim_ids": cited, "is_headline": True})
    verdicts = call("fact-checker", "fact_checker", {
        "meta": meta, "source": text,
        "claims": [dict(c, code_checks={k: checks[c["id"]][k] for k in ("quote_match", "numbers_missing_from_quote", "api")}) for c in claims],
        "sentences": sentences,
    }) if claims else {"claims": [], "sentences": []}
    _dump(os.path.join(wd, "verdicts.json"), verdicts)

    # 5. decide + publish
    result = decide(meta, claims, checks, summary, verdicts)
    report = dict(result["report"], at=_now(), stub=bool(stub_dir),
                  cost_usd=round(spent, 4), cost_by_stage={k: v.get("cost_usd") for k, v in costs.items()})
    _dump(os.path.join(wd, "report.json"), dict(result, report=report))
    _dump(os.path.join(paths.PUBLISHED, f"{doc_id}.json"), {
        "meta": meta, "headline": result["headline"], "generated_at": report["at"],
        "sentences": [{"text": s["text"], "claim_ids": s["claim_ids"]} for s in result["published_sentences"]],
        "claims": [{k: c[k] for k in ("id", "type", "statement", "quote", "page", "matter_file", "outcome", "amount_usd")}
                   | {"code_checks": {"api": c["code_checks"]["api"], "quote_match": c["code_checks"]["quote_match"]}}
                   for c in result["accepted"]],
        "report": report,
    })
    os.makedirs(paths.DATA, exist_ok=True)
    with open(paths.METRICS, "a", encoding="utf-8") as f:
        f.write(json.dumps(report) + "\n")
    return report


def _mark(doc_id, status, error=None):
    state = load_state()
    prev = state["docs"].get(doc_id, {})
    state["docs"][doc_id] = {"status": status, "at": _now(), "tries": prev.get("tries", 0) + 1,
                             **({"error": error[:300]} if error else {})}
    _dump(paths.STATE, state)


def nightly(source_name, days, max_docs, max_usd, fixture=False, stub_dir=None, today=None):
    today = today or datetime.date.today()
    since = (today - datetime.timedelta(days=days)).isoformat()
    until = (today + datetime.timedelta(days=1)).isoformat()
    doc_ids = ingest(source_name, since, until, limit=max_docs, fixture=fixture)
    spent = 0.0
    for doc_id in doc_ids:
        if spent >= max_usd:
            print(f"nightly budget ${max_usd:.2f} reached; {doc_id} waits for tomorrow")
            break
        try:
            rep = process(doc_id, stub_dir=stub_dir, max_usd=min(1.50, max_usd - spent))
            spent += rep["cost_usd"]
            _mark(doc_id, "ok")
            print(f"{doc_id}: {rep['claims_accepted']}/{rep['claims_extracted']} claims passed, ${rep['cost_usd']:.2f}")
        except Exception as e:  # one bad PDF must not stop the night
            _mark(doc_id, "error", str(e))
            print(f"{doc_id}: FAILED {e}", file=sys.stderr)
    out, n = build_site()
    print(f"site: {n} documents -> {out}; spent ${spent:.2f}")
    return spent


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m pipeline.run")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest")
    p.add_argument("--source", default="kansascity")
    p.add_argument("--since", required=True)
    p.add_argument("--until", default=(datetime.date.today() + datetime.timedelta(days=1)).isoformat())
    p.add_argument("--limit", type=int)
    p.add_argument("--fixture", action="store_true")
    p = sub.add_parser("estimate")
    p.add_argument("doc_id")
    p.add_argument("--model", default="claude-opus-5-5", choices=sorted(PRICES))
    p = sub.add_parser("process")
    p.add_argument("doc_id")
    p.add_argument("--stub")
    p.add_argument("--max-usd", type=float, default=1.50)
    p = sub.add_parser("nightly")
    p.add_argument("--source", default="kansascity")
    p.add_argument("--days", type=int, default=3)
    p.add_argument("--max-docs", type=int, default=4)
    p.add_argument("--max-usd", type=float, default=4.00)
    p.add_argument("--fixture", action="store_true")
    p.add_argument("--stub")
    sub.add_parser("build-site")
    a = ap.parse_args(argv)

    if a.cmd == "ingest":
        ingest(a.source, a.since, a.until, a.limit, a.fixture)
    elif a.cmd == "estimate":
        print(json.dumps(estimate(a.doc_id, a.model), indent=2))
    elif a.cmd == "process":
        rep = process(a.doc_id, stub_dir=a.stub, max_usd=a.max_usd)
        _mark(a.doc_id, "ok")
        print(json.dumps(rep, indent=2))
    elif a.cmd == "nightly":
        nightly(a.source, a.days, a.max_docs, a.max_usd, a.fixture, a.stub)
    elif a.cmd == "build-site":
        out, n = build_site()
        print(f"{n} documents -> {out}")


if __name__ == "__main__":
    main()
