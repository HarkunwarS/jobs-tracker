"""
LinkedIn public guest-search scraper (v6).

Changes vs v5:
  - Broader keyword sweep for Ireland (the full expanded keyword list from
    config) vs a SHORT list for non-Ireland locations — v5 burned ~half its
    runtime searching countries whose results were then auto-discarded.
  - NEW fetch_job_description(): pulls the description for a specific job
    from the guest jobPosting endpoint, so non-Ireland candidates can pass
    the visa-sponsorship phrase gate instead of being silently dropped.
    Capped per run to stay under LinkedIn's rate limits.
"""

from __future__ import annotations

import random
import re
import time
import urllib.parse
from typing import Dict, List

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.4 Safari/605.1.15"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IE,en;q=0.9",
}


def _search_url(keyword: str, location: str, seconds: int) -> str:
    params = {
        "keywords": keyword,
        "location": location,
        "f_TPR":    f"r{seconds}",
        "start":    0,
    }
    encoded = "&".join(f"{k}={urllib.parse.quote_plus(str(v))}" for k, v in params.items())
    return f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?{encoded}"


def fetch_linkedin(keyword: str, location: str = "Ireland", seconds: int = 7200) -> List[Dict]:
    """One search → list of job dicts. Returns [] on any failure."""
    url = _search_url(keyword, location, seconds)
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 429:
                if attempt == 0:
                    time.sleep(30 + random.uniform(0, 10))
                    continue
                return []
            if r.status_code != 200:
                return []
            break
        except Exception:
            return []
    else:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for card in soup.find_all("div", class_="base-card"):
        try:
            urn = card.get("data-entity-urn", "")
            job_id = urn.split(":")[-1] if urn else ""
            if not job_id:
                continue
            title_el   = card.find("h3", class_="base-search-card__title")
            company_el = card.find("h4", class_="base-search-card__subtitle")
            loc_el     = card.find("span", class_="job-search-card__location")
            link_el    = card.find("a", class_="base-card__full-link")
            time_el    = card.find("time")

            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue
            out.append({
                "id":          f"li_{job_id}",
                "li_job_id":   job_id,
                "title":       title,
                "company":     company_el.get_text(strip=True) if company_el else "Unknown",
                "location":    loc_el.get_text(strip=True) if loc_el else location,
                "link":        link_el["href"].split("?")[0] if link_el and link_el.get("href") else url,
                "posted":      (time_el.get("datetime", "") if time_el else "") or "Recent",
                "source":      "LinkedIn",
                "description": "",
            })
        except Exception:
            continue
    return out


def fetch_linkedin_sweep(
    ireland_keywords: List[str],
    abroad_keywords: List[str],
    abroad_locations: List[str],
    window_hours: int = 3,
    sleep_between: tuple = (2.5, 5.0),
) -> List[Dict]:
    """
    Full sweep: every keyword for Ireland, a short keyword list for the
    abroad locations. window_hours should exceed the run cadence so a
    delayed or skipped GitHub Actions run can't open a gap.
    """
    seconds = window_hours * 3600
    searches = [(kw, "Ireland") for kw in ireland_keywords]
    searches += [(kw, loc) for loc in abroad_locations for kw in abroad_keywords]

    all_jobs: List[Dict] = []
    print(f"  → LinkedIn: {len(searches)} searches "
          f"({len(ireland_keywords)} Ireland + {len(abroad_keywords)}×{len(abroad_locations)} abroad)")
    for kw, loc in searches:
        jobs = fetch_linkedin(kw, loc, seconds=seconds)
        if jobs:
            print(f"    ✓ '{kw}' @ {loc}: {len(jobs)}")
        all_jobs.extend(jobs)
        time.sleep(random.uniform(*sleep_between))
    return all_jobs


# ── Job description detail fetch (NEW) ──────────────────────────────────────

_MARKUP_RE = re.compile(r"\s+")


def fetch_job_description(job_id: str) -> str:
    """
    Guest endpoint for a single posting's detail card. Returns the plain-text
    description ('' on failure). Used only for the small set of jobs that
    need a description to pass the visa gate.
    """
    url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        el = soup.find("div", class_="show-more-less-html__markup")
        if not el:
            return ""
        return _MARKUP_RE.sub(" ", el.get_text(" ", strip=True))[:4000]
    except Exception:
        return ""


def enrich_descriptions(jobs: List[Dict], cap: int = 15,
                        sleep_between: tuple = (2.0, 4.0)) -> List[Dict]:
    """Fetch descriptions for up to `cap` LinkedIn jobs lacking one."""
    enriched = 0
    for j in jobs:
        if enriched >= cap:
            break
        if j.get("description") or not j.get("li_job_id"):
            continue
        desc = fetch_job_description(j["li_job_id"])
        if desc:
            j["description"] = desc
            enriched += 1
        time.sleep(random.uniform(*sleep_between))
    if enriched:
        print(f"  ✓ LinkedIn detail fetch: descriptions for {enriched} candidate job(s)")
    return jobs
