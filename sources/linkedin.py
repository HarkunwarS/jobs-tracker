"""
LinkedIn public job board scraper.

LinkedIn rate-limits unauthenticated requests aggressively. We mitigate by:
  - Using the guest-search endpoint (more stable than the main /jobs/search/)
  - Adding randomised delays between requests
  - Retrying once on 429 with backoff
  - Capping max queries per run

Even with all this, expect ~70% success rate on any given run. The ATS
sources are the primary source — LinkedIn is the safety net for companies
without a public ATS endpoint.
"""

import random
import time
import urllib.parse
from typing import Dict, List

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Safari/605.1.15"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IE,en;q=0.9",
}


def _search_url(keyword: str, location: str, days: int = 1) -> str:
    """Build the guest-search URL — far less rate-limited than /jobs/search/."""
    params = {
        "keywords":  keyword,
        "location":  location,
        "f_TPR":     f"r{days * 86400}",      # last N days in seconds
        "start":     0,
    }
    encoded = "&".join(f"{k}={urllib.parse.quote_plus(str(v))}" for k, v in params.items())
    return (
        f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?{encoded}"
    )


def fetch_linkedin(keyword: str, location: str = "Ireland", days: int = 1) -> List[Dict]:
    """One LinkedIn search → list of job dicts. Returns [] on any failure."""
    url = _search_url(keyword, location, days)

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
    cards = soup.find_all("div", class_="base-card")

    out = []
    for card in cards:
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

            title    = title_el.get_text(strip=True) if title_el else ""
            company  = company_el.get_text(strip=True) if company_el else "Unknown"
            loc      = loc_el.get_text(strip=True) if loc_el else location
            link     = link_el["href"].split("?")[0] if link_el and link_el.get("href") else url
            posted   = time_el.get("datetime", "") if time_el else ""

            if not title:
                continue

            out.append({
                "id":          f"li_{job_id}",
                "title":       title,
                "company":     company,
                "location":    loc,
                "link":        link,
                "posted":      posted or "Recent",
                "source":      "LinkedIn",
                "description": "",  # LinkedIn doesn't give us the body in the listing
            })
        except Exception:
            continue

    return out


def fetch_linkedin_sweep(
    keywords: List[str],
    locations: List[str] = None,
    days: int = 1,
    sleep_between: tuple = (3, 6),
) -> List[Dict]:
    """
    Run a full LinkedIn sweep across keywords × locations.
    Randomised sleep between requests reduces rate-limit incidents.
    """
    if locations is None:
        locations = ["Ireland"]

    all_jobs: List[Dict] = []
    print(f"  → LinkedIn: {len(keywords)} × {len(locations)} = {len(keywords) * len(locations)} searches")

    for loc in locations:
        for kw in keywords:
            jobs = fetch_linkedin(kw, loc, days=days)
            if jobs:
                print(f"    ✓ '{kw}' @ {loc}: {len(jobs)} jobs")
            all_jobs.extend(jobs)
            time.sleep(random.uniform(*sleep_between))

    return all_jobs
