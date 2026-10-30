"""Topics of an agenda item, by keyword rules on its official title (T-19, v2). Code only, no model.

An item can carry several topics (a sewer-bond ordinance is both bonds and streets/utilities). Every rule that matches counts, and
the PRIMARY topic is the one whose keyword appears earliest in the cleaned title, because the title opens with what the item does.
Before matching, the title is cleaned: the sponsor, the committee's action text and standard boilerplate ("recognizing this
ordinance as having an accelerated effective date", "directing the City Clerk to record certain documents") are removed, since
those words describe the paperwork, not the subject.

The rules are blunt and their accuracy is measured, not assumed: scripts/topic_sample.py asks a model to tag a sample of titles and
reports how often the rules agree (the site's accuracy page has the numbers). A topic whose measured agreement is poor is folded
into "Other" on the site (pipeline/explore.py reads the accuracy file).
"""

import re

# (topic, plain description, regex on the cleaned, lower-cased title)
RULES = [
    ("ceremonial", "Recognizing, honoring or commemorating a person, group or occasion",
     r"\brecogniz|\bhonor|\bcommemorat|\bproclaim|\bcongratulat|\bin memory\b|\bawareness month\b|\bday in kansas city\b"),
    ("boards_appointments", "Appointments to boards and commissions",
     r"\bappoint|\breappoint"),
    ("bonds_financing", "Bonds, tax increment financing, special districts and other financing",
     r"\bbonds?\b|\btax increment\b|\bindustrial development\b|\bindustrial revenue\b|\bfinancing\b|\bissuance\b|"
     r"\bcertificates? of participation\b|\bcommunity improvement district|\bneighborhood improvement district|\bspecial obligation\b|"
     r"\bplanned industrial expansion\b|\btif\b|\bchapter 100\b|payments? in lieu of taxes|\bpilot payments?\b|\btax abatement|\bincentive"),
    ("grants", "Accepting or applying for a grant",
     r"\bgrants?\b|\bfunding application|\bapplications? for (the )?(fy|fiscal)"),
    ("budget_funds", "Appropriations, fund transfers, taxes and fees, the budget and revenue estimates",
     r"\bappropriat|\bunappropriated\b|\bfund no\b|\bbudget\b|\bestimating revenue|\bfund balance\b|\btransfer(ring)? (of )?funds\b|"
     r"\bcapital improvements?\b|\btax(es)? rates?\b|\bsetting the rates?\b|\bproperty tax|\bsales tax|\bfront foot assessment|\bfees?\b"),
    ("land_use", "Zoning, plats, development plans, vacating streets and easements",
     r"\bplat\b|\brezon|\bzoning\b|\bdevelopment plan\b|\bredevelopment plan\b|\bvacat(e|ing|ion)\b(?! property)|\beasement|"
     r"\bright-of-way\b|\bspecial use\b|\b(petition|terminat\w+|establish\w*|remove property)\b.*\bdistrict\b|\bland use\b|\bcomprehensive plan\b|\bsite plan\b|\bacres\b|\bparcel|\bannex"),
    ("contracts", "Contracts, agreements, purchases and professional services",
     r"\bcontract|\bagreement|\bprocurement\b|\bpiggyback\b|\bpurchase|\bamendment no\b|\bprofessional services\b|\brenewal\b|"
     r"\bexecute\b|\bcooperative\b|\blease\b|\bbid\b|\bbids\b"),
    ("streets_utilities", "Streets, sidewalks, bridges, water, sewer, transit and the airport",
     r"\bstreets?\b|\bsidewalk|\bbridge|\broad\b|\broads\b|\bsewer|\bwater\b|\bstormwater\b|\btraffic\b|\btransit\b|\bairport\b|"
     r"\binfrastructure\b|\bbikeway|\bbicycle|\bpedestrian|\bstreetcar\b|\bboulevard|\bparkway|\butility\b|\butilities\b|\bvision zero\b"),
    ("public_safety", "Police, fire, emergency services and public safety",
     r"\bpolice\b|\bkcpd\b|\bfire department\b|\bfirefighters?\b|\bfire (and|&) rescue\b|\bemergency (services|medical|management|response|operations)\b|"
     r"\bpublic safety\b|\bcrime\b|\bviolence\b|\b911\b|\bsheriff\b|\bjail\b|\bdetention\b|\bmunicipal court\b"),
    ("housing", "Housing, homelessness, tenants and neighborhoods",
     r"\bhousing\b|\bhomeless|\btenant|\baffordable\b|\brental\b|\bblight|\bland bank\b|\bdwelling|\bvacant (property|lot|building)|"
     r"\bresidential\b|\bhome repair|\beviction"),
    ("parks_recreation", "Parks, recreation, community centers and pools",
     r"\bparks and recreation\b|\bpark board\b|\bparks? (department|master|maintenance)\b|\brecreation|\bplayground|\bcommunity cent(er|re)\b|"
     r"\bgolf\b|\bswimming\b|\baquatic|\bpool\b|\bpark land\b|\bcity park\b"),
    ("city_code", "Changes to the city code, charter or Council rules; pay and personnel",
     r"\bchapter \d|\bcode of ordinances\b|\bcharter\b|\bamending (section|rule|article)\b|\bstanding rules\b|\brepealing section\b|\bsalary\b|"
     r"\bpay (plan|rate|scale|ordinance)\b|\bpersonnel\b|\bemployee|\bretirement\b|\bpension\b"),
]
OTHER = ("other", "None of the above")
TOPICS = [t for t, _, _ in RULES] + [OTHER[0]]
DESCRIPTIONS = {t: d for t, d, _ in RULES}
DESCRIPTIONS[OTHER[0]] = OTHER[1]
NAMES = {"ceremonial": "Recognitions", "boards_appointments": "Boards & appointments", "bonds_financing": "Bonds & financing",
         "grants": "Grants", "budget_funds": "Budget & funds", "land_use": "Land use & zoning", "contracts": "Contracts",
         "streets_utilities": "Streets & utilities", "public_safety": "Public safety", "housing": "Housing",
         "parks_recreation": "Parks & recreation", "city_code": "City code & personnel", "other": "Other"}
_COMPILED = [(t, re.compile(rx)) for t, _, rx in RULES]

_SPONSOR = re.compile(r"^sponsor(?:\(s\))?:.*?(?=\b(?:resolution|ordinance|authorizing|approving|amending|appropriating|accepting|"
                      r"establishing|declaring|directing|recognizing|vacating|estimating|waiving|calling|adopting|setting|"
                      r"affirming|designating|notice|requesting|expressing|supporting|opposing)\b)", re.I)
_COMMITTEE_TAIL = re.compile(r"\b[A-Z][A-Z,&\- ]{6,}\bCOMMITTEE\b.*$|(?i:\bheld on docket\b.*$|\bhold on agenda\b.*$|"
                             r"\badvance and do pass\b.*$|\bdo pass as a committee substitute\b.*$)")
_LOCATION = re.compile(r"\bgenerally (located|bounded|described)\b[^;]*|\blocated (at|on|in|along)\b[^;]*")   # addresses: a street name in an address is a place, not a topic
_BOILERPLATE = [re.compile(p, re.I) for p in (
    r"and recognizing this (ordinance|resolution) as having an accelerated effective date",
    r"recognizing this (ordinance|resolution) as having an accelerated effective date",
    r"directing the city clerk to record certain documents?",
    r"committee substitute", r"as amended", r"^\s*(ordinance|resolution)\s*[-:]?\s*")]


def body_of(title):
    """The title with the sponsor, the committee's action text and paperwork boilerplate removed, lower-cased."""
    t = " ".join((title or "").replace("�", "'").split())
    t = _SPONSOR.sub("", t, count=1)
    t = _COMMITTEE_TAIL.sub("", t)
    t = _LOCATION.sub("", t)
    for rx in _BOILERPLATE:
        t = rx.sub("", t)
    return " ".join(t.split()).lower()


def short_title(title, limit=220):
    """The official title for people to read: sponsor, committee action text and the 'committee substitute' marker removed, case kept.
    Code only (no rewording): it only cuts words off the ends, so nothing in it is anyone's paraphrase."""
    t = " ".join((title or "").replace("�", "'").split())
    t = _SPONSOR.sub("", t, count=1)
    t = _COMMITTEE_TAIL.sub("", t)
    t = re.sub(r"(?i)^\s*(committee substitute|as amended)\s*", "", t)
    t = " ".join(t.split()).strip(" ;,")
    t = re.sub(r"(?i)^(ordinance|resolution)\s*[-:]\s*", "", t)
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
    return t or "(no title)"


def topics_of(title):
    """[(topic, position)] for every rule that matches, earliest keyword first; [] when none match."""
    t = body_of(title)
    if re.match(r"(notice|noice|notification)\b", t):   # "Notice to the City Clerk ... annual report": a filing, not a decision
        if re.search(r"annual report|financial report", t):
            return []
        t = t.replace("community improvement district", "district")   # the district's name says nothing about the subject
    hits = []
    for topic, rx in _COMPILED:
        m = rx.search(t)
        if m:
            hits.append((topic, m.start()))
    hits.sort(key=lambda h: h[1])
    return hits


def topic_list(title):
    return [t for t, _ in topics_of(title)] or [OTHER[0]]


def topic_of(title):
    """The primary topic: the matching rule whose keyword comes first in the cleaned title."""
    return topic_list(title)[0]
