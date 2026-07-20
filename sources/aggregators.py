"""
Aggregator APIs (NEW in v6).

These catch everything the direct company list misses — including jobs
posted on IrishJobs.ie, jobs.ie, Indeed etc., which the aggregators index
but which block direct scraping.

  Jooble     — free API key (https://jooble.org/api/about), covers IRELAND.
               Secret: JOOBLE_API_KEY. The single biggest recall win for
               Irish jobs outside the curated company list.
  Adzuna     — free API key (https://developer.adzuna.com), covers UK, DE,
               NL, FR, AT, PL, SG, IN and more (no Irish market).
               Secrets: ADZUNA_APP_ID, ADZUNA_APP_KEY.
  Arbeitnow  — no key needed. European jobs with an explicit
               visa_sponsorship flag — pre-verified sponsorship.
  Remotive   — no key needed. Remote jobs.
  RemoteOK   — no key needed. Remote jobs.

Every fetcher degrades gracefully: missing keys → skip with a log line.
"""

from __future__ import annotations

import html
import os
import re
from typing import Dict, List

import requests

TIMEOUT = 25
HEADERS = {"User-Agent": "job-tracker-v6 (personal graduate job alerts)"}

TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str, limit: int = 3000) -> str:
    return html.unescape(TAG_RE.sub(" ", text or ""))[:limit]


# ── Jooble (Ireland + worldwide) ────────────────────────────────────────────

def fetch_jooble(keywords: List[str], location: str = "Ireland") -> List[Dict]:
    key = os.environ.get("JOOBLE_API_KEY", "").strip()
    if not key:
        print("  ⏭  Jooble skipped (JOOBLE_API_KEY not set — free key at jooble.org/api/about)")
        return []

    out: List[Dict] = []
    for kw in keywords:
        try:
            r = requests.post(
                f"https://jooble.org/api/{key}",
                json={"keywords": kw, "location": location, "page": 1},
                headers=HEADERS, timeout=TIMEOUT,
            )
            if r.status_code != 200:
                continue
            jobs = r.json().get("jobs", [])
        except Exception:
            continue
        for j in jobs:
            jid = str(j.get("id", "")) or j.get("link", "")
            if not jid:
                continue
            out.append({
                "id":          f"jo_{jid}",
                "title":       j.get("title", ""),
                "company":     j.get("company", "") or "Unknown",
                "location":    j.get("location", "") or location,
                "link":        j.get("link", ""),
                "posted":      (j.get("updated", "") or "")[:10] or "Recent",
                "source":      "Jooble",
                "description": _strip_html(j.get("snippet", "")),
            })
    print(f"  ✓ Jooble ({location}): {len(out)} jobs across {len(keywords)} queries")
    return out


# ── Adzuna (UK / EU / SG — no Irish market) ─────────────────────────────────

def fetch_adzuna(keywords: List[str], countries: List[str], max_days_old: int = 2) -> List[Dict]:
    app_id = os.environ.get("ADZUNA_APP_ID", "").strip()
    app_key = os.environ.get("ADZUNA_APP_KEY", "").strip()
    if not app_id or not app_key:
        print("  ⏭  Adzuna skipped (ADZUNA_APP_ID / ADZUNA_APP_KEY not set — free at developer.adzuna.com)")
        return []

    out: List[Dict] = []
    for country in countries:
        for kw in keywords:
            try:
                r = requests.get(
                    f"https://api.adzuna.com/v1/api/jobs/{country}/search/1",
                    params={
                        "app_id": app_id, "app_key": app_key,
                        "what": kw, "results_per_page": 30,
                        "max_days_old": max_days_old,
                        "sort_by": "date",
                        "content-type": "application/json",
                    },
                    headers=HEADERS, timeout=TIMEOUT,
                )
                if r.status_code != 200:
                    continue
                results = r.json().get("results", [])
            except Exception:
                continue
            for j in results:
                jid = str(j.get("id", ""))
                if not jid:
                    continue
                out.append({
                    "id":          f"az_{country}_{jid}",
                    "title":       j.get("title", "").replace("<strong>", "").replace("</strong>", ""),
                    "company":     (j.get("company") or {}).get("display_name", "Unknown"),
                    "location":    (j.get("location") or {}).get("display_name", country.upper()),
                    "link":        j.get("redirect_url", ""),
                    "posted":      (j.get("created", "") or "")[:10] or "Recent",
                    "source":      "Adzuna",
                    "description": _strip_html(j.get("description", "")),
                })
    print(f"  ✓ Adzuna: {len(out)} jobs ({len(countries)} countries × {len(keywords)} queries)")
    return out


# ── Arbeitnow (Europe, pre-verified visa sponsorship) ───────────────────────

def fetch_arbeitnow(visa_only: bool = True, pages: int = 3) -> List[Dict]:
    out: List[Dict] = []
    url = "https://www.arbeitnow.com/api/job-board-api"
    params: Dict = {"visa_sponsorship": "true"} if visa_only else {}
    for page in range(1, pages + 1):
        try:
            r = requests.get(url, params={**params, "page": page}, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code != 200:
                break
            data = r.json().get("data", [])
        except Exception:
            break
        if not data:
            break
        for j in data:
            slug = j.get("slug", "")
            if not slug:
                continue
            out.append({
                "id":            f"an_{slug}",
                "title":         j.get("title", ""),
                "company":       j.get("company_name", "") or "Unknown",
                "location":      j.get("location", "") or "Germany",
                "link":          j.get("url", ""),
                "posted":        "Recent",
                "source":        "Arbeitnow",
                "description":   _strip_html(j.get("description", "")),
                "sponsors_visa": bool(j.get("visa_sponsorship", visa_only)),
            })
    print(f"  ✓ Arbeitnow (visa-sponsor jobs): {len(out)}")
    return out


# ── Remotive (remote) ───────────────────────────────────────────────────────

def fetch_remotive(limit: int = 100) -> List[Dict]:
    try:
        r = requests.get(f"https://remotive.com/api/remote-jobs?limit={limit}",
                         headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return []
        jobs = r.json().get("jobs", [])
    except Exception:
        return []
    out = []
    for j in jobs:
        jid = str(j.get("id", ""))
        if not jid:
            continue
        out.append({
            "id":          f"rv_{jid}",
            "title":       j.get("title", ""),
            "company":     j.get("company_name", "") or "Unknown",
            "location":    j.get("candidate_required_location", "") or "Remote",
            "link":        j.get("url", ""),
            "posted":      (j.get("publication_date", "") or "")[:10] or "Recent",
            "source":      "Remotive",
            "description": _strip_html(j.get("description", "")),
        })
    print(f"  ✓ Remotive: {len(out)} remote jobs")
    return out


# ── RemoteOK (remote) ───────────────────────────────────────────────────────

def fetch_remoteok() -> List[Dict]:
    try:
        r = requests.get("https://remoteok.com/api", headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception:
        return []
    out = []
    for j in data:
        if not isinstance(j, dict) or not j.get("id"):
            continue  # first element is a legal notice
        out.append({
            "id":          f"ro_{j['id']}",
            "title":       j.get("position", "") or j.get("title", ""),
            "company":     j.get("company", "") or "Unknown",
            "location":    j.get("location", "") or "Remote",
            "link":        j.get("url", "") or f"https://remoteok.com/remote-jobs/{j['id']}",
            "posted":      (j.get("date", "") or "")[:10] or "Recent",
            "source":      "RemoteOK",
            "description": _strip_html(j.get("description", "")),
        })
    print(f"  ✓ RemoteOK: {len(out)} remote jobs")
    return out
