"""Planted errors (canaries): would the fact-checker catch a wrong claim?

The pass rate says how much survives; it can't say whether the checker would say "no" to something false.
So each document's fact-checker call also gets a few fake claims. Each is a copy of a claim that already
passed the code checks, made false in a way code can't see (the quote, numbers and matter number are all
still right):

  flip_outcome  "passed" becomes "failed" (or "held" becomes "approved"...), outcome field flipped to match
  overstate     "passed" becomes "passed unanimously" for a vote the city's roll call shows had Nay votes
  swap_name     the councilmember who voted no is replaced by one who voted aye
  swap_body     the vote is attributed to a different body than the meeting's

The checker is never told which claims are fake: they get ordinary ids that continue the real sequence.
They are never published and never reach decide(); their verdicts are split off and only counted.
A fake counts as caught when the checker's verdict is anything other than SUPPORTED. Whether code would
also have caught it is recorded separately (flip_outcome contradicts the city's record, so code catches
that one too; the other three are the checker's alone).
"""

import copy
import re

TYPES = ("flip_outcome", "overstate", "swap_name", "swap_body")
BODIES = ["Council", "Neighborhood Planning and Development Committee",
          "Finance, Governance and Public Safety Committee", "Transportation, Infrastructure and Operations Committee"]

# (regex on the statement, replacement, new value of the outcome field)
FLIPS = [
    (r"\bpassed\b", "failed", "failed"),
    (r"\badopted\b", "rejected", "failed"),
    (r"\bheld\b", "approved", "passed"),
    (r"\breferred\b", "approved", "passed"),
    (r"\brecommended do pass\b", "recommended against passage", "other"),
]


def next_number(claims):
    """The number after the highest c<N> id in use, so a fake's id can't collide with a real one."""
    nums = [int(m.group(1)) for c in claims if (m := re.match(r"c(\d+)", c["id"]))]
    return (max(nums) if nums else 0) + 1


def roll_call(api_items, matter):
    for it in api_items:
        if (it.get("EventItemMatterFile") or "").strip() == (matter or "").strip() and it.get("votes"):
            return it["votes"]
    return []


def _surname(name):
    return (name or "").replace("’", "'").strip().split()[-1] if (name or "").strip() else ""


def _flip(claim):
    for pat, repl, outcome in FLIPS:
        if re.search(pat, claim["statement"], re.I):
            c = copy.deepcopy(claim)
            c["statement"] = re.sub(pat, repl, claim["statement"], count=1, flags=re.I)
            c["outcome"] = outcome
            return c
    return None


def _overstate(claim, api_items):
    votes = roll_call(api_items, claim.get("matter_file"))
    if claim.get("type") != "vote" or not any(v["vote"] == "Nay" for v in votes):
        return None
    for word in ("passed", "adopted"):
        if re.search(rf"\b{word}\b", claim["statement"], re.I):
            c = copy.deepcopy(claim)
            c["statement"] = re.sub(rf"\b{word}\b", f"{word} unanimously", claim["statement"], count=1, flags=re.I)
            return c
    return None


def _swap_name(claim, api_items):
    votes = roll_call(api_items, claim.get("matter_file"))
    nays = {_surname(v["name"]) for v in votes if v["vote"] == "Nay"}
    ayes = [_surname(v["name"]) for v in votes if v["vote"] == "Aye"]
    for nay in sorted(nays):
        if nay and re.search(rf"\b{re.escape(nay)}\b", claim["statement"]):
            repl = next((a for a in ayes if a and not re.search(rf"\b{re.escape(a)}\b", claim["statement"])), None)
            if repl:
                c = copy.deepcopy(claim)
                c["statement"] = re.sub(rf"\b{re.escape(nay)}\b", repl, claim["statement"], count=1)
                return c
    return None


def _swap_body(claim, meta):
    if claim.get("type") != "vote":
        return None
    s = claim["statement"]
    # a body that is neither the meeting's own nor already named in the statement, or the fake isn't false
    other = next((b for b in BODIES if b != meta.get("body", "") and b.lower() not in s.lower()), None)
    if other is None:
        return None
    c = copy.deepcopy(claim)
    c["statement"] = f"At the {other} meeting, {s[0].lower() + s[1:]}"
    return c


def make_canaries(meta, trusted, api_items, first_number, n=4):
    """Fake claims built from `trusted` claims (ones that passed the code checks).

    Returns (claims, info): claims are ordinary claim dicts with ids c<first_number>, c<first_number+1>...;
    info maps each fake id to {"type", "source_id", "original"} and is never sent to the checker.
    Deterministic: types in a fixed order, source claims in id order, each source used once."""
    claims, info, used = [], {}, set()
    makers = {
        "flip_outcome": lambda c: _flip(c),
        "overstate": lambda c: _overstate(c, api_items),
        "swap_name": lambda c: _swap_name(c, api_items),
        "swap_body": lambda c: _swap_body(c, meta),
    }
    progress = True
    while len(claims) < n and progress:
        progress = False
        for kind in TYPES:
            if len(claims) >= n:
                break
            for src in trusted:
                if src["id"] in used:
                    continue
                fake = makers[kind](src)
                if fake is None or fake["statement"] == src["statement"]:
                    continue
                fake["id"] = f"c{first_number + len(claims)}"
                claims.append(fake)
                info[fake["id"]] = {"type": kind, "source_id": src["id"], "original": src["statement"]}
                used.add(src["id"])
                progress = True
                break
    return claims, info


def score(info, fake_claims, verdicts_by_id, checks_by_id):
    """One row per fake: was it caught by the checker, and would code have caught it anyway?"""
    rows = []
    by_id = {c["id"]: c for c in fake_claims}
    for cid, meta in info.items():
        v = verdicts_by_id.get(cid)
        ck = checks_by_id.get(cid) or {}
        rows.append({
            "id": cid, "type": meta["type"], "source_id": meta["source_id"],
            "fake_statement": by_id[cid]["statement"], "original_statement": meta["original"],
            "checker_verdict": v["verdict"] if v else "NO_VERDICT",
            "checker_reason": v["reason"] if v else "",
            "checker_caught": bool(v) and v["verdict"] != "SUPPORTED",
            "code_caught": not ck.get("passed", True),
        })
    return rows


def summary(rows):
    by_type = {}
    for r in rows:
        t = by_type.setdefault(r["type"], {"total": 0, "checker_caught": 0})
        t["total"] += 1
        t["checker_caught"] += r["checker_caught"]
    return {
        "total": len(rows),
        "checker_caught": sum(r["checker_caught"] for r in rows),
        "code_caught": sum(r["code_caught"] for r in rows),
        "caught_by_either": sum(r["checker_caught"] or r["code_caught"] for r in rows),
        "by_type": by_type,
    }   # counts only: this goes into the published report, so no fake ids or statements
