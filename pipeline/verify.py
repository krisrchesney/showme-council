"""The code half of fact-checking. Runs before and after the fact-checker agent.

A claim is published only if it passes BOTH:
  1. code_checks()  - mechanical, deterministic, free:
       quote_found      the quote is in the source (exact after normalizing, or >= FUZZY_MIN similar)
       quote_length     at least MIN_QUOTE_CHARS, so "Passed" can't prove anything
       numbers_in_quote every number in the statement / amount appears in the quote, except the
                        claim's own matter number when matter_block confirms it
       matter_block     the quote sits inside the source block of the agenda item whose matter
                        number the claim names (blocks are located from the API's item titles).
                        Needed because Legistar minutes print the number a few lines after the
                        item's description, so a correct quote often can't contain it.
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
COVERAGE_MIN = 0.40     # below this share of voted items covered, the default model is not coping (stop and ask)
COVERAGE_MIN_ITEMS = 5  # ...but only for meetings with at least this many recorded votes

_PAGE_RE = re.compile(r"^=== page (\d+) ===$", re.M)
# A number glued to letters ("IAP2", "CD2") is part of a name, not a figure to check.
ORDINAL_RE = re.compile(r"(?:st|nd|rd|th)\b")   # "63rd" is a street name, not a figure
_NUM_RE = re.compile(r"(?<![A-Za-z\d])\d[\d,]*(?:\.\d+)?(?![\d])")
TITLE_PROBE = 50          # chars of an API item title searched for in the source
_TRANS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                        "–": "-", "—": "-", " ": " "})


def normalize(s):
    s = unicodedata.normalize("NFKC", s).translate(_TRANS).lower()
    s = re.sub(r"-\s*\n\s*", "", s)          # words hyphenated across a line break
    s = re.sub(r"\$\s+", "$", s)             # "$ 1,100,000.00" -> "$1,100,000.00"
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)             # "one ( 1) year" -> "one (1) year"
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


def numbers(s, skip_ordinals=False):
    """Canonical numbers in a string. skip_ordinals drops "63rd"/"5th": on the statement side they are
    names (63rd Street) that a quote need not repeat. On the quote side keep them, so "November 5th"
    in the quote still supports "November 5" in the statement."""
    out = set()
    for m in _NUM_RE.finditer(s or ""):
        if skip_ordinals and ORDINAL_RE.match(s, m.end()):
            continue
        out.add(_canon(m.group(0)))
    return out


def numbers_check(claim, meta):
    """Numbers in the statement (and amount_usd) that the quote doesn't contain."""
    wanted = numbers(claim.get("statement", ""), skip_ordinals=True)
    if claim.get("amount_usd") is not None:
        wanted.add(_canon(str(claim["amount_usd"])))
    have = numbers(normalize(claim.get("quote", "")))
    # The meeting date is in the page header, not in every quote; let its parts through.
    y, m, d = (meta.get("date") or "0-0-0").split("-")
    allowed = have | {_canon(y), _canon(m), _canon(d)}
    return sorted(wanted - allowed, key=lambda x: float(x))


# What each claimed outcome looks like in the city's own record (Legistar's action names and pass/fail flag).
# The city's wording varies: "Held on Docket" (Council), "Hold on Agenda" and "Held in Committee" (committees),
# "referred" and "Re-referred", "Adv and Do Pass" and "Move to Advance" (a committee advancing an item to the
# Council, which is not the Council passing it). Word boundaries matter: "Adv and Do Pass" must NOT read as "passed".
_OUTCOME_ACTION = {
    "passed": re.compile(r"\bpassed\b"),
    "adopted": re.compile(r"\badopted\b"),
    "failed": re.compile(r"\bfailed\b"),
    "held": re.compile(r"\bheld\b|\bhold\b"),
    "referred": re.compile(r"\bre-?referred\b|\breferred\b"),
    "advanced": re.compile(r"\badv\b|\badvanced?\b|\bdo pass\b"),
}
_OUTCOME_FLAG = {"passed": "pass", "adopted": "pass", "failed": "fail"}   # the API's PassedFlagName


def api_check(claim, api_items):
    """'agree', 'disagree' or 'unchecked' (no matter number, no checkable outcome, or the API lacks the item)."""
    mf, outcome = claim.get("matter_file"), claim.get("outcome")
    if not mf or outcome not in _OUTCOME_ACTION:
        return "unchecked"
    rows = [r for r in api_items if (r.get("EventItemMatterFile") or "").strip() == str(mf).strip()]
    rows = [r for r in rows if r.get("EventItemActionName") or r.get("EventItemPassedFlagName")]
    if not rows:
        return "unchecked"
    for r in rows:
        action = (r.get("EventItemActionName") or "").lower()
        flag = (r.get("EventItemPassedFlagName") or "").lower()
        if _OUTCOME_ACTION[outcome].search(action) or (flag and flag == _OUTCOME_FLAG.get(outcome)):
            return "agree"
    return "disagree"


def _joined(pages):
    return " ".join(pages[p] for p in sorted(pages))


def _locate(q, joined):
    """Start offset of the quote in the joined source, or None."""
    i = joined.find(q)
    if i >= 0:
        return i
    m = SequenceMatcher(None, joined, q, autojunk=False).find_longest_match(0, len(joined), 0, len(q))
    return max(0, m.a - m.b) if m.size >= min(40, len(q) // 2) else None


def _description(title):
    """An item's own wording: its API title minus the 'Sponsor: ...' and 'COMMITTEE SUBSTITUTE' lines,
    which many items share and which would match the wrong spot in the minutes."""
    lines = [ln for ln in (title or "").splitlines()
             if ln.strip() and not ln.strip().lower().startswith(("sponsor", "committee sub"))]
    return normalize(" ".join(lines))


def matter_blocks(pages, api_items):
    """[(start_offset, matter_file)] sorted: where each agenda item's text begins in the source.

    The item's description is searched for (longest probe first, since neighbours can share an
    opening), then the block start is pulled back to the 'Sponsor:' line just before it.
    A block runs until the next item's block starts."""
    joined = _joined(pages)
    starts = {}
    for it in api_items:
        mf, desc = (it.get("EventItemMatterFile") or "").strip(), _description(it.get("EventItemTitle"))
        if not mf or len(desc) < TITLE_PROBE:
            continue
        i = -1
        for n in (200, 120, TITLE_PROBE):
            i = joined.find(desc[:n])
            if i >= 0 and (n > TITLE_PROBE or joined.count(desc[:n]) == 1):   # short probes must be unique
                break
            i = -1
        if i < 0:
            # Multi-line sponsor headers leave names in the description; slide the probe along
            # and accept only a window that occurs exactly once in the source.
            for off in range(30, min(len(desc) - TITLE_PROBE, 240) + 1, 30):
                probe = desc[off:off + TITLE_PROBE]
                if joined.count(probe) == 1:
                    i = joined.find(probe)
                    break
        if i >= 0:
            j = joined.rfind("sponsor", max(0, i - 160), i)
            starts[mf] = j if j >= 0 else i
    return sorted((v, k) for k, v in starts.items())


def _positions(q, joined):
    """Every start offset of the quote in the source. A quote like 'A motion was made that this
    Ordinance be Passed' repeats under every passed item, so the first hit proves nothing about
    which item it belongs to. Falls back to the single best fuzzy hit when there is no exact one."""
    out, i = [], joined.find(q)
    while i >= 0:
        out.append(i)
        i = joined.find(q, i + 1)
    if out:
        return out
    j = _locate(q, joined)
    return [j] if j is not None else []


def _owner(pos, blocks):
    owner = None
    for start, file in blocks:
        if start <= pos:
            owner = file
        else:
            break
    return owner


def matter_check(claim, pages, api_items):
    """'block' if the quote occurs inside the named matter's own block, 'other:<file>' if it occurs
    only in other items' blocks, 'unlocated' if the claimed item or the quote can't be placed,
    'none' if the claim names no matter. Any occurrence in the claimed item's block counts: the text
    really is there. A boilerplate quote still can't back a claim about an item whose block lacks it."""
    mf = (claim.get("matter_file") or "").strip()
    if not mf:
        return "none"
    blocks = matter_blocks(pages, api_items)
    if not blocks or mf not in {f for _, f in blocks}:
        return "unlocated"      # can't place the claimed item itself, so don't blame a neighbour
    positions = _positions(normalize(claim.get("quote", "")), _joined(pages))
    if not positions:
        return "unlocated"
    owners = [_owner(p_, blocks) for p_ in positions]
    if mf in owners:
        return "block"
    first = next((o for o in owners if o), None)
    return f"other:{first}" if first else "unlocated"


# An agenda is a plan, never an outcome. On an agenda a claim must not say something passed, was approved, or
# "authorizes" a thing, and must not carry a recorded outcome. "Scheduled", "listed", "would" and "proposed" are fine.
AGENDA_OUTCOME_FIELDS = ("passed", "adopted", "failed", "held", "referred", "advanced")
AGENDA_OUTCOME_WORDS = re.compile(
    r"\b(passed|approved|adopted|authorizes|authorised|authorized|enacted|rejected|failed|voted|advanced|agreed|carried)\b", re.I)
AGENDA_PLAN_WORDS = re.compile(
    r"\b(scheduled|planned|proposed|proposes|would|will|to be|seeks|listed|up for|on the agenda|slated)\b", re.I)


def agenda_states_outcome(claim, meta):
    """True if a claim made from an AGENDA reads as a decision."""
    if meta.get("kind") != "agenda":
        return False
    if claim.get("outcome") in AGENDA_OUTCOME_FIELDS:
        return True
    statement = claim.get("statement", "")
    return bool(AGENDA_OUTCOME_WORDS.search(statement)) and not AGENDA_PLAN_WORDS.search(statement)


def code_checks(claim, pages, meta, api_items):
    match, score, page = find_quote(claim.get("quote", ""), pages)
    missing = numbers_check(claim, meta)
    matter = matter_check(claim, pages, api_items)
    mf = _canon(claim["matter_file"]) if (claim.get("matter_file") or "").strip().isdigit() else None
    if matter == "block" and mf in missing:
        missing = [n for n in missing if n != mf]   # its number is proven by position instead
    api = api_check(claim, api_items)
    qlen = len(normalize(claim.get("quote", "")))
    reasons = []
    if match == "none":
        reasons.append("quote_not_found")
    if qlen < MIN_QUOTE_CHARS:
        reasons.append("quote_too_short")
    if missing:
        reasons.append("number_not_in_quote")
    if matter.startswith("other:"):
        reasons.append("quote_from_other_item")
    if api == "disagree":
        reasons.append("api_disagrees")
    if agenda_states_outcome(claim, meta):
        reasons.append("agenda_states_outcome")
    return {
        "quote_match": match, "quote_score": score, "quote_page": page,
        "numbers_missing_from_quote": missing, "matter": matter, "api": api,
        "passed": not reasons, "reasons": reasons,
    }


def coverage(meta, api_items, accepted):
    """How much of the meeting the page covers, measured against the city's own record.

    voted   = agenda items the API records a pass/fail for (minutes only; an agenda has no votes)
    covered = those items that have at least one ACCEPTED fact naming their matter number.
    The pass rate says how much of what was extracted survived; this says how much of the meeting
    was extracted at all. Returns None when there is nothing to measure."""
    if meta.get("kind") != "minutes":
        return None
    voted = sorted({(i.get("EventItemMatterFile") or "").strip() for i in api_items
                    if (i.get("EventItemMatterFile") or "").strip() and i.get("EventItemPassedFlagName")})
    if not voted:
        return None
    got = {(c.get("matter_file") or "").strip() for c in accepted if c.get("matter_file")}
    missing = [m for m in voted if m not in got]
    return {"voted": len(voted), "covered": len(voted) - len(missing),
            "rate": round((len(voted) - len(missing)) / len(voted), 3), "missing": missing}


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
    # The headline may restate any claim the summary used, so every one of them must have been accepted.
    # (T-10 gives the headline its own claim list so one rejected fact doesn't cost the whole headline.)
    cited = {cid for s in sentences for cid in s.get("claim_ids", [])}
    headline_ok = hv is not None and hv["verdict"] == "FAITHFUL" and bool(published) and cited <= ok_ids
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
