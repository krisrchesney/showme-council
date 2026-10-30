"""Topic of an agenda item, by keyword rules on its official title (T-19). Code only, no model.

Rules are tried in order and the first match wins, so the order matters: a ceremonial resolution that mentions a park is
still ceremonial. The rules are blunt on purpose and their accuracy is measured, not assumed: scripts/topic_sample.py asks a
model to tag a sample of titles and reports how often the rules agree (docs/AGENDA-VS-MINUTES.md has the result).
"""

import re

# (topic, description for people and for the model that checks the rules, regex on the lower-cased title)
RULES = [
    ("ceremonial", "Recognizing, honoring or commemorating a person, group or occasion",
     r"\brecogniz|\bhonor|\bcommemorat|\bproclaim|\bcongratulat|\bin memory\b|\bawareness month\b"),
    ("bonds_financing", "Bonds, tax increment financing, industrial development and other financing",
     r"\bbonds?\b|\btax increment\b|\bindustrial development\b|\bindustrial revenue\b|\bfinancing\b|\bissuance\b|\bcertificates? of participation\b"),
    ("grants", "Accepting or applying for a grant",
     r"\bgrants?\b"),
    ("budget_funds", "Appropriations, fund transfers, the budget and revenue estimates",
     r"\bappropriat|\bunappropriated\b|\bfund no\b|\bbudget\b|\bestimating revenue\b|\btransfer(ring)? (of )?funds\b|\bcapital improvements?\b"),
    ("land_use", "Zoning, plats, development plans, vacating streets and easements",
     r"\bplat\b|\brezon|\bzoning\b|\bdevelopment plan\b|\bvacat|\beasement|\bright-of-way\b|\bspecial use\b|\bland use\b|\bcomprehensive plan\b|\bdistrict\b.*\b(uses?|plan)\b"),
    ("contracts", "Contracts, agreements, purchases and professional services",
     r"\bcontract|\bagreement|\bprocurement\b|\bpiggyback\b|\bpurchase|\bamendment no\b|\bprofessional services\b|\brenewal\b|\bsettlement\b"),
    ("streets_utilities", "Streets, sidewalks, bridges, water, sewer, transit and the airport",
     r"\bstreets?\b|\bsidewalk|\bbridge|\broad\b|\broads\b|\bsewer|\bwater\b|\bstormwater\b|\btraffic\b|\btransit\b|\bairport\b|\binfrastructure\b|\btrail|\butility|\butilities\b"),
    ("public_safety", "Police, fire, emergency services and public safety",
     r"\bpolice\b|\bfire\b|\bfirefighter|\bemergency\b|\bpublic safety\b|\bcrime\b|\bviolence\b|\b911\b"),
    ("housing", "Housing, homelessness, tenants and neighborhoods",
     r"\bhousing\b|\bhomeless|\btenant|\baffordable\b|\brental\b|\bblight|\bland bank\b|\bneighborhood\b|\bdwelling"),
    ("parks_recreation", "Parks, recreation, community centers and pools",
     r"\bparks?\b|\brecreation|\bplayground|\bcommunity center\b|\bgolf\b|\bpool\b|\bswimming\b"),
    ("city_code", "Changes to the city code or charter, pay and personnel",
     r"\bchapter \d|\bcode of ordinances\b|\bcharter\b|\bamending section\b|\bsalary\b|\bpay\b|\bpersonnel\b|\bemployee"),
]
# Appointments are checked right after ceremonial items: "appointing members to the Board of Zoning Adjustment" is about
# appointments, not zoning. The words are only appoint/reappoint, because "commission" and "committee" appear in the titles of
# many other items ("referred to the ... Committee").
RULES.insert(1, ("boards_appointments", "Appointments to boards and commissions", r"\bappoint|\breappoint"))
OTHER = ("other", "None of the above")
TOPICS = [t for t, _, _ in RULES] + [OTHER[0]]
DESCRIPTIONS = {t: d for t, d, _ in RULES}
DESCRIPTIONS[OTHER[0]] = OTHER[1]
_COMPILED = [(t, re.compile(rx)) for t, _, rx in RULES]
_SPONSOR = re.compile(r"^sponsor(?:\(s\))?:.*?(?=\b(?:resolution|ordinance|authorizing|approving|amending|appropriating|accepting|"
                      r"establishing|declaring|directing|recognizing|vacating|estimating|waiving|calling|adopting)\b)", re.I)


def body_of(title):
    """The title minus the leading 'Sponsor: ...' words, so a sponsor's department name can't decide the topic."""
    t = " ".join((title or "").split())
    t = _SPONSOR.sub("", t, count=1)
    return t.lower()


def topic_of(title):
    t = body_of(title)
    for topic, rx in _COMPILED:
        if rx.search(t):
            return topic
    return OTHER[0]
