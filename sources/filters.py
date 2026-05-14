"""
Filtering: location and seniority checks.

Fixes from v4:
  - is_ireland() now uses word boundaries, not substring (no more "ie" matching "pie")
  - is_entry_level() requires positive signal OR no senior signal, not just absence
  - Adds is_in_scope() for the expanded geography (Ireland/EU/remote/visa-sponsor)
"""

import re
from typing import Dict, List

# ── Compiled location patterns (word-boundary safe) ─────────────────────────

IRELAND_PATTERNS = [
    re.compile(r"\bireland\b", re.I),
    re.compile(r"\bdublin\b", re.I),
    re.compile(r"\bcork\b", re.I),
    re.compile(r"\bgalway\b", re.I),
    re.compile(r"\blimerick\b", re.I),
    re.compile(r"\bwaterford\b", re.I),
    re.compile(r"\bleinster\b", re.I),
    re.compile(r"\bmunster\b", re.I),
    re.compile(r"\bbelfast\b", re.I),  # NI — close enough, Stamp 2 can cross
    # ISO code: \bie\b would match too much (initialism). Skip it.
    # Use ", IE" or "(IE)" patterns instead:
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

# ── Compiled seniority patterns ─────────────────────────────────────────────

# Hard-reject phrases: multi-word matches only, avoids "lead" alone causing
# false positives on things like "Project Lead - Graduate Programme"
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

# Positive signals — when present, we override soft seniority words
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
    re.compile(r"\bi\b(?=\s*[-,\)]|$)", re.I),   # "Engineer I"
    re.compile(r"\bii\b(?=\s*[-,\)]|$)", re.I),  # "Engineer II"
]

# Mid-level signals — we ACCEPT these by default. Reason: most companies'
# "default" listing is mid-level, and as a postgrad you're competitive for
# them. Only hard-reject explicit senior+.
MID_LEVEL_SIGNALS = [
    re.compile(r"\bmid.?level\b", re.I),
    re.compile(r"\b[123]\+?\s*years\b", re.I),
]


def matches_any(text: str, patterns: List[re.Pattern]) -> bool:
    """True if any compiled pattern matches text."""
    return any(p.search(text) for p in patterns)


def is_ireland(location: str, title: str = "") -> bool:
    """True if the location (or title fallback) looks Irish."""
    combined = f"{location} {title}"
    return matches_any(combined, IRELAND_PATTERNS)


def is_eu_remote(location: str) -> bool:
    return matches_any(location, EU_REMOTE_PATTERNS)


def is_remote_anywhere(location: str) -> bool:
    return matches_any(location, REMOTE_ANYWHERE_PATTERNS)


def is_visa_sponsor_location(location: str, sponsor_countries: List[str]) -> bool:
    """True if location mentions one of the visa-sponsoring countries."""
    loc_low = location.lower()
    return any(c.lower() in loc_low for c in sponsor_countries)


def is_in_scope(location: str, title: str, cfg: Dict) -> str | None:
    """
    Returns a scope tag (ireland/eu_remote/remote/visa) if the job is in scope,
    or None if it should be filtered out.
    """
    loc_cfg = cfg.get("locations", {})
    if loc_cfg.get("ireland", True) and is_ireland(location, title):
        return "ireland"
    if loc_cfg.get("eu_remote", True) and is_eu_remote(location):
        return "eu_remote"
    if loc_cfg.get("remote_anywhere", True) and is_remote_anywhere(location):
        return "remote"
    if loc_cfg.get("visa_sponsoring", True):
        sponsors = cfg.get("visa_sponsor_countries", [])
        if is_visa_sponsor_location(location, sponsors):
            return "visa"
    return None


def is_too_senior(title: str) -> bool:
    """
    True if title is unambiguously a senior role we should reject.

    Logic: if it matches a hard-reject pattern AND lacks an entry-level signal,
    reject. This catches "Senior Data Engineer" but lets through "Graduate Lead
    Engineer Programme" or "Junior to Senior Software Engineer".
    """
    has_senior_signal = matches_any(title, HARD_REJECT_PHRASES)
    if not has_senior_signal:
        return False
    has_entry_signal = matches_any(title, ENTRY_LEVEL_SIGNALS)
    return not has_entry_signal


def matches_role_category(title: str, role_cfg: Dict) -> str | None:
    """
    Returns the category name (e.g. 'software_engineering') if the title
    matches any enabled category's keywords. None if no match.
    """
    title_low = title.lower()
    for category, settings in role_cfg.items():
        if not settings.get("enabled", True):
            continue
        for kw in settings.get("keywords", []):
            if kw.lower() in title_low:
                return category
    return None
