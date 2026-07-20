"""
Networking events (NEW in v6) — Cork/Ireland tech & careers events.

Sources:
  - Meetup group iCal feeds: every public Meetup group exposes
    https://www.meetup.com/<group>/events/ical/  — no API key needed.
    Configured groups (config.yaml → events.meetup_groups) include Cork AI,
    Cork Devs, Cork Big Data & Analytics, Python Ireland.
  - gradireland.com/events — careers fairs & employer events (scraped).

A minimal iCal parser is used instead of an extra dependency: VEVENT blocks
are line-based and we only need DTSTART / SUMMARY / URL / LOCATION.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from typing import Dict, List

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15"
    ),
}
TIMEOUT = 20


def _unfold_ical(text: str) -> List[str]:
    """RFC 5545 line unfolding: continuation lines start with a space/tab."""
    lines: List[str] = []
    for raw in text.splitlines():
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _parse_dt(value: str) -> datetime | None:
    value = value.strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def parse_ical_events(text: str) -> List[Dict]:
    events, current = [], None
    for line in _unfold_ical(text):
        if line.startswith("BEGIN:VEVENT"):
            current = {}
        elif line.startswith("END:VEVENT"):
            if current and current.get("start") and current.get("title"):
                events.append(current)
            current = None
        elif current is not None and ":" in line:
            key, _, value = line.partition(":")
            key = key.split(";")[0].upper()
            if key == "DTSTART":
                current["start"] = _parse_dt(value)
            elif key == "SUMMARY":
                current["title"] = value.strip()
            elif key == "URL":
                current["link"] = value.strip()
            elif key == "LOCATION":
                current["location"] = value.replace("\\,", ",").strip()
    return events


def fetch_meetup_events(groups: List[str], days_ahead: int = 45) -> List[Dict]:
    now, horizon = datetime.now(), datetime.now() + timedelta(days=days_ahead)
    out: List[Dict] = []
    for group in groups:
        url = f"https://www.meetup.com/{group}/events/ical/"
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code != 200 or "BEGIN:VCALENDAR" not in r.text:
                print(f"    ⚠️  Meetup feed unavailable: {group}")
                continue
        except Exception:
            print(f"    ⚠️  Meetup feed failed: {group}")
            continue
        for ev in parse_ical_events(r.text):
            start = ev["start"]
            if not (now - timedelta(hours=12) <= start <= horizon):
                continue
            out.append({
                "id":       f"mu_{group}_{start:%Y%m%d%H%M}",
                "title":    ev["title"],
                "when":     start.strftime("%a %d %b, %H:%M"),
                "start":    start,
                "where":    ev.get("location", "See event page"),
                "link":     ev.get("link", f"https://www.meetup.com/{group}/events/"),
                "group":    group,
                "source":   "Meetup",
            })
        time.sleep(0.5)
    return out


GRADIRELAND_EVENT_RE = re.compile(r"^/events/[\w-]+-?(\d*)/?$")


def fetch_gradireland_events() -> List[Dict]:
    """Careers fairs / employer events listed on gradireland.com/events."""
    out: List[Dict] = []
    try:
        r = requests.get("https://gradireland.com/events", headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return out
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception:
        return out

    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not GRADIRELAND_EVENT_RE.match(href) or href in seen:
            continue
        seen.add(href)
        title = a.get_text(" ", strip=True)
        title = re.sub(r"\bSave\b\s*$", "", title).strip()
        if not title or len(title) < 4:
            slug = href.rsplit("/", 1)[-1]
            title = re.sub(r"-\d+$", "", slug).replace("-", " ").title()
        out.append({
            "id":     f"gie_{href}",
            "title":  title[:120],
            "when":   "See event page",
            "start":  None,
            "where":  "Ireland",
            "link":   f"https://gradireland.com{href}",
            "group":  "gradireland",
            "source": "gradireland",
        })
    return out[:15]


def collect_events(cfg: Dict) -> List[Dict]:
    ev_cfg = cfg.get("events", {})
    events: List[Dict] = []
    groups = ev_cfg.get("meetup_groups", [])
    if groups:
        print(f"  → Meetup: {len(groups)} groups")
        events.extend(fetch_meetup_events(groups, days_ahead=int(ev_cfg.get("days_ahead", 45))))
    if ev_cfg.get("gradireland_events", True):
        gi = fetch_gradireland_events()
        print(f"  → gradireland events: {len(gi)}")
        events.extend(gi)
    dated = sorted([e for e in events if e["start"]], key=lambda e: e["start"])
    undated = [e for e in events if not e["start"]]
    return dated + undated
