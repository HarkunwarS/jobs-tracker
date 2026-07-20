"""
Graduate-specific boards (NEW in v6).

gradireland.com — Ireland's main graduate board (Group GTI). Its listing
pages are server-rendered (Gatsby SSR), so plain requests + BeautifulSoup
works. Job links follow the pattern:

    /jobs/<title-slug>-<numeric-id>

and each card anchor contains the employer name and job title. We walk the
first N pages of /s/jobs/all/<page> (newest first) each run; the seen-cache
handles overlap between runs.
"""

from __future__ import annotations

import re
import time
from typing import Dict, List

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15"
    ),
    "Accept-Language": "en-IE,en;q=0.9",
}
TIMEOUT = 20

JOB_HREF_RE = re.compile(r"^/jobs/[\w-]+-(\d+)/?$")


def fetch_gradireland(pages: int = 3, sleep_between: float = 1.0) -> List[Dict]:
    """
    Scrape the first `pages` pages of gradireland's all-jobs listing.
    ~12 jobs per page; page 1 is the newest, so with the seen-cache
    3 pages per half-hourly run comfortably catches everything.
    """
    out: List[Dict] = []
    seen_ids = set()

    for page in range(1, pages + 1):
        url = f"https://gradireland.com/s/jobs/all/{page}" if page > 1 \
            else "https://gradireland.com/s/jobs/all"
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code != 200:
                break
            soup = BeautifulSoup(r.text, "html.parser")
        except Exception:
            break

        found_on_page = 0
        for a in soup.find_all("a", href=True):
            m = JOB_HREF_RE.match(a["href"])
            if not m:
                continue
            job_id = m.group(1)
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            # Card anchor text is a run-together string like:
            #   "R" + "Rentokil Initial" + "Graduate Pest Control Technician"
            #   + optional "17 days to apply" + "Save"
            # The href slug is the reliable title source; the longest text
            # chunk before it usually holds the employer.
            slug_title = a["href"].rsplit("/", 1)[-1]
            slug_title = re.sub(rf"-{job_id}/?$", "", slug_title).replace("-", " ").strip()
            title = slug_title.title()

            raw = a.get_text(" ", strip=True)
            raw = re.sub(r"\s*\d+\s+days? to apply\s*", " ", raw)
            raw = re.sub(r"\bSave\b\s*$", "", raw).strip()
            # Try to peel the employer off the front: the raw text starts with
            # a single-letter logo initial, then employer, then the title.
            company = "See listing"
            low_raw, low_title = raw.lower(), slug_title.lower()
            idx = low_raw.rfind(low_title[:20])  # locate title within raw text
            if idx > 1:
                company = raw[1:idx].strip(" -·|") or "See listing"

            out.append({
                "id":          f"gi_{job_id}",
                "title":       title,
                "company":     company,
                "location":    "Ireland",
                "link":        f"https://gradireland.com{a['href']}",
                "posted":      "Recent",
                "source":      "gradireland",
                "description": "",
            })
            found_on_page += 1

        if found_on_page == 0:
            break
        time.sleep(sleep_between)

    print(f"  ✓ gradireland: {len(out)} jobs from {pages} page(s)")
    return out
