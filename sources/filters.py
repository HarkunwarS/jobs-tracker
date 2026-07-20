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
        if DESC_SENIOR_PATTERN.search(description):
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

IRELAND_PATTERNS = [re.compile(p, re.I) for p in [
    r"\bireland\b", r"\bdublin\b", r"\bcork\b", r"\bgalway\b", r"\blimerick\b",
    r"\bwaterford\b", r"\bkilkenny\b", r"\bathlone\b", r"\bsligo\b", r"\bdundalk\b",
    r"\bshannon\b", r"\bleinster\b", r"\bmunster\b", r"\bconnacht\b",
    r",\s*ie\b", r"\(ie\)", r"\bbelfast\b", r"\bderry\b", r"\bnorthern ireland\b",
]]

EU_REMOTE_PATTERNS = [re.compile(p, re.I) for p in [
    r"remote.{0,15}\beu(rope(an)?)?\b", r"\beu(rope(an)?)?\b.{0,15}remote",
    r"\bemea\b.{0,10}remote", r"remote.{0,10}\bemea\b",
]]

REMOTE_ANYWHERE_PATTERNS = [re.compile(p, re.I) for p in [
    r"\bremote\b.{0,20}\b(global|anywhere|worldwide|world.?wide)\b",
    r"\b(global|anywhere|worldwide|world.?wide)\b.{0,20}\bremote\b",
    r"\bfully remote\b", r"\b100%\s*remote\b", r"^remote$",
]]


def matches_any(text: str, patterns) -> bool:
    return any(p.search(text) for p in patterns)


def is_ireland(location: str, title: str = "") -> bool:
    return matches_any(f"{location} {title}", IRELAND_PATTERNS)


def is_visa_sponsor_location(location: str, cfg: Dict) -> Optional[str]:
    """Return 'europe' / 'asia' if the location matches a target country, else None."""
    loc_low = location.lower()
    for c in cfg.get("visa_sponsor_countries_asia", []):
        if c.lower() in loc_low:
            return "asia"
    for c in cfg.get("visa_sponsor_countries_europe", []):
        if c.lower() in loc_low:
            return "europe"
    return None


def mentions_visa_sponsorship(description: str, cfg: Dict) -> bool:
    if not description:
        return False
    desc_low = description.lower()
    return any(p.lower() in desc_low for p in cfg.get("visa_sponsorship_phrases", []))


def scope_of(job: Dict, cfg: Dict) -> Optional[str]:
    """
    Scope tags (priority order): ireland > eu_remote > remote > visa/asia.
    None = out of scope.

    Jobs carrying a pre-verified sponsorship flag from their source
    (job["sponsors_visa"] is True, e.g. Arbeitnow) skip the phrase gate.
    Jobs with an empty description in a target country are tagged
    'visa_unverified' so the pipeline can decide to fetch the description
    (LinkedIn detail fetch) instead of silently dropping them.
    """
    loc_cfg = cfg.get("locations", {})
    location = job.get("location", "") or ""
    title = job.get("title", "") or ""
    description = job.get("description", "") or ""

    if loc_cfg.get("ireland", True) and is_ireland(location, title):
        return "ireland"
    if loc_cfg.get("eu_remote", True) and matches_any(location, EU_REMOTE_PATTERNS):
        return "eu_remote"
    if loc_cfg.get("remote_anywhere", True) and matches_any(location, REMOTE_ANYWHERE_PATTERNS):
        return "remote"

    if loc_cfg.get("visa_sponsoring", True):
        region = is_visa_sponsor_location(location, cfg)
        if region:
            tag = "asia" if region == "asia" else "visa"
            if job.get("sponsors_visa"):            # source pre-verified it
                return tag
            if mentions_visa_sponsorship(description, cfg):
                return tag
            if not description:
                return "visa_unverified"            # candidate for detail fetch
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

        if scope == "visa_unverified":
            counters["unverified"] += 1
            unverified.append(j)
            continue

        j["scope"] = scope
        kept.append(j)
        counters["kept"] += 1

    return kept, unverified, counters
