"""Council members in model-written text (T-23). Code only.

The rule: a model-written sentence, fact or item description may name a council member ONLY inside a plain recorded-vote
statement (who voted Aye or Nay, abstained, or was absent) AND only if the city's roll call for that item says so. Any other
mention is rejected and never published: characterizing someone, their motives, patterns across votes, comparisons, quotes that
are not from the record, who sponsored or championed something. This is the line between reporting a vote the city recorded and
writing about a person. The site still never ranks, scores or profiles members.

Roll calls come from the city's own item data (api_items: each item carries `votes: [{name, vote}]`). The city's vote words are
Aye, Nay, Abstain, Out and Excused; the sentence's words are mapped onto those.
"""

import json
import os
import re

from pipeline import paths

ROSTER_FILE = os.path.join(paths.ROOT, "site-inputs", "council_roster.json")

# what a sentence says -> the city's words for it
VOTE_WORDS = {
    "aye": {"Aye"}, "yes": {"Aye"}, "yea": {"Aye"}, "in favor": {"Aye"},
    "nay": {"Nay"}, "no": {"Nay"}, "against": {"Nay"},
    "abstained": {"Abstain"}, "abstaining": {"Abstain"}, "out": {"Out", "Excused"},
    "absent": {"Out", "Excused"}, "was absent": {"Out", "Excused"}, "were absent": {"Out", "Excused"}, "excused": {"Excused", "Out"},
}
TITLES = r"(?:the\s+)?(?:council\s?members?|councilwoman|councilman|mayor\s+pro\s+tem|mayor)"
MATTER = re.compile(r"\b2\d{5}\b")
# what may follow "voted Nay": nothing, "both"/"all"/"it", or a plain list of item numbers
SCOPE = re.compile(r"^(?:both|all|them|it|that|this|(?:(?:the\s+)?(?:ordinances?|resolutions?|items?|special\s+actions?|communications?|bills?)\s+)?"
                   r"2\d{5}(?:\s*(?:,|and|or|&)\s*(?:and\s+)?(?:(?:ordinances?|resolutions?|items?)\s+)?2\d{5})*)$", re.I)


def _norm(s):
    return " ".join((s or "").replace("’", "'").replace("‘", "'").split())


def load_roster():
    """The standing roster of member names (site-inputs/council_roster.json), so item descriptions are checked too."""
    try:
        with open(ROSTER_FILE, encoding="utf-8") as f:
            return [_norm(n) for n in json.load(f)["names"]]
    except (OSError, ValueError, KeyError):
        return []


def roster_from_items(api_items):
    """Every name that appears in a roll call of these items."""
    names = set()
    for it in api_items or []:
        for v in it.get("votes") or []:
            if v.get("name"):
                names.add(_norm(v["name"]))
    return names


def full_roster(api_items=None):
    return sorted(set(load_roster()) | roster_from_items(api_items))


def _forms(name):
    """The ways a sentence may refer to a member: the full name, the last name, and for a two-word last name both words."""
    parts = name.split()
    forms = {name, parts[-1]}
    if len(parts) >= 3:
        forms.add(" ".join(parts[-2:]))
    return {f for f in forms if len(f) >= 3}


def _alts(names):
    forms = {}
    for n in names:
        for f in _forms(n):
            forms.setdefault(f.lower(), set()).add(n)
    return sorted(forms, key=len, reverse=True), forms


def _pattern(names):
    alts, forms = _alts(names)
    if not alts:
        return None, forms
    return re.compile(r"(?<![\w'-])(" + "|".join(re.escape(a) for a in alts) + r")(?![\w-])", re.I), forms


def mentions(text, names):
    """The full names of the members a text refers to."""
    rx, forms = _pattern(names)
    if rx is None:
        return set()
    found = set()
    for m in rx.finditer(_norm(text)):
        found |= forms[m.group(1).lower()]
    return found


def _clause_rx(names):
    alts, forms = _alts(names)
    name = "(?:" + "|".join(re.escape(a) for a in alts) + ")"
    who = rf"(?P<who>{name}(?:(?:\s*,\s*(?:and\s+)?|\s+and\s+){name})*)"
    vote = "|".join(sorted((re.escape(w) for w in VOTE_WORDS), key=len, reverse=True))
    return re.compile(rf"^(?:{TITLES}\s+)?{who}\s+(?:both\s+)?(?:voted\s+)?(?P<v>{vote})(?:\s+(?:on\s+)?(?P<scope>.+))?$", re.I), forms


def _frame2_rx(names):
    alts, forms = _alts(names)
    name = "(?:" + "|".join(re.escape(a) for a in alts) + ")"
    vote = "|".join(sorted((re.escape(w) for w in VOTE_WORDS), key=len, reverse=True))
    frag = rf"{name}\s+(?:voting\s+|voted\s+)?(?:{vote})"
    sep = r"(?:\s*,\s*(?:and\s+)?|\s+and\s+)"
    whole = re.compile(rf"^(?P<pre>.*?),?\s+with\s+(?P<frags>{frag}(?:{sep}{frag})*)$", re.I)
    one = re.compile(rf"(?P<who>{name})\s+(?:voting\s+|voted\s+)?(?P<v>{vote})", re.I)
    return whole, one, forms


def _vote_of(items, matter, member):
    """The member's recorded votes on this matter at this meeting."""
    out = []
    for it in items:
        if str(it.get("EventItemMatterFile") or "").strip() == matter:
            for v in it.get("votes") or []:
                if _norm(v.get("name")) == member:
                    out.append(v.get("vote"))
    return out


def verify_published(doc, api_items):
    """A published document re-checked against the city's roll calls: every fact and sentence that names a member is kept and marked
    `members_verified` only if it is a recorded-vote statement the roll call confirms; the rest are removed (and any sentence that
    cited a removed fact). The document is marked `members_checked`. Pure: returns a new document."""
    names = full_roster(api_items)
    claims, dropped = [], set()
    for c in doc["claims"]:
        if not mentions(c.get("statement", ""), names):
            claims.append(c)
        elif check_text(c["statement"], api_items, [c.get("matter_file")])[0]:
            claims.append(dict(c, members_verified=True))
        else:
            dropped.add(c["id"])
    matter = {c["id"]: c.get("matter_file") for c in doc["claims"]}
    sentences = []
    for s in doc["sentences"]:
        if dropped & set(s.get("claim_ids", [])):
            continue
        if not mentions(s.get("text", ""), names):
            sentences.append(s)
        elif check_text(s["text"], api_items, [matter.get(c) for c in s.get("claim_ids", [])])[0]:
            sentences.append(dict(s, members_verified=True))
    headline = doc.get("headline", "")
    if mentions(headline, names):
        headline = f"{doc['meta']['body']} {doc['meta']['kind']}, {doc['meta']['date']}"
    return dict(doc, claims=claims, sentences=sentences, headline=headline, members_checked=True)


def check_text(text, api_items=None, extra_matters=()):
    """(ok, reason). ok when the text names no member, or names members only in recorded-vote statements the roll call confirms."""
    names = full_roster(api_items)
    found = mentions(text, names)
    if not found:
        return True, None
    if not api_items:
        return False, "member_named: no roll call to check it against"
    rx, forms = _clause_rx(names)
    t = _norm(text)
    text_matters = set(MATTER.findall(t)) | {str(m) for m in extra_matters if m and str(m).isdigit()}
    for clause in [c.strip() for c in re.split(r"(?<=[.;!?])\s+|;\s*", t) if c.strip()]:
        clause = clause.rstrip(".;!? ")
        if not mentions(clause, names):
            continue
        # each statement is (who, the city's words for the vote, the items it is about)
        statements = []
        m = rx.match(clause)
        if m:
            who = set()
            for piece in re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+", m.group("who")):
                who |= forms.get(piece.strip().lower(), set())
            scope = (m.group("scope") or "").strip()
            if scope and not SCOPE.match(scope):
                return False, "member_named: more than a recorded vote is stated"
            statements.append((who, VOTE_WORDS[m.group("v").lower()], set(MATTER.findall(scope)) or text_matters))
        else:
            whole, one, forms2 = _frame2_rx(names)
            m2 = whole.match(clause)
            if not m2 or mentions(m2.group("pre"), names):
                return False, "member_named: not a plain recorded-vote statement"
            here = set(MATTER.findall(m2.group("pre"))) or text_matters
            for f in one.finditer(m2.group("frags")):
                statements.append((forms2.get(f.group("who").lower(), set()), VOTE_WORDS[f.group("v").lower()], here))
        for who, allowed, matters in statements:
            if not matters:
                return False, "member_named: no item named for the vote"
            for matter in sorted(matters):
                for member in sorted(who):
                    votes = _vote_of(api_items, matter, member)
                    if not votes:
                        return False, f"member_named: no roll call for {member} on {matter}"
                    if not any(v in allowed for v in votes):
                        return False, f"member_named: the roll call has {member} as {'/'.join(sorted(set(votes)))} on {matter}"
    return True, None
