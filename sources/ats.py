"""
ATS source fetchers (v6).

New in v6:
  - Jibe/iCIMS career sites (careers.sig.com and similar) via their
    JSON endpoint  https://<host>/api/jobs?page=N
  - Parallel fetching with a thread pool: the v5 sequential loop over
    ~150 companies took minutes; different companies live on different
    hosts, so parallelism is polite AND fast.
  - Workday page size raised 20 → 50.

All fetchers return list[dict] with the unified shape:
  {id, title, company, location, link, posted, source, description}
"""

from __future__ import annotations

import time
import hashlib
from datetime import datetime, timezone
from sources.coverage import tracked, request_result, partial
from sources.catalogue import plain
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
}
TIMEOUT = 20


def _safe_get(url: str, **kw) -> requests.Response | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, **kw)
        request_result(status=r.status_code)
        return r if r.status_code == 200 else None
    except Exception as exc:
        request_result(error=type(exc).__name__)
        return None


# ── Greenhouse ──────────────────────────────────────────────────────────────

def fetch_greenhouse(company: str, slug: str) -> List[Dict]:
    r = _safe_get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    if not r:
        return []
    try:
        jobs = r.json().get("jobs", [])
    except Exception:
        return []
    out = []
    for j in jobs:
        loc = (j.get("location") or {}).get("name", "") or "Not specified"
        out.append({
            "id":          f"gh_{slug}_{j['id']}",
            "title":       j.get("title", ""),
            "company":     company,
            "location":    loc,
            "link":        j.get("absolute_url", f"https://boards.greenhouse.io/{slug}"),
            "posted":      (j.get("first_published", "") or "")[:10] or None,
            "source":      "Greenhouse",
            "updated_at": j.get("updated_at"),
            "requisition_id": j.get("requisition_id"),
            "posted_kind": "published",
            "description": (j.get("content", "") or ""),
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
        loc = ((j.get("categories") or {}).get("location", "")) or "Not specified"
        out.append({
            "id":          f"lv_{slug}_{j['id']}",
            "title":       j.get("text", ""),
            "company":     company,
            "location":    loc,
            "link":        j.get("hostedUrl", f"https://jobs.lever.co/{slug}"),
            "posted":      datetime.fromtimestamp(j["createdAt"]/1000, timezone.utc).isoformat() if isinstance(j.get("createdAt"), (int,float)) else None,
            "source":      "Lever",
            "work_model": j.get("workplaceType"),
            "country": j.get("country"),
            "description": plain(j.get("descriptionPlain", "") or "") + " " + " ".join(plain(x.get("content", "")) for x in j.get("lists", [])) + " " + plain(j.get("additionalPlain", "")),
        })
    return out


# ── Ashby ───────────────────────────────────────────────────────────────────

def fetch_ashby(company: str, slug: str) -> List[Dict]:
    r = _safe_get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    if not r:
        return []
    try:
        jobs = r.json().get("jobs", [])
    except Exception:
        return []
    out = []
    for j in jobs:
        if j.get("isListed") is False: continue
        loc = j.get("location", "") or j.get("locationName", "") or ("Remote" if j.get("isRemote") else "Not specified")
        out.append({
            "id":          f"ab_{slug}_{j.get('id') or hashlib.sha256(j.get('jobUrl', '').encode()).hexdigest()[:20]}",
            "title":       j.get("title", ""),
            "company":     company,
            "location":    loc,
            "link":        j.get("jobUrl", f"https://jobs.ashbyhq.com/{slug}"),
            "posted":      (j.get("publishedAt", "") or "")[:10] or None,
            "source":      "Ashby",
            "country": (j.get("address", {}).get("postalAddress") or {}).get("addressCountry"),
            "work_model": j.get("workplaceType"),
            "employment_type": j.get("employmentType"),
            "salary": j.get("compensation"),
            "description": (j.get("descriptionPlain", "") or ""),
        })
    return out


# ── Workable ────────────────────────────────────────────────────────────────

def fetch_workable(company: str, slug: str) -> List[Dict]:
    r = _safe_get(f"https://apply.workable.com/api/v3/accounts/{slug}/jobs")
    if not r:
        return []
    try:
        jobs = r.json().get("results", [])
    except Exception:
        return []
    out = []
    for j in jobs:
        loc_obj = j.get("location") or {}
        loc = ", ".join(p for p in [loc_obj.get("city", ""), loc_obj.get("region", ""),
                                    loc_obj.get("country", "")] if p) or "Not specified"
        shortcode = j.get("shortcode", "")
        out.append({
            "id":          f"wk_{slug}_{shortcode}",
            "title":       j.get("title", ""),
            "company":     company,
            "location":    loc,
            "link":        f"https://apply.workable.com/{slug}/j/{shortcode}/",
            "posted":      (j.get("published", "") or "")[:10] or "Recent",
            "source":      "Workable",
            "description": (j.get("description", "") or ""),
        })
    return out


# ── SmartRecruiters ─────────────────────────────────────────────────────────

def fetch_smartrecruiters(company: str, slug: str) -> List[Dict]:
    jobs, offset, seen_pages = [], 0, set()
    end = time.monotonic() + 120
    while True:
        if time.monotonic() >= end:
            partial("SmartRecruiters pagination time budget exhausted"); break
        r = _safe_get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset={offset}")
        if r is None: break
        payload = r.json()
        batch = payload.get("content", [])
        if not batch: break
        ids = tuple(j.get("id") for j in batch)
        if ids in seen_pages:
            partial("Repeated pagination page"); break
        seen_pages.add(ids); jobs.extend(batch); offset += len(batch)
        if offset >= payload.get("totalFound", offset + 1): break
    out = []
    for j in jobs:
        loc_obj = j.get("location") or {}
        loc = ", ".join(filter(None, [loc_obj.get("city", ""), loc_obj.get("region", ""),
                                      loc_obj.get("country", "")])) or "Not specified"
        job_id = j.get("id", "")
        out.append({
            "id":          f"sr_{slug}_{job_id}",
            "title":       j.get("name", ""),
            "company":     company,
            "location":    loc,
            "link":        f"https://jobs.smartrecruiters.com/{slug}/{job_id}",
            "posted":      (j.get("releasedDate", "") or "")[:10] or "Recent",
            "source":      "SmartRecruiters",
            "country": loc_obj.get("country"),
            "detail_api": f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{job_id}",
            "description": "",
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
            job_id = pos.findtext("id", "") or ""
            desc = " ".join(v.text for v in pos.findall(".//jobDescription/value") if v.text)
            out.append({
                "id":          f"ps_{slug}_{job_id}",
                "title":       pos.findtext("name", "") or "",
                "company":     company,
                "location":    pos.findtext("office", "") or "Not specified",
                "link":        f"https://{slug}.jobs.personio.de/job/{job_id}",
                "posted":      "Recent",
                "source":      "Personio",
                "description": desc,
            })
        except Exception:
            continue
    return out


# ── Jibe / iCIMS career sites (NEW — this is what SIG uses) ─────────────────

def fetch_jibe(company: str, host: str, pages: int = 0) -> List[Dict]:
    """
    Jibe-powered career sites (e.g. careers.sig.com) expose a JSON search
    endpoint at https://<host>/api/jobs?page=N. Response shape:
      {"jobs": [{"data": {"title", "city"/"location_name", "slug"/"req_id",
                 "description", "posted_date"/"create_date", ...}}, ...]}
    Field names vary slightly per tenant, so we probe several keys.
    """
    out: List[Dict] = []
    page, fetched_ids = 0, set()
    end = time.monotonic() + 120
    while not pages or page < pages:
        if time.monotonic() >= end:
            partial("Jibe pagination time budget exhausted"); break
        r = _safe_get(f"https://{host}/api/jobs?page={page}&sortBy=posted_date&descending=true")
        if not r:
            break
        try:
            payload = r.json()
        except Exception:
            break
        jobs = payload.get("jobs", [])
        if not jobs:
            break
        ids = tuple(str(w.get("data", w).get("req_id", w.get("data", w).get("id", w.get("data", w).get("slug")))) for w in jobs)
        if ids in fetched_ids:
            partial("Repeated Jibe page"); break
        fetched_ids.add(ids)
        for wrapper in jobs:
            d = wrapper.get("data", wrapper) or {}
            title = d.get("title", "")
            if not title:
                continue
            loc = (d.get("full_location") or d.get("location_name") or d.get("city")
                   or ", ".join(filter(None, [d.get("city", ""), d.get("country", "")]))
                   or "Not specified")
            slug = d.get("slug", "") or str(d.get("req_id", "") or d.get("id", ""))
            link = d.get("apply_url") or d.get("canonical_url") or f"https://{host}/job/{slug}"
            if link.startswith("/"):
                link = f"https://{host}{link}"
            posted = (d.get("posted_date") or d.get("create_date") or d.get("update_date") or "")[:10]
            out.append({
                "id":          f"jb_{host}_{slug}",
                "title":       title,
                "company":     company,
                "location":    str(loc),
                "link":        link,
                "posted":      posted or "Recent",
                "source":      "CareerSite",
                "description": (d.get("description", "") or ""),
            })
        # Stop early if the API reports fewer total pages
        total_pages = payload.get("totalPages") or payload.get("pageCount")
        if total_pages and page + 1 >= int(total_pages):
            break
        page += 1
        time.sleep(0.3)
    return out


# ── Workday ─────────────────────────────────────────────────────────────────

def fetch_workday(company: str, tenant: str, wd_n: int, ext_path: str) -> List[Dict]:
    url = f"https://{tenant}.wd{wd_n}.myworkdayjobs.com/wday/cxs/{tenant}/{ext_path}/jobs"
    jobs, offset, seen_pages = [], 0, set()
    end = time.monotonic() + 120
    while True:
        if time.monotonic() >= end:
            partial("Workday pagination time budget exhausted"); break
        try:
            r = requests.post(url, json={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": ""},
                              headers={**HEADERS,"Content-Type":"application/json"}, timeout=TIMEOUT)
            request_result(status=r.status_code)
            if r.status_code != 200: break
            payload = r.json(); batch = payload.get("jobPostings", [])
            if not batch: break
            ids = tuple(j.get("externalPath") for j in batch)
            if ids in seen_pages:
                partial("Repeated pagination page"); break
            seen_pages.add(ids); jobs.extend(batch); offset += len(batch)
            if offset >= payload.get("total", offset + 1): break
        except requests.RequestException as exc:
            request_result(error=type(exc).__name__); break
    out = []
    base_view = f"https://{tenant}.wd{wd_n}.myworkdayjobs.com/en-US/{ext_path}"
    for j in jobs:
        ext_id = j.get("externalPath", "")
        out.append({
            "id":          f"wd_{tenant}_{ext_id.split('/')[-1]}",
            "title":       j.get("title", ""),
            "company":     company,
            "location":    j.get("locationsText", "") or "Not specified",
            "link":        f"{base_view}{ext_id}",
            "posted":      j.get("postedOn", "") or "Recent",
            "source":      "Workday",
            "detail_api": url.removesuffix("/jobs") + ext_id,
            "requisition_id": (j.get("bulletFields") or [None])[0],
            "description": "",
        })
    return out


# ── Parallel dispatcher ─────────────────────────────────────────────────────

FETCHERS = {
    "greenhouse":      fetch_greenhouse,
    "lever":           fetch_lever,
    "ashby":           fetch_ashby,
    "workable":        fetch_workable,
    "smartrecruiters": fetch_smartrecruiters,
    "personio":        fetch_personio,
}


def fetch_all_companies(companies_cfg: Dict, max_workers: int = 12) -> List[Dict]:
    """
    Fetch every configured company in parallel. Each task hits a different
    host (or a major API designed for this traffic), so a modest pool is
    both fast and polite. v5's sequential loop took minutes; this takes
    seconds.
    """
    tasks = []  # (label, callable)

    for ats, fetcher in FETCHERS.items():
        for company_name, slug in (companies_cfg.get(ats) or {}).items():
            tasks.append((f"{ats}:{company_name}",
                          lambda f=fetcher, c=company_name, s=slug: f(c, s)))

    for company_name, host in (companies_cfg.get("jibe") or {}).items():
        tasks.append((f"jibe:{company_name}",
                      lambda c=company_name, h=host: fetch_jibe(c, h)))

    for company_name, params in (companies_cfg.get("workday_tenants") or {}).items():
        if isinstance(params, list) and len(params) >= 3:
            tenant, wd_n, ext_path = params[0], int(params[1]), params[2]
            tasks.append((f"workday:{company_name}",
                          lambda c=company_name, t=tenant, n=wd_n, e=ext_path:
                          fetch_workday(c, t, n, e)))

    all_jobs: List[Dict] = []
    print(f"  → {len(tasks)} company fetch tasks, {max_workers} workers")
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(tracked, label, fn): label for label, fn in tasks}
        for fut in as_completed(futures):
            label = futures[fut]
            try:
                jobs = fut.result()
            except Exception as e:
                print(f"    ⚠️  {label}: {e}")
                continue
            if jobs:
                all_jobs.extend(jobs)
    print(f"  ✓ ATS/company sources: {len(all_jobs)} jobs")
    return all_jobs
