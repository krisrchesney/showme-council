"""Pipeline entry point.

    python -m pipeline.run ingest  --since 2026-10-20 [--until ...] [--limit 1] [--fixture]
    python -m pipeline.run estimate DOC_ID                 # expected tokens, no model call
    python -m pipeline.run process DOC_ID [--stub DIR] [--loop-cap 1.50] [--model ID]
    python -m pipeline.run redecide DOC_ID                 # re-score saved agent output, no model call
    python -m pipeline.run nightly [--days 3] [--max-docs 4] [--loop-cap 4.00] [--fixture] [--stub DIR]
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
from pipeline.agents import AgentOutputError, find_claude, login_instructions, run_agent
from pipeline.site import build_site
from pipeline.sources import get_source
from pipeline.sources.base import read_raw, write_raw
from pipeline.verify import COVERAGE_MIN, COVERAGE_MIN_ITEMS, code_checks, coverage, decide, split_pages

# API-equivalent rates, USD per million tokens (claude-api reference, cached 2026-10-06). The pipeline
# runs on a Claude subscription, so nothing is billed per token. These only turn token counts into
# a common unit for comparing models and runs; real runs record what Claude Code estimates itself.
API_EQUIV_RATES = {"claude-opus-5-5": (4.00, 20.00), "claude-sonnet-5-5": (2.00, 10.00), "claude-haiku-5-5": (0.10, 0.50)}
DEFAULT_MODEL = "claude-sonnet-5-5"     # model policy: Sonnet by default (also each agent .md)
ESCALATION_MODEL = "claude-opus-5-5"    # only when the user reruns a document with --model
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
    # needs_model waits for the user to rerun with --model; retrying on the same model will not help
    return {k for k, v in state["docs"].items()
            if v["status"] in ("ok", "needs_model") or v.get("tries", 0) >= MAX_TRIES}


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


def estimate(doc_id, model=DEFAULT_MODEL):
    """Expected tokens for one document, before running anything. ~3.5 chars per token for this text.
    The API-equivalent figure is a unit for comparing models, not a charge."""
    _, text, _ = read_raw(doc_id)
    src_tok = len(text) / 3.5
    claims_tok = 6000                     # ~40 claims as JSON
    stages = {   # (input tokens, output tokens incl. thinking)
        "extractor": (CALL_OVERHEAD_TOKENS + src_tok, 9000),
        "summarizer": (CALL_OVERHEAD_TOKENS + claims_tok * 0.6, 2500),
        "fact-checker": (CALL_OVERHEAD_TOKENS + src_tok + claims_tok * 1.4, 6000),
    }
    rin, rout = API_EQUIV_RATES[model]
    by_stage = {k: {"tokens_in": int(i), "tokens_out": int(o), "api_equiv_usd": round((i * rin + o * rout) / 1e6, 3)}
                for k, (i, o) in stages.items()}
    return {
        "model": model,
        "tokens_in": sum(v["tokens_in"] for v in by_stage.values()),
        "tokens_out": sum(v["tokens_out"] for v in by_stage.values()),
        "calls": len(stages),
        "api_equiv_usd": round(sum(v["api_equiv_usd"] for v in by_stage.values()), 2),
        "note": "api_equiv_usd compares models; it is not a charge (runs use the subscription's plan usage)",
        "source_tokens": int(src_tok),
        "by_stage": by_stage,
    }


def _norm_usage(u):
    """One stage's usage in the current shape. Accepts files written before the usage rename."""
    raw = u.get("usage") or {}
    return {
        "tokens_in": u.get("tokens_in", (raw.get("input_tokens") or 0) + (raw.get("cache_creation_input_tokens") or 0)
                        + (raw.get("cache_read_input_tokens") or 0)),
        "tokens_out": u.get("tokens_out", raw.get("output_tokens") or 0),
        "turns": u.get("num_turns") or 0,
        "seconds": u.get("duration_s") or 0.0,
        "api_equiv_usd": u.get("api_equiv_usd", u.get("cost_usd")) or 0.0,
        "models": u.get("models") or sorted((u.get("model_usage") or {}).keys()),
    }


def summarize_usage(stages):
    """{stage: usage dict from run_agent} -> the `usage` block and `models` list stored in the report."""
    by = {k: _norm_usage(v) for k, v in stages.items()}
    total = {key: sum(v[key] for v in by.values()) for key in ("tokens_in", "tokens_out", "turns")}
    total["seconds"] = round(sum(v["seconds"] for v in by.values()), 1)
    total["api_equiv_usd"] = round(sum(v["api_equiv_usd"] for v in by.values()), 4)
    return {"usage": dict(total, by_stage=by),
            "models": sorted({m for v in by.values() for m in v["models"]})}


def _stage_usage_from_files(wd):
    out = {}
    for name in ("extractor", "summarizer", "fact-checker"):
        p = os.path.join(wd, f"{name}.usage.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                out[name] = json.load(f)
    return out


class NeedsStrongerModel(RuntimeError):
    """A stage failed in a way that looks like a model-capability problem. The pipeline never
    switches models by itself: it stops this document and tells the user to rerun it."""

    def __init__(self, why):
        super().__init__(f"this may need Opus: {why}. Rerun with: "
                         f"python -m pipeline.run process <doc> --model {ESCALATION_MODEL}")


MISSING_VERDICT_LIMIT = 0.10   # fact-checker skipped >10% of claims -> it could not handle the document


def process(doc_id, stub_dir=None, loop_cap=1.50, model=None):
    """Run one document through all stages. `loop_cap` is a runaway-loop tripwire in API-equivalent
    units (what Claude Code estimates the tokens would cost at API rates), not a spending limit."""
    meta, text, api_items = read_raw(doc_id)
    pages = split_pages(text)
    wd = paths.work_dir(doc_id)
    used, stages = 0.0, {}
    strong = (model or DEFAULT_MODEL) == ESCALATION_MODEL

    def call(name, schema, payload):
        nonlocal used
        left = loop_cap - used
        if left <= 0.05:
            raise RuntimeError(f"loop cap ({loop_cap:.2f} API-equivalent units) reached before {name}")
        try:
            out, usage = run_agent(name, schema, payload, wd, left, stub_dir=stub_dir, model=model)
        except AgentOutputError as e:
            if strong:
                raise
            raise NeedsStrongerModel(f"{name} did not return valid structured output ({e})") from e
        used += usage.get("api_equiv_usd") or 0.0
        stages[name] = usage
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
        "claims": [dict(c, code_checks={k: checks[c["id"]][k] for k in ("quote_match", "numbers_missing_from_quote", "matter", "api")}) for c in claims],
        "sentences": sentences,
    }) if claims else {"claims": [], "sentences": []}
    _dump(os.path.join(wd, "verdicts.json"), verdicts)
    judged = {v["id"] for v in verdicts.get("claims", [])}
    skipped = [c["id"] for c in claims if c["id"] not in judged]
    if claims and len(skipped) / len(claims) > MISSING_VERDICT_LIMIT and not strong:
        raise NeedsStrongerModel(f"fact-checker gave no verdict for {len(skipped)} of {len(claims)} claims")

    # Coverage stop (default model only, never for canned stub output): publishing a page that covers
    # a sliver of the meeting is worse than stopping and asking. The agents' files stay in data/work.
    if not stub_dir and not strong:
        cov = coverage(meta, api_items, decide(meta, claims, checks, summary, verdicts)["accepted"])
        if cov and cov["voted"] >= COVERAGE_MIN_ITEMS and cov["rate"] < COVERAGE_MIN:
            raise NeedsStrongerModel(f"only {cov['covered']} of {cov['voted']} voted items covered by an accepted fact "
                                     f"({round(100 * cov['rate'])}%, under the {round(100 * COVERAGE_MIN)}% floor)")

    # 5. decide + publish
    usage_meta = dict({"at": _now(), "stub": bool(stub_dir),
                       "auth": "api-key" if os.environ.get("SHOWME_BARE") == "1" else "subscription"},
                      **summarize_usage(stages))
    _dump(os.path.join(wd, "usage_meta.json"), usage_meta)
    return finalize(doc_id, meta, claims, checks, summary, verdicts, usage_meta)


def finalize(doc_id, meta, claims, checks, summary, verdicts, usage_meta):
    """decide() + write report, published JSON and the metrics line. Free; no model calls."""
    wd = paths.work_dir(doc_id)
    result = decide(meta, claims, checks, summary, verdicts)
    _, _, api_items = read_raw(doc_id)
    report = dict(result["report"], coverage=coverage(meta, api_items, result["accepted"]), **usage_meta)
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
    lines = []
    if os.path.exists(paths.METRICS):    # one line per document: a re-decide replaces its line
        with open(paths.METRICS, encoding="utf-8") as f:
            lines = [x for x in f if x.strip() and json.loads(x)["doc_id"] != doc_id]
    lines.append(json.dumps(report) + "\n")
    with open(paths.METRICS, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return report


def redecide(doc_id):
    """Re-run the free stages (code checks + decide) on saved agent outputs. For when verify.py
    changes: no model call, so the agents' outputs stay exactly as they were."""
    meta, text, api_items = read_raw(doc_id)
    pages = split_pages(text)
    wd = paths.work_dir(doc_id)

    def load(name):
        with open(os.path.join(wd, name), encoding="utf-8") as f:
            return json.load(f)
    claims = load("facts.json")["claims"]
    checks = {c["id"]: code_checks(c, pages, meta, api_items) for c in claims}
    _dump(os.path.join(wd, "checks.json"), checks)
    usage_meta = load("usage_meta.json") if os.path.exists(os.path.join(wd, "usage_meta.json")) else {}
    if "usage" not in usage_meta:     # run saved before the usage fields existed: rebuild from the stage files
        old = load("report.json")["report"]
        usage_meta = dict({k: old.get(k) for k in ("at", "stub")}, auth="subscription",
                          **summarize_usage(_stage_usage_from_files(wd)))
        _dump(os.path.join(wd, "usage_meta.json"), usage_meta)
    usage_meta = dict(usage_meta, redecided_at=_now())
    return finalize(doc_id, meta, claims, checks, load("summary.json"), load("verdicts.json"), usage_meta)


def report_markdown(doc_id):
    """A short markdown summary of one processed document: quality and usage (tokens, turns, time)."""
    wd = paths.work_dir(doc_id)
    with open(os.path.join(wd, "report.json"), encoding="utf-8") as f:
        full = json.load(f)
    with open(os.path.join(wd, "verdicts.json"), encoding="utf-8") as f:
        verdicts = json.load(f)["claims"]
    r, u = full["report"], full["report"]["usage"]
    cov = r.get("coverage")
    flags = sum(1 for v in verdicts if v["verdict"] != "SUPPORTED")
    contradicted = sum(1 for c in full["accepted"] if c["code_checks"]["api"] == "disagree")
    pct = lambda x: "n/a" if x is None else f"{round(100 * x)}%"
    lines = [
        f"### {doc_id}",
        f"- facts: {r['claims_extracted']} extracted, {r['claims_accepted']} passed ({pct(r['claim_pass_rate'])})",
        "- voted-item coverage: " + (f"{cov['covered']} of {cov['voted']} ({pct(cov['rate'])})" if cov else "n/a"),
        f"- accepted facts the city's record contradicts: {contradicted}",
        f"- fact-checker flags: {flags} of {len(verdicts)}",
        f"- summary sentences published: {r['sentences_published']} of {r['sentences_written']}",
        f"- models: {', '.join(r['models']) or 'none'}; auth: {r.get('auth')}",
        f"- usage: {u['tokens_in']:,} tokens in, {u['tokens_out']:,} out, {u['turns']} turns, {u['seconds']:.0f} s",
    ]
    for name, v in u["by_stage"].items():
        lines.append(f"  - {name}: {v['tokens_in']:,} in, {v['tokens_out']:,} out, {v['turns']} turns, {v['seconds']:.0f} s")
    if r.get("reject_reasons"):
        lines.append("- rejected because: " + ", ".join(f"{k} x{n}" for k, n in r["reject_reasons"].items()))
    return "\n".join(lines)


def _mark(doc_id, status, error=None):
    state = load_state()
    prev = state["docs"].get(doc_id, {})
    state["docs"][doc_id] = {"status": status, "at": _now(), "tries": prev.get("tries", 0) + 1,
                             **({"error": error[:300]} if error else {})}
    _dump(paths.STATE, state)


def nightly(source_name, days, max_docs, loop_cap, fixture=False, stub_dir=None, today=None):
    """One night. `loop_cap` bounds the night in API-equivalent units; it is a tripwire, not a budget."""
    today = today or datetime.date.today()
    since = (today - datetime.timedelta(days=days)).isoformat()
    until = (today + datetime.timedelta(days=1)).isoformat()
    doc_ids = ingest(source_name, since, until, limit=max_docs, fixture=fixture)
    used = 0.0
    tot = {"tokens_in": 0, "tokens_out": 0, "turns": 0, "seconds": 0.0}
    for doc_id in doc_ids:
        if used >= loop_cap:
            print(f"night loop cap reached; {doc_id} waits for tomorrow")
            break
        try:
            rep = process(doc_id, stub_dir=stub_dir, loop_cap=min(1.50, loop_cap - used))
            u = rep["usage"]
            used += u["api_equiv_usd"]
            for k in tot:
                tot[k] += u[k]
            _mark(doc_id, "ok")
            print(f"{doc_id}: {rep['claims_accepted']}/{rep['claims_extracted']} claims passed; "
                  f"{u['tokens_in']:,} tokens in, {u['tokens_out']:,} out, {u['turns']} turns, {u['seconds']:.0f}s")
        except NeedsStrongerModel as e:
            _mark(doc_id, "needs_model", str(e))
            print(f"{doc_id}: STOPPED, {e}", file=sys.stderr)
        except Exception as e:  # one bad PDF must not stop the night
            _mark(doc_id, "error", str(e))
            print(f"{doc_id}: FAILED {e}", file=sys.stderr)
    out, n = build_site()
    print(f"site: {n} documents -> {out}; night usage: {tot['tokens_in']:,} tokens in, {tot['tokens_out']:,} out, "
          f"{tot['turns']} turns, {tot['seconds']:.0f}s")
    return used


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
    p.add_argument("--model", default=DEFAULT_MODEL, choices=sorted(API_EQUIV_RATES))
    p = sub.add_parser("process")
    p.add_argument("doc_id")
    p.add_argument("--stub")
    p.add_argument("--loop-cap", type=float, default=1.50,
                   help="runaway-loop tripwire in API-equivalent units; not a spending limit")
    p.add_argument("--model", choices=sorted(API_EQUIV_RATES),
                   help="override every agent model for this document (e.g. after a may-need-Opus stop)")
    p = sub.add_parser("redecide")
    p.add_argument("doc_id")
    p = sub.add_parser("nightly")
    p.add_argument("--source", default="kansascity")
    p.add_argument("--days", type=int, default=3)
    p.add_argument("--max-docs", type=int, default=4)
    p.add_argument("--loop-cap", type=float, default=4.00,
                   help="runaway-loop tripwire for the whole night, in API-equivalent units; not a spending limit")
    p.add_argument("--fixture", action="store_true")
    p.add_argument("--stub")
    sub.add_parser("build-site")
    p = sub.add_parser("report", help="markdown summary of one processed document (quality + tokens, turns, time)")
    p.add_argument("doc_id")
    sub.add_parser("claude-path", help="show which claude CLI the pipeline will use, and the exact login command")
    a = ap.parse_args(argv)

    if a.cmd == "ingest":
        ingest(a.source, a.since, a.until, a.limit, a.fixture)
    elif a.cmd == "estimate":
        print(json.dumps(estimate(a.doc_id, a.model), indent=2))
    elif a.cmd == "process":
        try:
            rep = process(a.doc_id, stub_dir=a.stub, loop_cap=a.loop_cap, model=a.model)
        except NeedsStrongerModel as e:
            _mark(a.doc_id, "needs_model", str(e))
            sys.exit(str(e))
        _mark(a.doc_id, "ok")
        print(json.dumps(rep, indent=2))
    elif a.cmd == "redecide":
        print(json.dumps(redecide(a.doc_id), indent=2))
    elif a.cmd == "nightly":
        nightly(a.source, a.days, a.max_docs, a.loop_cap, a.fixture, a.stub)
    elif a.cmd == "report":
        print(report_markdown(a.doc_id))
    elif a.cmd == "claude-path":
        try:
            path, how = find_claude()
        except FileNotFoundError as e:
            sys.exit(str(e))
        print(f"claude CLI: {path}\n  found via: {how}")
        if how != "PATH":
            print("  (not on PATH, so use the full path when you run it yourself)")
        print(f"log in (PowerShell):\n  {login_instructions(path)}")
    elif a.cmd == "build-site":
        out, n = build_site()
        print(f"{n} documents -> {out}")


if __name__ == "__main__":
    main()
