"""The code half of fact-checking. Runs before and after the fact-checker agent.

A claim is published only if it passes BOTH:
  1. code_checks()  - mechanical, deterministic, free:
       quote_found      the quote is in the source (exact after normalizing, or >= FUZZY_MIN similar)
       quote_length     at least MIN_QUOTE_CHARS, so "Passed" can't prove anything
       numbers_in_quote every number in the statement / amount appears in the quote
       api_agrees       for votes, the city's own API records the same outcome (when it has one)
  2. the fact-checker agent's verdict == SUPPORTED (reads the quote in context).

A summary sentence is published only if the fact-checker marks it FAITHFUL and every
claim it cites was published. The pass/reject counts from here are the headline metric.

Thresholds live here and nowhere else. Lowering one to raise the pass rate is the
"gaming the check" failure CLAUDE.md forbids.
"""

import re
import unicodedata
from difflib import SequenceMatcher

FUZZY_MIN = 0.92        # PDF text extraction mangles some spacing; below this it's a different passage
MIN_QUOTE_CHARS = 20

_PAGE_RE = re.compile(r"^=== page (\d+) ===$", re.M)
_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_TRANS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                        "–": "-", "—": "-", " ": " "})


def normalize(s):
    s = unicodedata.normalize("NFKC", s).translate(_TRANS).lower()
    s = re.sub(r"-\s*\n\s*", "", s)          # words hyphenated across a line break
    s = re.sub(r"\$\s+", "$", s)             # "$ 1,100,000.00" -> "$1,100,000.00"
    return re.sub(r"\s+", " ", s).strip()


def split_pages(text):
    """{page_number: normalized page text}"""
    parts = _PAGE_RE.split(text)
    pages = {}
    for i in range(1, len(parts) - 1, 2):
        pages[int(parts[i])] = normalize(parts[i + 1])
    if not pages:
        pages[1] = normalize(text)
    return pages


def find_quote(quote, pages):
    """Return (match, score, page): match is "exact", "fuzzy" or "none"."""
    q = normalize(quote)
    if not q:
        return "none", 0.0, None
    for p, t in pages.items():
        if q in t:
            return "exact", 1.0, p
    joined = " ".join(pages[p] for p in sorted(pages))   # quote may straddle a page break
    if q in joined:
        return "exact", 1.0, None
    best = (0.0, None)
    for p, t in pages.items():
        sm = SequenceMatcher(None, t, q, autojunk=False)
        m = sm.find_longest_match(0, len(t), 0, len(q))
        if m.size == 0:
            continue
        start = max(0, m.a - m.b)
        window = t[start:start + len(q)]
        score = SequenceMatcher(None, window, q, autojunk=False).ratio()
        if score > best[0]:
            best = (score, p)
    if best[0] >= FUZZY_MIN:
        return "fuzzy", round(best[0], 3), best[1]
    return "none", round(best[0], 3), best[1]


def _canon(num):
    n = float(num.replace(",", ""))
    return str(int(n)) if n == int(n) else repr(n)


def numbers(s):
    return {_canon(m) for m in _NUM_RE.findall(s or "") if any(ch.isdigit() for ch in m)}


def numbers_check(claim, meta):
    """Numbers in the statement (and amount_usd) that the quote doesn't contain."""
    wanted = numbers(claim.get("statement", ""))
    if claim.get("amount_usd") is not None:
        wanted.add(_canon(str(claim["amount_usd"])))
    have = numbers(normalize(claim.get("quote", "")))
    # The meeting date is in the page header, not in every quote; let its parts through.
    y, m, d = (meta.get("date") or "0-0-0").split("-")
    allowed = have | {_canon(y), _canon(m), _canon(d)}
    return sorted(wanted - allowed, key=lambda x: float(x))


_OUTCOME_WORDS = {
    "passed": ("passed", "pass"), "adopted": ("adopted", "pass"), "failed": ("failed", "fail"),
    "held": ("held",), "referred": ("referred",),
}


def api_check(claim, api_items):
    """'agree', 'disagree' or 'unchecked' (no matter number, no outcome, or the API lacks the item)."""
    mf, outcome = claim.get("matter_file"), claim.get("outcome")
    if not mf or outcome not in _OUTCOME_WORDS:
        return "unchecked"
    rows = [r for r in api_items if (r.get("EventItemMatterFile") or "").strip() == str(mf).strip()]
    rows = [r for r in rows if r.get("EventItemActionName") or r.get("EventItemPassedFlagName")]
    if not rows:
        return "unchecked"
    for r in rows:
        recorded = f"{r.get('EventItemActionName') or ''} {r.get('EventItemPassedFlagName') or ''}".lower()
        if any(w in recorded for w in _OUTCOME_WORDS[outcome]):
            return "agree"
    return "disagree"


def code_checks(claim, pages, meta, api_items):
    match, score, page = find_quote(claim.get("quote", ""), pages)
    missing = numbers_check(claim, meta)
    api = api_check(claim, api_items)
    qlen = len(normalize(claim.get("quote", "")))
    reasons = []
    if match == "none":
        reasons.append("quote_not_found")
    if qlen < MIN_QUOTE_CHARS:
        reasons.append("quote_too_short")
    if missing:
        reasons.append("number_not_in_quote")
    if api == "disagree":
        reasons.append("api_disagrees")
    return {
        "quote_match": match, "quote_score": score, "quote_page": page,
        "numbers_missing_from_quote": missing, "api": api,
        "passed": not reasons, "reasons": reasons,
    }


def decide(meta, claims, checks, summary, verdicts):
    """Combine code checks + fact-checker verdicts into what gets published, plus the metric."""
    by_id = {v["id"]: v for v in verdicts.get("claims", [])}
    accepted, rejected = [], []
    reasons_count = {}
    for c in claims:
        ck = checks[c["id"]]
        v = by_id.get(c["id"])
        reasons = list(ck["reasons"])
        if v is None:
            reasons.append("checker_missing")
        elif v["verdict"] == "PARTIAL":
            reasons.append("checker_partial")
        elif v["verdict"] == "UNSUPPORTED":
            reasons.append("checker_unsupported")
        row = dict(c, code_checks=ck, checker=v)
        (rejected if reasons else accepted).append(dict(row, reject_reasons=reasons))
        for r in reasons:
            reasons_count[r] = reasons_count.get(r, 0) + 1

    ok_ids = {c["id"] for c in accepted}
    sv = {v["index"]: v for v in verdicts.get("sentences", [])}
    sentences = summary.get("sentences", [])
    published, dropped = [], []
    for i, s in enumerate(sentences):
        v = sv.get(i)
        good = (v is not None and v["verdict"] == "FAITHFUL"
                and s.get("claim_ids") and all(cid in ok_ids for cid in s["claim_ids"]))
        (published if good else dropped).append(dict(s, index=i, checker=v))

    # The headline is checked as one extra sentence citing every claim the summary used.
    hv = sv.get(len(sentences))
    headline_ok = hv is not None and hv["verdict"] == "FAITHFUL" and bool(published)
    headline = summary.get("headline") if headline_ok else (
        f"{meta['body']} {meta['kind']}, {meta['date']}")

    n, k = len(claims), len(accepted)
    report = {
        "doc_id": meta["doc_id"],
        "claims_extracted": n, "claims_accepted": k, "claims_rejected": n - k,
        "claim_pass_rate": round(k / n, 3) if n else None,
        "reject_reasons": dict(sorted(reasons_count.items())),
        "code_vs_checker": _agreement(claims, checks, by_id),
        "sentences_written": len(sentences), "sentences_published": len(published),
        "sentence_pass_rate": round(len(published) / len(sentences), 3) if sentences else None,
        "headline_checked": headline_ok,
    }
    return {"headline": headline, "accepted": accepted, "rejected": rejected,
            "published_sentences": published, "dropped_sentences": dropped, "report": report}


def _agreement(claims, checks, by_id):
    """How often the code gate and the LLM checker reach the same pass/fail call."""
    both = agree = 0
    for c in claims:
        v = by_id.get(c["id"])
        if v is None:
            continue
        both += 1
        agree += checks[c["id"]]["passed"] == (v["verdict"] == "SUPPORTED")
    return {"compared": both, "agree": agree}
