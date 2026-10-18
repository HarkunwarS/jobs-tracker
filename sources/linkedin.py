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
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from sources.coverage import tracked, request_result, partial

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.4 Safari/605.1.15"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IE,en;q=0.9",
}


def _search_url(keyword: str, location: str, seconds: int, start: int = 0) -> str:
    params = {
        "keywords": keyword,
        "location": location,
        "f_TPR":    f"r{seconds}",
        "start":    start,
    }
    encoded = "&".join(f"{k}={urllib.parse.quote_plus(str(v))}" for k, v in params.items())
    return f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?{encoded}"


def fetch_linkedin(keyword: str, location: str = "Ireland", seconds: int = 7200,
                   pages: int = 2) -> List[Dict]:
    """Search multiple public guest-result pages; deduplicate by LinkedIn ID.

    Guest endpoint is not guaranteed to return all matching results, and
    HTTP/429 responses are not proof of an empty jobs market.
    """
    out: List[Dict] = []
    seen = set()
    page=0; end=time.monotonic()+45
    while not pages or page < pages:
        if time.monotonic()>=end:
            partial("LinkedIn query time budget exhausted");break
        url = _search_url(keyword, location, seconds, start=page * 25)
        for attempt in range(2):
            try:
                r = requests.get(url, headers=HEADERS, timeout=15)
                request_result(status=r.status_code)
                if r.status_code == 429:
                    print(f"  ⚠️  LinkedIn throttled: {keyword!r} @ {location}")
                    return out
                if r.status_code != 200:
                    print(f"  ⚠️  LinkedIn HTTP {r.status_code}: {keyword!r} @ {location}")
                    return out
                break
            except requests.RequestException as exc:
                request_result(error=type(exc).__name__)
                print(f"  ⚠️  LinkedIn request error: {type(exc).__name__}")
                return out
        else:
            return out

        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.find_all("div", class_="base-card")
        previous=len(seen)
        for card in cards:
            try:
                urn = card.get("data-entity-urn", "")
                job_id = urn.split(":")[-1] if urn else ""
                if not job_id or job_id in seen:
                    continue
                title_el = card.find("h3", class_="base-search-card__title")
                company_el = card.find("h4", class_="base-search-card__subtitle")
                loc_el = card.find("span", class_="job-search-card__location")
                link_el = card.find("a", class_="base-card__full-link")
                time_el = card.find("time")
                title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue
                seen.add(job_id)
                out.append({
                    "id": f"li_{job_id}", "li_job_id": job_id, "title": title,
                    "company": company_el.get_text(strip=True) if company_el else "Unknown",
                    "location": loc_el.get_text(strip=True) if loc_el else location,
                    "link": link_el["href"].split("?")[0] if link_el and link_el.get("href") else url,
                    "posted": (time_el.get("datetime", "") if time_el else "") or "Recent",
                    "source": "LinkedIn", "description": "",
                })
            except (KeyError, AttributeError, ValueError):
                continue
        if len(cards) < 25 or len(seen)==previous:
            break
        page+=1
    if pages and page>=pages:partial("Configured LinkedIn page limit reached")
    return out


def lookback_hours(last_sweep: str | None, now: datetime | None = None,
                   minimum: int = 96, maximum: int = 168) -> int:
    """Cover weekdays, 2+ day weekend gaps and delayed Actions schedules.

    Always overlap previous sweeps for recovery; the seen-cache removes repeats.
    Cap at seven days because LinkedIn guest date filters may reject larger spans.
    """
    now = now or datetime.now(timezone.utc)
    if not last_sweep:
        return minimum
    try:
        last = datetime.fromisoformat(last_sweep.replace("Z", "+00:00"))
        if last.tzinfo is None:
            raise ValueError("naive timestamp")
        elapsed = max(0.0, (now - last).total_seconds() / 3600.0)
    except ValueError:
        return maximum
    if elapsed > maximum:
        print(f"  ⚠️  LinkedIn sweep gap {elapsed:.0f}h exceeds max {maximum}h; complete backfill unverified")
    return min(maximum, max(minimum, int(elapsed + 24.99)))


def fetch_linkedin_sweep(
    ireland_keywords: List[str], abroad_keywords: List[str],
    abroad_locations: List[str], window_hours: int = 96,
    sleep_between: tuple = (2.5, 5.0), pages_per_search: int = 2,
) -> List[Dict]:
    """Overlapping 4–7 day discovery with in-run ID deduplication."""
    seconds = window_hours * 3600
    searches = [(kw, "Ireland") for kw in ireland_keywords]
    searches += [(kw, loc) for loc in abroad_locations for kw in abroad_keywords]
    all_jobs: List[Dict] = []
    seen_ids = set()
    print(f"  → LinkedIn: {len(searches)} searches, {window_hours}h lookback, "
          f"{'time-budgeted pagination' if not pages_per_search else str(pages_per_search)+' pages per query'}")
    end=time.monotonic()+600
    for kw, loc in searches:
        if time.monotonic()>=end:
            tracked("LinkedIn:"+loc+":"+kw,lambda: (partial("Sweep time budget exhausted; query deferred"),[])[1])
            continue
        jobs = tracked("LinkedIn:"+loc+":"+kw,lambda: fetch_linkedin(kw, loc, seconds=seconds, pages=pages_per_search))
        if jobs:
            print(f"    ✓ {kw!r} @ {loc}: {len(jobs)}")
        for job in jobs:
            if job["id"] not in seen_ids:
                seen_ids.add(job["id"])
                all_jobs.append(job)
        if sleep_between[1] > 0:
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
