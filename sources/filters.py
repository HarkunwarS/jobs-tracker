"""
Filtering: location, seniority, role, and visa sponsorship checks.

Key change vs original:
  - Jobs outside Ireland now require EXPLICIT visa sponsorship language
    in the job description. Pure geography match is no longer enough.
  - Asia-Pacific locations added: Singapore, Malaysia, Japan, South Korea,
    Hong Kong, Taiwan, Thailand, Vietnam, Indonesia, Philippines, UAE.
  - is_in_scope() now calls mentions_visa_sponsorship() for all non-Ireland jobs.
"""

import re
from typing import Dict, List

# ── Ireland patterns (word-boundary safe) ───────────────────────────────────

IRELAND_PATTERNS = [
    re.compile(r"\bireland\b", re.I),
    re.compile(r"\bdublin\b", re.I),
    re.compile(r"\bcork\b", re.I),
    re.compile(r"\bgalway\b", re.I),
    re.compile(r"\blimerick\b", re.I),
    re.compile(r"\bwaterford\b", re.I),
    re.compile(r"\bleinster\b", re.I),
    re.compile(r"\bmunster\b", re.I),
    re.compile(r"\bbelfast\b", re.I),
    re.compile(r",\s*ie\b", re.I),
    re.compile(r"\(ie\)", re.I),
]

EU_REMOTE_PATTERNS = [
    re.compile(r"remote.{0,15}eu(rope)?", re.I),
    re.compile(r"eu(rope)?.{0,15}remote", re.I),
    re.compile(r"emea.{0,10}remote", re.I),
    re.compile(r"remote.{0,10}emea", re.I),
]

REMOTE_ANYWHERE_PATTERNS = [
    re.compile(r"\bremote\b.{0,20}\b(global|anywhere|worldwide|world wide)\b", re.I),
    re.compile(r"\b(global|anywhere|worldwide|world wide)\b.{0,20}\bremote\b", re.I),
    re.compile(r"\bfully remote\b", re.I),
    re.compile(r"\b100%\s*remote\b", re.I),
]

# ── Seniority patterns ───────────────────────────────────────────────────────

HARD_REJECT_PHRASES = [
    re.compile(r"\bsenior\b", re.I),
    re.compile(r"\bsr\.?\s+(software|data|engineer|developer|analyst|manager)", re.I),
    re.compile(r"\bstaff\s+(engineer|software|data|developer|scientist)", re.I),
    re.compile(r"\bprincipal\s+(engineer|software|data|developer|scientist|architect)", re.I),
    re.compile(r"\bdirector\b", re.I),
    re.compile(r"\b(vp|vice president)\b", re.I),
    re.compile(r"\bhead of\b", re.I),
    re.compile(r"\bchief\b", re.I),
    re.compile(r"\bdistinguished\b", re.I),
    re.compile(r"\b(5|6|7|8|9|10|11|12|15)\+?\s*years", re.I),
    re.compile(r"\bsenior\s+(software|data|engineer|developer)", re.I),
    re.compile(r"\blead\s+(\w+\s+)?(engineer|developer|architect|scientist|analyst)", re.I),
    re.compile(r"\bengineering manager\b", re.I),
]

ENTRY_LEVEL_SIGNALS = [
    re.compile(r"\bgraduate\b", re.I),
    re.compile(r"\bjunior\b", re.I),
    re.compile(r"\bassociate\b", re.I),
    re.compile(r"\bentry.?level\b", re.I),
    re.compile(r"\bintern(ship)?\b", re.I),
    re.compile(r"\btrainee\b", re.I),
    re.compile(r"\bnew grad\b", re.I),
    re.compile(r"\bearly career\b", re.I),
    re.compile(r"\b(level|l)\s*[12]\b", re.I),
    re.compile(r"\bi\b(?=\s*[-,\)]|$)", re.I),
    re.compile(r"\bii\b(?=\s*[-,\)]|$)", re.I),
]


def matches_any(text: str, patterns: List[re.Pattern]) -> bool:
    return any(p.search(text) for p in patterns)


def is_ireland(location: str, title: str = "") -> bool:
    combined = f"{location} {title}"
    return matches_any(combined, IRELAND_PATTERNS)


def is_eu_remote(location: str) -> bool:
    return matches_any(location, EU_REMOTE_PATTERNS)


def is_remote_anywhere(location: str) -> bool:
    return matches_any(location, REMOTE_ANYWHERE_PATTERNS)


def is_visa_sponsor_location(location: str, cfg: Dict) -> bool:
    """
    True if the location mentions any Europe or Asia visa-sponsor country/city.
    Both lists are combined from config.
    """
    loc_low = location.lower()
    europe = cfg.get("visa_sponsor_countries_europe", [])
    asia = cfg.get("visa_sponsor_countries_asia", [])
    all_countries = europe + asia
    return any(c.lower() in loc_low for c in all_countries)


def mentions_visa_sponsorship(description: str, cfg: Dict) -> bool:
    """
    Returns True if the job description explicitly mentions visa sponsorship,
    relocation support, or work permit assistance.

    This is the key gate for non-Ireland jobs — we don't want to send you
    jobs where the company has zero intention of sponsoring you.
    """
    if not description:
        return False
    desc_low = description.lower()
    phrases = cfg.get("visa_sponsorship_phrases", [])
    return any(phrase.lower() in desc_low for phrase in phrases)


def is_in_scope(location: str, title: str, description: str, cfg: Dict) -> str | None:
    """
    Returns a scope tag if the job is in scope, None if it should be filtered out.

    Ireland jobs: always in scope (you already have right to work there).
    EU Remote: in scope without sponsorship check (remote = no visa needed).
    Remote anywhere: same.
    Everything else (EU countries, Asia): MUST mention visa sponsorship in description.
    """
    loc_cfg = cfg.get("locations", {})

    # Ireland — always accept, no sponsorship check needed
    if loc_cfg.get("ireland", True) and is_ireland(location, title):
        return "ireland"

    # EU remote or fully remote — no visa issue, accept
    if loc_cfg.get("eu_remote", True) and is_eu_remote(location):
        return "eu_remote"
    if loc_cfg.get("remote_anywhere", True) and is_remote_anywhere(location):
        return "remote"

    # Non-Ireland physical location — only accept if:
    # 1. Location is in our target country list AND
    # 2. Description explicitly mentions visa sponsorship
    if loc_cfg.get("visa_sponsoring", True):
        if is_visa_sponsor_location(location, cfg):
            if mentions_visa_sponsorship(description, cfg):
                # Tag as asia or visa depending on which list matched
                asia_list = cfg.get("visa_sponsor_countries_asia", [])
                loc_low = location.lower()
                if any(c.lower() in loc_low for c in asia_list):
                    return "asia"
                return "visa"

    return None


def is_too_senior(title: str) -> bool:
    has_senior_signal = matches_any(title, HARD_REJECT_PHRASES)
    if not has_senior_signal:
        return False
    has_entry_signal = matches_any(title, ENTRY_LEVEL_SIGNALS)
    return not has_entry_signal


def matches_role_category(title: str, role_cfg: Dict) -> str | None:
    title_low = title.lower()
    for category, settings in role_cfg.items():
        if not settings.get("enabled", True):
            continue
        for kw in settings.get("keywords", []):
            if kw.lower() in title_low:
                return category
    return None
