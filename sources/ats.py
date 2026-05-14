"""
ATS source fetchers.

All return list[dict] with the unified job shape:
  {id, title, company, location, link, posted, source, description}

`description` is included where available so the scorer has something
better than just the title to work with.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Dict, List

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

TIMEOUT = 15


def _safe_get(url: str, **kw) -> requests.Response | None:
    """GET with a try/except; returns None on any error."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, **kw)
        if r.status_code == 200:
            return r
        return None
    except Exception:
        return None


# ── Greenhouse ──────────────────────────────────────────────────────────────

def fetch_greenhouse(company: str, slug: str) -> List[Dict]:
    r = _safe_get(
        f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    )
    if not r:
        return []
    try:
        jobs = r.json().get("jobs", [])
    except Exception:
        return []

    out = []
    for j in jobs:
        loc = j.get("location", {}).get("name", "") or ""
        out.append({
            "id":          f"gh_{slug}_{j['id']}",
            "title":       j.get("title", ""),
            "company":     company,
            "location":    loc or "Not specified",
            "link":        j.get("absolute_url", f"https://boards.greenhouse.io/{slug}"),
            "posted":      j.get("updated_at", "")[:10] or "Recent",
            "source":      "Greenhouse",
            "description": (j.get("content", "") or "")[:2000],
        })
    return out


# ── Lever ───────────────────────────────────────────────────────────────────

def fetch_lever(company: str, slug: str) -> List[Dict]:
    r = _safe_get(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if not r:
        return []
    try:
        jobs = r.json()
        if not isinstance(jobs, list):
            return []
    except Exception:
        return []

    out = []
    for j in jobs:
        cats = j.get("categories", {}) or {}
        loc = cats.get("location", "") or ""
        out.append({
            "id":          f"lv_{slug}_{j['id']}",
            "title":       j.get("text", ""),
            "company":     company,
            "location":    loc or "Not specified",
            "link":        j.get("hostedUrl", f"https://jobs.lever.co/{slug}"),
            "posted":      str(j.get("createdAt", "Recent"))[:10],
            "source":      "Lever",
            "description": (j.get("descriptionPlain", "") or "")[:2000],
        })
    return out


# ── Ashby ───────────────────────────────────────────────────────────────────

def fetch_ashby(company: str, slug: str) -> List[Dict]:
    # Ashby has a public job board API at this endpoint
    r = _safe_get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    if not r:
        return []
    try:
        data = r.json()
        jobs = data.get("jobs", [])
    except Exception:
        return []

    out = []
    for j in jobs:
        loc = j.get("locationName", "") or ""
        if not loc and j.get("isRemote"):
            loc = "Remote"
        out.append({
            "id":          f"ab_{slug}_{j.get('id', '')}",
            "title":       j.get("title", ""),
            "company":     company,
            "location":    loc or "Not specified",
            "link":        j.get("jobUrl", f"https://jobs.ashbyhq.com/{slug}"),
            "posted":      j.get("publishedDate", "")[:10] or "Recent",
            "source":      "Ashby",
            "description": (j.get("descriptionPlain", "") or "")[:2000],
        })
    return out


# ── Workable ────────────────────────────────────────────────────────────────

def fetch_workable(company: str, slug: str) -> List[Dict]:
    # Workable public account jobs feed
    r = _safe_get(f"https://apply.workable.com/api/v3/accounts/{slug}/jobs")
    if not r:
        return []
    try:
        data = r.json()
        jobs = data.get("results", [])
    except Exception:
        return []

    out = []
    for j in jobs:
        loc_obj = j.get("location") or {}
        loc_parts = [
            loc_obj.get("city", ""),
            loc_obj.get("region", ""),
            loc_obj.get("country", ""),
        ]
        loc = ", ".join(p for p in loc_parts if p) or "Not specified"
        shortcode = j.get("shortcode", "")
        out.append({
            "id":          f"wk_{slug}_{shortcode}",
            "title":       j.get("title", ""),
            "company":     company,
            "location":    loc,
            "link":        f"https://apply.workable.com/{slug}/j/{shortcode}/",
            "posted":      j.get("published", "")[:10] or "Recent",
            "source":      "Workable",
            "description": (j.get("description", "") or "")[:2000],
        })
    return out


# ── SmartRecruiters ─────────────────────────────────────────────────────────

def fetch_smartrecruiters(company: str, slug: str) -> List[Dict]:
    r = _safe_get(
        f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100"
    )
    if not r:
        return []
    try:
        data = r.json()
        jobs = data.get("content", [])
    except Exception:
        return []

    out = []
    for j in jobs:
        loc_obj = j.get("location") or {}
        loc = ", ".join(filter(None, [
            loc_obj.get("city", ""),
            loc_obj.get("region", ""),
            loc_obj.get("country", ""),
        ])) or "Not specified"
        job_id = j.get("id", "")
        out.append({
            "id":          f"sr_{slug}_{job_id}",
            "title":       j.get("name", ""),
            "company":     company,
            "location":    loc,
            "link":        f"https://jobs.smartrecruiters.com/{slug}/{job_id}",
            "posted":      j.get("releasedDate", "")[:10] or "Recent",
            "source":      "SmartRecruiters",
            "description": "",  # SR needs a second call for description; skip
        })
    return out


# ── Personio ────────────────────────────────────────────────────────────────

def fetch_personio(company: str, slug: str) -> List[Dict]:
    r = _safe_get(f"https://{slug}.jobs.personio.de/xml?language=en")
    if not r:
        return []
    try:
        root = ET.fromstring(r.text)
    except Exception:
        return []

    out = []
    for pos in root.findall(".//position"):
        try:
            title  = pos.findtext("name", "") or ""
            office = pos.findtext("office", "") or ""
            job_id = pos.findtext("id", "") or ""
            desc_parts = [j.text for j in pos.findall(".//jobDescription/value") if j.text]
            description = " ".join(desc_parts)[:2000]
            out.append({
                "id":          f"ps_{slug}_{job_id}",
                "title":       title,
                "company":     company,
                "location":    office or "Not specified",
                "link":        f"https://{slug}.jobs.personio.de/job/{job_id}",
                "posted":      "Recent",
                "source":      "Personio",
                "description": description,
            })
        except Exception:
            continue
    return out


# ── Workday ─────────────────────────────────────────────────────────────────

def fetch_workday(company: str, tenant: str, wd_n: int, ext_path: str) -> List[Dict]:
    """
    Workday is per-tenant. The public REST endpoint is:
      https://<tenant>.wd<N>.myworkdayjobs.com/wday/cxs/<tenant>/<ext_path>/jobs

    POST body with empty filters returns first page. We're being polite —
    only first 20 results per company per run.
    """
    url = (
        f"https://{tenant}.wd{wd_n}.myworkdayjobs.com/wday/cxs/"
        f"{tenant}/{ext_path}/jobs"
    )
    try:
        r = requests.post(
            url,
            json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""},
            headers={
                **HEADERS,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        jobs = data.get("jobPostings", [])
    except Exception:
        return []

    out = []
    base_view = f"https://{tenant}.wd{wd_n}.myworkdayjobs.com/en-US/{ext_path}"
    for j in jobs:
        ext_id = j.get("externalPath", "")
        title = j.get("title", "")
        loc = j.get("locationsText", "") or ""
        posted = j.get("postedOn", "") or "Recent"
        out.append({
            "id":          f"wd_{tenant}_{ext_id.split('/')[-1]}",
            "title":       title,
            "company":     company,
            "location":    loc or "Not specified",
            "link":        f"{base_view}{ext_id}",
            "posted":      posted,
            "source":      "Workday",
            "description": "",
        })
    return out


# ── Dispatcher ──────────────────────────────────────────────────────────────

FETCHERS = {
    "greenhouse":      fetch_greenhouse,
    "lever":           fetch_lever,
    "ashby":           fetch_ashby,
    "workable":        fetch_workable,
    "smartrecruiters": fetch_smartrecruiters,
    "personio":        fetch_personio,
}


def fetch_all_companies(companies_cfg: Dict, sleep_between: float = 0.5) -> List[Dict]:
    """Fetch from every standard ATS in the company config."""
    all_jobs: List[Dict] = []

    # Standard single-slug ATSes
    for ats, fetcher in FETCHERS.items():
        section = companies_cfg.get(ats, {})
        if not section:
            continue
        print(f"  → {ats}: {len(section)} companies")
        for company_name, slug in section.items():
            jobs = fetcher(company_name, slug)
            if jobs:
                print(f"    ✓ {company_name}: {len(jobs)} jobs")
            all_jobs.extend(jobs)
            time.sleep(sleep_between)

    # Workday (special tuple-args shape)
    workday_section = companies_cfg.get("workday_tenants", {})
    if workday_section:
        print(f"  → workday: {len(workday_section)} tenants")
        for company_name, params in workday_section.items():
            if not isinstance(params, list) or len(params) < 3:
                continue
            tenant, wd_n, ext_path = params[0], int(params[1]), params[2]
            jobs = fetch_workday(company_name, tenant, wd_n, ext_path)
            if jobs:
                print(f"    ✓ {company_name}: {len(jobs)} jobs")
            all_jobs.extend(jobs)
            time.sleep(sleep_between)

    return all_jobs
