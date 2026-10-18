"""
Filtering v6 — reject-first philosophy.

v5 kept only jobs whose title matched a keyword ALLOWLIST, which silently
dropped every early-career role phrased differently ("AI Trainer",
"Supply Chain Graduate", "Programme Analyst", "Operations Associate"...).

v6 inverts this:
  1. REJECT clearly-senior roles (title or description demands 4+ years).
  2. REJECT clearly-irrelevant sectors (licensed professions, trades, care,
     hospitality...). Everything else early-career survives.
  3. Tag a soft category for email grouping (never used as a gate).
  4. Scope check (Ireland / remote / visa-sponsor countries) unchanged in
     spirit, but non-Ireland jobs with a pre-verified sponsorship flag
     (e.g. Arbeitnow visa_sponsorship=true) skip the phrase gate.

The embedding score then RANKS what survives — borderline roles land in
the email's "other" section instead of being invisible.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

# ── Seniority: hard rejects ─────────────────────────────────────────────────

SENIOR_TITLE_PATTERNS = [
    re.compile(r"\bsenior\b", re.I),
    re.compile(r"\bsr\.?\s", re.I),
    re.compile(r"\bstaff\s+(engineer|software|data|developer|scientist)", re.I),
    re.compile(r"\bprincipal\b", re.I),
    re.compile(r"\bdirector\b", re.I),
    re.compile(r"\b(vp|vice president)\b", re.I),
    re.compile(r"\bhead of\b", re.I),
    re.compile(r"\bchief\b", re.I),
    re.compile(r"\bdistinguished\b", re.I),
    re.compile(r"\bexpert\b", re.I),
    re.compile(r"\blead\s+(\w+\s+)?(engineer|developer|architect|scientist|analyst|consultant)", re.I),
    re.compile(r"\bengineering manager\b", re.I),
    re.compile(r"\barchitect\b", re.I),
    # 4+ years in the title itself
    re.compile(r"\b([4-9]|1[0-9])\s*\+?\s*(?:years|yrs)\b", re.I),
    re.compile(r"\bexperienced\b", re.I),   # SIG-style "| Experienced" suffix
]

ENTRY_LEVEL_PATTERNS = [
    re.compile(r"\bgraduate\b", re.I),
    re.compile(r"\bgrad\b", re.I),
    re.compile(r"\bjunior\b", re.I),
    re.compile(r"\bentry.?level\b", re.I),
    re.compile(r"\bintern(ship)?\b", re.I),
    re.compile(r"\btrainee\b", re.I),
    re.compile(r"\bapprentice", re.I),
    re.compile(r"\bearly.?career\b", re.I),
    re.compile(r"\bnew grad\b", re.I),
    re.compile(r"\bcampus\b", re.I),
    re.compile(r"\bco.?op\b", re.I),
    re.compile(r"\bplacement\b", re.I),
    re.compile(r"\bassociate\b", re.I),
    re.compile(r"(?:^|\s)(?:I|1)\s*(?:$|[-,\)\|])"),          # "... Engineer I"
    re.compile(r"(?:^|\s)II\s*(?:$|[-,\)\|])"),               # "... Engineer II"
    re.compile(r"\blevel\s*[12]\b", re.I),
]

# Description-level experience demands, e.g. "5+ years of experience",
# "minimum of 4 years' experience". Only fires near the word experience
# so "founded 40 years ago" doesn't trigger it.
DESC_SENIOR_PATTERN = re.compile(
    r"\b(?:minimum\s+(?:of\s+)?)?([4-9]|1[0-9])\s*\+?\s*(?:years|yrs)['’]?\s*"
    r"(?:of\s+)?(?:\w+\s+){0,3}experience",
    re.I,
)

# Description-level entry signals
DESC_ENTRY_PATTERN = re.compile(
    r"recent graduate|recently graduated|final.?year|no (?:prior |previous )?experience "
    r"(?:required|needed|necessary)|0.?[-–to]{1,4}.?2 years|graduate programme|"
    r"graduate program|entry.?level|early.?career",
    re.I,
)


def seniority_of(title: str, description: str = "") -> str:
    """
    Classify: 'entry', 'senior', or 'unspecified'.

    A title with BOTH signals (e.g. "Graduate Programme Senior Analyst"...
    rare, but "Junior to Senior" ranges exist) counts as entry — false
    positives are cheaper than false negatives for a job seeker.
    """
    entry_title = any(p.search(title) for p in ENTRY_LEVEL_PATTERNS)
    if entry_title:
        return "entry"
    if any(p.search(title) for p in SENIOR_TITLE_PATTERNS):
        return "senior"
    if description:
        if DESC_ENTRY_PATTERN.search(description):
            return "entry"
        for match in DESC_SENIOR_PATTERN.finditer(description):
            context = description[max(0,match.start()-35):match.end()+45]
            if not re.search(r"preferred|desirable|nice.to.have|advantage|ideally",context,re.I):
                return "senior"
    return "unspecified"


# ── Sector rejects: roles that can never fit the profile ────────────────────
# Licensed professions, trades, care, food, transport... A graduate data/tech/
# business profile can't apply to these regardless of seniority.

SECTOR_REJECT_PATTERNS = [re.compile(p, re.I) for p in [
    r"\bnurse\b|\bnursing\b|\bmidwife\b|\bhealthcare assistant\b|\bcare assistant\b",
    r"\bphysiotherap|\boccupational therap|\bspeech and language\b|\bradiograph|\baudiolog",
    r"\bdentist\b|\bdental\b|\bpharmacist\b|\bpharmacy technician\b|\boptometr",
    r"\bveterinar|\bdoctor\b|\bphysician\b|\bsurgeon\b|\bclinical psycholog",
    r"\bsolicitor\b|\bbarrister\b|\blegal secretary\b|\bparalegal\b",
    r"\bchef\b|\bkitchen\b|\bbarista\b|\bbartender\b|\bwaiter\b|\bwaitress\b|\bcatering\b",
    r"\bcleaner\b|\bcleaning operative\b|\bhousekeep|\bjanitor",
    r"\bhgv\b|\bforklift\b|\bdelivery driver\b|\bvan driver\b|\bbus driver\b|\btaxi\b",
    r"\belectrician\b|\bplumber\b|\bwelder\b|\bcarpenter\b|\bbricklayer\b|\bscaffold",
    r"\bbeautician\b|\bhairdress|\bbarber\b|\bnail technician\b",
    r"\bchildcare\b|\bearly years educator\b|\bmontessori\b|\bcreche\b|\bnanny\b",
    r"\bsocial care worker\b|\bsocial worker\b|\bcare worker\b",
    r"\bprimary teacher\b|\bsecondary teacher\b|\bsna\b|\bspecial needs assistant\b",
    r"\bsecurity guard\b|\bdoor supervisor\b|\bwarehouse operative\b|\bpicker\b|\bpacker\b",
    r"\bpest control\b|\bgroundskeep|\blandscap|\bgardener\b",
    r"\btax trainee\b|\baudit trainee\b|\btrainee accountant\b|\baccounting technician\b",
    r"\bquantity surveyor\b|\bsite engineer\b|\bcivil engineer\b|\bstructural engineer\b",
    r"\bmechanical fitter\b|\bmaintenance technician\b|\bcnc\b",
    r"\bretail assistant\b|\bsales assistant\b|\bshop assistant\b|\bcashier\b|\bstore manager\b",
    r"\breceptionist\b|\bclerical officer\b|\badministrative assistant\b",
    r"\bcuratorial\b|\blibrarian\b|\barchivist\b",
]]


def is_rejected_sector(title: str) -> bool:
    return any(p.search(title) for p in SECTOR_REJECT_PATTERNS)


# ── Soft categories (tags for email grouping, NEVER a gate) ─────────────────

CATEGORY_PATTERNS: List[tuple] = [
    ("software",      re.compile(r"software|developer|full.?stack|fullstack|backend|frontend|front.?end|back.?end|web dev|mobile|ios|android|\.net|python dev|java dev|api |engineer", re.I)),
    ("data_ml",       re.compile(r"\bdata\b|machine learning|\bml\b|\bai\b|artificial intelligence|analytics|analyst|scientist|deep learning|nlp|computer vision|mlops|annotation|labell?ing|\btrainer\b", re.I)),
    ("cloud_devops",  re.compile(r"devops|\bsre\b|site reliability|cloud|infrastructure|platform|kubernetes|aws|azure|gcp|linux|network engineer|systems engineer", re.I)),
    ("product_pm",    re.compile(r"product manager|product owner|project manager|programme? manager|project coordinator|scrum|delivery|product analyst", re.I)),
    ("ops_supply",    re.compile(r"supply chain|procurement|logistics|operations|planner|demand planning|inventory|warehouse analyst|process improvement|continuous improvement", re.I)),
    ("business",      re.compile(r"business analyst|consultant|consulting|strategy|risk analyst|finance analyst|financial analyst|fintech|investment|trading|quant|actuar|commercial analyst|insights", re.I)),
    ("qa_support",    re.compile(r"\bqa\b|quality|test engineer|tester|automation|support engineer|technical support|service desk|implementation|solutions engineer|customer success engineer|integration", re.I)),
    ("security",      re.compile(r"security|cyber|soc analyst|penetration|grc|compliance analyst", re.I)),
    ("grad_scheme",   re.compile(r"graduate programme|graduate program|graduate scheme|rotational", re.I)),
]


def category_of(title: str) -> str:
    for name, pattern in CATEGORY_PATTERNS:
        if pattern.search(title):
            return name
    return "other"


# ── Location scope ──────────────────────────────────────────────────────────

# Locations must be checked using the LOCATION field only. Northern Ireland is
# under UK immigration jurisdiction and must not be tagged Republic of Ireland.
NI_PATTERN = re.compile(r"\b(?:northern ireland|belfast|(?:london)?derry|lisburn|newry|armagh|county antrim|county down|county tyrone|county fermanagh|county londonderry)\b", re.I)
ROI_PATTERN = re.compile(
    r"\b(?:republic of ireland|ireland|dublin|cork|galway|limerick|waterford|kilkenny|"
    r"athlone|sligo|dundalk|shannon|leinster|munster|connacht|wicklow|kildare|"
    r"meath|tipperary|wexford|donegal|offaly|laois|clare|kerry|mayo|roscommon|"
    r"monaghan|cavan|longford|carlow|leitrim)\b|,\s*ie\b|\(ie\)", re.I,
)
EU_REMOTE_PATTERNS = [re.compile(p, re.I) for p in [
    r"remote.{0,22}\b(?:eu|europe|european union)\b",
    r"\b(?:eu|europe|european union)\b.{0,22}remote",
]]
REMOTE_ANYWHERE_PATTERNS = [re.compile(p, re.I) for p in [
    r"\bremote\b.{0,25}\b(?:global|anywhere|worldwide|world.?wide)\b",
    r"\b(?:global|anywhere|worldwide|world.?wide)\b.{0,25}\bremote\b",
]]
RESTRICTED_REMOTE = re.compile(
    r"\b(?:us|usa|u\.?s\.?a?\.?|united states|north america|canada|uk|united kingdom|"
    r"australia|india|singapore)\s*[- ]?only\b|"
    r"\bonly\s+(?:in|within|from|for)\s+(?:the\s+)?(?:us|usa|united states|"
    r"north america|canada|uk|united kingdom|australia|india|singapore)\b|"
    r"\b(?:uk|united kingdom|us|usa|united states|canada)\s+(?:residents?|candidates?|applicants?)\s+only\b|"
    r"\bmust\s+(?:be\s+)?(?:based|located|resident)\s+in\s+(?:the\s+)?"
    r"(?:us|usa|united states|north america|canada|uk|united kingdom)\b",
    re.I,
)
# Restriction language may use "US-based applicants" or "must reside in GB"
# rather than the literal "US only". Explicit restrictive language vetoes all
# candidate geographic positives, including EU/global remote listings.
RESTRICTED_WORK_RESIDENCY = re.compile(
    r'\b(?:must|need to|required to|only)\s+(?:be\s+)?(?:currently\s+)?'
    r'(?:reside|resident|based|located|live|work)\s+(?:in|within)\s+(?:the\s+)?'
    r'(?:us|usa|united states|uk|united kingdom|great britain)\b|'
    r'\b(?:us|usa|u\.?s\.?a?\.?|united states|uk|united kingdom|great britain)'
    r'[-\s]+based\s+(?:candidates?|residents?|applicants?)\s*(?:only)?\b|'
    r'\bonly\s+(?:us|usa|united states|uk|united kingdom)'
    r'[-\s]+based\s+(?:candidates?|residents?|applicants?)\b',
    re.I,
)
NEGATIVE_SPONSORSHIP = re.compile(
    r"\b(?:no|not|without|cannot|can't|unable to|do not|don't|does not|doesn't|"
    r"will not|won't)\s+(?:offer|provide|support|available for)?\s*"
    r"(?:any\s+)?(?:visa\s+)?sponsorship\b|"
    r"\b(?:do not|don't|does not|doesn't|will not|won't|cannot|can't|unable to)\s+"
    r"(?:offer|provide|support)?\s*(?:visa\s+)?sponsor(?:ship|ing|\s+visas)?\b|"
    r"\bsponsorship\s+(?:is\s+)?(?:not available|unavailable|not provided)\b|"
    r"\b(?:must|need to|required to)\s+(?:already\s+)?(?:have|hold|possess)\s+"
    r"(?:an?\s+)?(?:existing\s+)?(?:right to work|work permit|work authori[sz]ation)\b",
    re.I,
)
POSITIVE_SPONSORSHIP = re.compile(
    r"\b(?:we|employer|company)\s+(?:can\s+|may\s+|will\s+|do\s+)?"
    r"(?:offer|provide|support|arrange|sponsor)\s+(?:visa\s+)?sponsorship\b|"
    r"\b(?:visa\s+)?sponsorship\s+(?:is\s+)?(?:available|provided|offered|supported)\b|"
    r"\b(?:we\s+)?(?:will|can)\s+sponsor\s+(?:your\s+)?(?:work\s+)?visa\b|"
    r"\b(?:visa|immigration|work permit|employment pass|work visa)\s+"
    r"(?:application\s+)?(?:sponsorship|support|provided|supported|assistance)\b|"
    r"\b(?:we|company|employer)\s+(?:can\s+|will\s+)?sponsor\s+(?:visas?|work permits?|eligible candidates)\b|"
    r"\b(?:sponsor the right candidate|skilled worker visa sponsorship)\b",
    re.I,
)


def matches_any(text: str, patterns) -> bool:
    return any(p.search(text) for p in patterns)


# Geography is a SAFETY gate, not a fuzzy city-name search. A name shared
# across countries (Dublin, Cork, etc.) is never proof of Republic of Ireland.
# Recognise state suffixes as delimited administrative units, NOT substrings:
# "CA" is California in "Dublin, CA" but must not match "CA" in "Canada".
# Do not split multiword state names; those are explicit geographic conflicts.
_US_NAMES = (
    'Alabama', 'Alaska', 'Arizona', 'Arkansas', 'California', 'Colorado',
    'Connecticut', 'Delaware', 'Florida', 'Georgia', 'Hawaii', 'Idaho',
    'Illinois', 'Indiana', 'Iowa', 'Kansas', 'Kentucky', 'Louisiana', 'Maine',
    'Maryland', 'Massachusetts', 'Michigan', 'Minnesota', 'Mississippi',
    'Missouri', 'Montana', 'Nebraska', 'Nevada', 'New Hampshire', 'New Jersey',
    'New Mexico', 'New York', 'North Carolina', 'North Dakota', 'Ohio',
    'Oklahoma', 'Oregon', 'Pennsylvania', 'Rhode Island', 'South Carolina',
    'South Dakota', 'Tennessee', 'Texas', 'Utah', 'Vermont', 'Virginia',
    'Washington', 'West Virginia', 'Wisconsin', 'Wyoming', 'District of Columbia'
)
_US_CODES = (
    'AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI '
    'MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT '
    'VT VA WA WV WI WY DC'
).split()
US_STATE_NAME = re.compile(r'\b(?:' + '|'.join(re.escape(n) for n in _US_NAMES) + r')\b', re.I)
# Comma, semicolon, dash and parenthesis delimiters; accepts "Dublin, CA, USA"
# and "Cork (KY)" but never matches an incidental "or" or "in" in prose.
US_STATE_CODE = re.compile(
    r'(?:,|;|\(|\s[-–—]\s)\s*(?:' + '|'.join(_US_CODES) +
    r')(?=\s*(?:[,;)/]|$))', re.I,
)
FOREIGN_COUNTRY = re.compile(
    r'\b(?:usa|u\.?s\.?a?\.?|united states(?: of america)?|united kingdom|'
    r'uk|great britain|england|scotland|wales|canada|australia|india|'
    r'new zealand|northern ireland|germany|france|netherlands|spain|'
    r'portugal|italy|poland|sweden|switzerland|norway|singapore|'
    r'japan|united arab emirates|uae)\b', re.I,
)
FOREIGN_COUNTRY_CODE = re.compile(
    r'(?:^|[,;(]\s*)(?:US|USA|GB|UK|CA|AU|NZ|IN|DE|FR|NL)(?=\s*(?:[,;)]|$))', re.I,
)
ROI_COUNTRY = re.compile(r'\b(?:republic of ireland|ireland)\b|(?:,\s*IE\b|\(IE\))', re.I)
ROI_CITY = re.compile(
    r'\b(?:dublin|cork|galway|limerick|waterford|kilkenny|athlone|sligo|'
    r'dundalk|shannon|leinster|munster|connacht|wicklow|kildare|meath|'
    r'tipperary|wexford|donegal|offaly|laois|clare|kerry|mayo|'
    r'roscommon|monaghan|cavan|longford|carlow|leitrim)\b', re.I,
)
# Distinctively Irish address details can provide explicit local evidence.
ROI_LOCAL_ADDRESS = re.compile(
    r'\b(?:co\.?\s+(?:cork|dublin|galway|limerick|kildare|wicklow|'
    r'waterford|kilkenny|meath|wexford|donegal|tipperary|kerry|clare)|'
    r'dublin\s+(?:[1-9]|1[0-9]|2[024])|cork city|dublin city centre)\b', re.I,
)
EMEA = re.compile(r'\bemea\b', re.I)
EU_MEMBER = re.compile(
    r'\b(?:ireland|germany|france|netherlands|spain|italy|portugal|'
    r'belgium|luxembourg|austria|poland|denmark|sweden|finland|'
    r'czechia|czech republic|slovakia|slovenia|croatia|greece|'
    r'romania|bulgaria|hungary|malta|cyprus|estonia|latvia|lithuania)\b', re.I)


def _country_conflict(location: str, country: str = '', physical: str = '') -> bool:
    """True if any explicit foreign-country/state evidence defeats ROI claims."""
    parts = (location, country, physical)
    return any(NI_PATTERN.search(part) or FOREIGN_COUNTRY.search(part)
               or FOREIGN_COUNTRY_CODE.search(part)
               or US_STATE_NAME.search(part) or US_STATE_CODE.search(part)
               for part in parts if part)


def _confirmed_roi_country(text: str) -> bool:
    return text.strip().upper() in ('IE', 'IRL') or _confirmed_roi(text)


def _confirmed_roi(text: str) -> bool:
    """Unambiguous Republic of Ireland country/address markers (not city alone)."""
    return bool(ROI_COUNTRY.search(text) or ROI_LOCAL_ADDRESS.search(text))


def is_ireland(location: str, title: str = "") -> bool:
    """ROI only; shared city names alone are unverified, never positive."""
    return bool(location and _confirmed_roi(location) and
                not _country_conflict(location))


def is_visa_sponsor_location(location: str, cfg: Dict) -> Optional[str]:
    """Return regional scope for a *location* with word-boundary matches."""
    for region, key in (("asia", "visa_sponsor_countries_asia"),
                        ("europe", "visa_sponsor_countries_europe")):
        for c in cfg.get(key, []):
            if re.search(r"(?<!\w)" + re.escape(c) + r"(?!\w)", location, re.I):
                return region
    return None


def mentions_visa_sponsorship(description: str, cfg: Dict) -> bool:
    """Positive employer-supported sponsorship signal, not legal verification."""
    if not description or NEGATIVE_SPONSORSHIP.search(description):
        return False
    return bool(POSITIVE_SPONSORSHIP.search(description))


def scope_of(job: Dict, cfg: Dict) -> Optional[str]:
    """Classify conservatively using separate physical, country and eligibility evidence.

    Eligibility unknown is NOT an alertable scope; enrichment/manual review
    must precede seen marking. A location tag never proves employment rights.
    """
    loc_cfg = cfg.get('locations', {})
    location = str(job.get('location', '') or '')
    country = str(job.get('country', '') or '')
    physical = str(job.get('physical_location', '') or '')
    remote_area = str(job.get('remote_area', '') or '')
    restrictions = str(job.get('employer_restrictions', '') or '')
    sponsorship = str(job.get('sponsorship_terms', '') or '')
    description = str(job.get('description', '') or '')
    constraint_text = ' '.join((location, remote_area, restrictions, sponsorship, description))
    country_text = ' '.join((country, physical))

    # Explicit employment restrictions override positive geographical matches.
    # Employer text saying UK-only / US-only makes an Ireland location invalid.
    if (RESTRICTED_REMOTE.search(constraint_text) or RESTRICTED_REMOTE.search(country_text)
            or RESTRICTED_WORK_RESIDENCY.search(constraint_text)):
        return None
    if NI_PATTERN.search(' '.join((location, country, physical))):
        if not cfg.get('filtering', {}).get('international_candidates'):
            return None
        from sources.catalogue import eligibility
        signal = eligibility(job)
        return 'visa' if signal['sponsorship'] in ('employer_stated','source_reported') or signal['international_candidates']=='explicitly_considered' else None
    conflict = _country_conflict(location, country, physical)
    remote_listing = bool(re.match(r"\s*(?:fully\s+)?remote\b", location, re.I))
    # Even if another field asserts Ireland, unknown/non-Irish country values
    # are contradictory evidence requiring human verification.
    uncertain_country = bool(country.strip() and not _confirmed_roi_country(country))
    # A separate physical-location field with unresolvable geography cannot
    # silently override a confident country/office claim.
    uncertain_physical = bool(physical.strip() and not _confirmed_roi(physical)
                              and not ROI_CITY.fullmatch(physical.strip()))
    # Keep remote EU claims from overriding conflicting physical locations.
    if re.search(r'\bremote\b', location + ' ' + remote_area, re.I) and (
            _country_conflict(country, '', physical) or uncertain_country):
        return 'eligibility_unverified'
    # A "Remote - EU (Ireland eligible)" listing is not an Irish office.
    explicit_roi = bool(
        (not remote_listing and _confirmed_roi(location))
        or _confirmed_roi(physical)
        or (country and _confirmed_roi_country(country) and not remote_listing)
    )
    shared_city = bool(ROI_CITY.search(' '.join((location, physical))))
    if (explicit_roi or shared_city) and (conflict or uncertain_country or uncertain_physical):
        return 'eligibility_unverified'
    if loc_cfg.get('ireland', True) and explicit_roi:
        return 'ireland'
    # With only "Dublin" or "Cork" the country is still uncertain. Do not
    # claim ROI or mark the job seen; send it for manual enrichment instead.
    if shared_city and not remote_listing:
        return 'eligibility_unverified'

    area = ' '.join((location, remote_area))
    # EMEA contains non-EU countries; cannot imply EU work eligibility.
    if EMEA.search(area) and not (EU_MEMBER.search(remote_area) and 'only' in remote_area.lower()):
        return 'eligibility_unverified'
    if loc_cfg.get('eu_remote', True) and matches_any(area, EU_REMOTE_PATTERNS):
        return 'eu_remote'
    # Specific EU member(s) must be explicitly remote-work eligible.
    if (loc_cfg.get('eu_remote', True) and re.search(r'\bremote\b', area, re.I)
            and EU_MEMBER.search(remote_area) and
            re.search(r'\b(?:eligible|allowed|hiring|based|work from|only)\b', remote_area, re.I)):
        return 'eu_remote'
    if loc_cfg.get('remote_anywhere', True) and matches_any(area, REMOTE_ANYWHERE_PATTERNS):
        return 'remote'
    if cfg.get('filtering', {}).get('international_candidates'):
        from sources.catalogue import eligibility
        signal = eligibility(job)
        if signal['international_candidates']=='explicitly_considered':
            return 'international'
        if signal['sponsorship'] in ('employer_stated','source_reported'):
            region = is_visa_sponsor_location(location or physical,cfg)
            return 'asia' if region == 'asia' else 'visa'
    if loc_cfg.get('visa_sponsoring', True):
        region = is_visa_sponsor_location(location or physical, cfg)
        if region:
            if NEGATIVE_SPONSORSHIP.search(sponsorship + ' ' + description):
                return None
            if job.get('sponsors_visa') is True or mentions_visa_sponsorship(sponsorship + ' ' + description, cfg):
                return 'asia' if region == 'asia' else 'visa'
            if not description and not sponsorship:
                return 'visa_unverified'
    return None


# ── Top-level filter ────────────────────────────────────────────────────────

def filter_jobs(raw_jobs: List[Dict], cfg: Dict) -> tuple:
    """
    Returns (kept, unverified, counters).

    kept       — in-scope, early-career (or unspecified), relevant sector
    unverified — passes everything but sits in a visa country with no
                 description to check; caller may fetch descriptions and
                 re-run scope_of on them.
    """
    include_unspecified = cfg.get("filtering", {}).get("include_unspecified_seniority", True)

    kept, unverified = [], []
    counters = {"kept": 0, "senior": 0, "sector": 0, "out_of_scope": 0, "unverified": 0}

    for j in raw_jobs:
        title = j.get("title", "") or ""
        description = j.get("description", "") or ""

        if cfg.get("filtering", {}).get("technology_focus"):
            from sources.catalogue import ROLE
            if not ROLE.search(title):
                counters["sector"] += 1
                continue

        if is_rejected_sector(title):
            counters["sector"] += 1
            continue

        level = seniority_of(title, description)
        if level == "senior":
            counters["senior"] += 1
            continue
        if level == "unspecified" and not include_unspecified:
            counters["senior"] += 1
            continue

        scope = scope_of(j, cfg)
        if scope is None:
            counters["out_of_scope"] += 1
            continue

        j["seniority"] = level
        j["category"] = category_of(title)

        if scope in ("visa_unverified", "eligibility_unverified"):
            counters["unverified"] += 1
            unverified.append(j)
            continue

        j["scope"] = scope
        kept.append(j)
        counters["kept"] += 1

    return kept, unverified, counters
