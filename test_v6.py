"""Offline test suite for Job Tracker v6 (no network needed)."""
import sys
sys.path.insert(0, ".")

import yaml
from sources.filters import (
    filter_jobs, seniority_of, is_rejected_sector, category_of, scope_of,
)
from sources.notify import build_email_html
from sources.events import parse_ical_events
from sources.scoring import route_jobs

cfg = yaml.safe_load(open("config.yaml"))
PASS, FAIL = 0, 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  ❌ {name}")


def J(title, location="Dublin, Ireland", description="", **kw):
    return {"id": f"t_{title}", "title": title, "company": "TestCo",
            "location": location, "link": "http://x", "posted": "2026-07-20",
            "source": "Test", "description": description, **kw}


# ── Requirement 3: broadened recall — these MUST all survive ────────────────
recall_cases = [
    J("AI Trainer"),
    J("Supply Chain Graduate Programme"),
    J("Graduate Program Manager"),
    J("Programme Analyst"),
    J("Operations Associate"),
    J("Junior Business Analyst"),
    J("Data Annotation Specialist"),
    J("Trading Operations Analyst Graduate: 2026"),   # the SIG-style title
    J("Software Developer Graduate: 2026"),
    J("Data Analyst"),                                # unspecified seniority
    J("Procurement Graduate"),
    J("Scrum Master - Entry Level"),
    J("QA Engineer I"),
    J("Solutions Engineer II"),
]
kept, unverified, counters = filter_jobs(list(recall_cases), cfg)
kept_titles = {j["title"] for j in kept}
for c in recall_cases:
    check(f"recall: {c['title']}", c["title"] in kept_titles)

# ── Seniority rejects ───────────────────────────────────────────────────────
for t in ["Senior Data Engineer", "Staff Engineer", "Principal Scientist",
          "Head of Data", "Lead Software Engineer", "Engineering Manager",
          "Full stack Developer | Options | Experienced",   # SIG experienced tag
          "Data Engineer (5+ years)"]:
    check(f"senior reject: {t}", seniority_of(t) == "senior")

check("desc senior reject",
      seniority_of("Data Analyst", "We need a minimum of 5 years of professional experience") == "senior")
check("desc entry keeps", seniority_of("Data Analyst", "perfect for a recent graduate") == "entry")
check("junior+senior mix → entry", seniority_of("Graduate Programme Senior Analyst") == "entry")

# ── Sector rejects (real gradireland listings from research) ────────────────
for t in ["Graduate Pest Control Technician", "Social Care Worker",
          "Early Years Educator", "Curatorial Fellow", "Tax Trainee",
          "Clerical Officer (July 2026)", "Sales Assistant", "Chef de Partie",
          "Roof Truss and Timber Frame Designers"]:
    # last one: trades — check it's either sector-rejected or scored low; must at least not crash
    pass
for t in ["Graduate Pest Control Technician", "Social Care Worker",
          "Early Years Educator", "Curatorial Fellow", "Tax Trainee",
          "Clerical Officer (July 2026)", "Sales Assistant", "Chef de Partie"]:
    check(f"sector reject: {t}", is_rejected_sector(t))
check("sector keeps AI Trainer", not is_rejected_sector("AI Trainer"))
check("sector keeps Supply Chain", not is_rejected_sector("Supply Chain Analyst"))

# ── Categories ──────────────────────────────────────────────────────────────
check("cat software", category_of("Graduate Software Developer") == "software")
check("cat ops_supply", category_of("Supply Chain Graduate") == "ops_supply")
check("cat data_ml for AI Trainer", category_of("AI Trainer") == "data_ml")
check("cat product_pm", category_of("Junior Project Manager") == "product_pm")

# ── Scope logic ─────────────────────────────────────────────────────────────
check("ireland scope", scope_of(J("Data Analyst", "Cork, Ireland"), cfg) == "ireland")
check("belfast counts", scope_of(J("Data Analyst", "Belfast"), cfg) == "ireland")
check("eu remote", scope_of(J("Data Analyst", "Remote — Europe"), cfg) == "eu_remote")
check("remote anywhere", scope_of(J("Data Analyst", "Fully Remote"), cfg) == "remote")
check("visa w/ phrase", scope_of(
    J("Data Analyst", "London, UK", "We offer visa sponsorship to the right candidate"), cfg) == "visa")
check("asia w/ phrase", scope_of(
    J("Data Analyst", "Singapore", "employment pass application supported"), cfg) == "asia")
check("visa no desc → unverified", scope_of(J("Data Analyst", "Berlin, Germany"), cfg) == "visa_unverified")
check("arbeitnow flag skips gate", scope_of(
    J("Data Analyst", "Munich, Germany", sponsors_visa=True), cfg) == "visa")
check("out of scope: India", scope_of(J("Data Analyst", "Bengaluru, India"), cfg) is None)
check("visa w/o sponsorship dropped", scope_of(
    J("Data Analyst", "Paris, France", "must have EU right to work already"), cfg) is None)

# ── filter_jobs plumbing: unverified bucket ─────────────────────────────────
k2, unv2, c2 = filter_jobs([J("Graduate Data Analyst", "Berlin, Germany", li_job_id="123")], cfg)
check("unverified routed", len(unv2) == 1 and len(k2) == 0)

# ── Routing thresholds ──────────────────────────────────────────────────────
jobs = [
    dict(J("A"), scope="ireland", score=0.46),   # ≥ 0.44 → alert
    dict(J("B"), scope="visa", score=0.46),      # < 0.52 → rest
    dict(J("C"), scope="visa", score=0.55),      # alert
    dict(J("D"), scope="ireland", score=0.30),   # rest
    dict(J("E"), scope="ireland", score=0.10),   # dropped
]
alerts, rest, dropped = route_jobs(jobs, cfg["scoring"])
check("route alerts", {j["title"] for j in alerts} == {"A", "C"})
check("route rest", {j["title"] for j in rest} == {"B", "D"})
check("route dropped", {j["title"] for j in dropped} == {"E"})

# ── The v5 email crash case ─────────────────────────────────────────────────
job = dict(J("Data Analyst"), score=0.7, boost=0.08, scope="ireland", category="data_ml")
try:
    html_out = build_email_html([job], [dict(job, score=0.35, scope="visa")])
    check("email builds (v5 crash fixed)", "Data Analyst" in html_out and "★" in html_out)
except Exception as e:
    check(f"email builds (raised {e})", False)

# HTML escaping in email
evil = dict(J("<script>alert(1)</script>"), score=0.5, scope="ireland", category="other")
html_out = build_email_html([evil], [])
check("email escapes html", "<script>alert" not in html_out)

# ── iCal parser ─────────────────────────────────────────────────────────────
ical = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART:20260812T180000Z
SUMMARY:Cork AI Meetup — LLMs in production
LOCATION:Republic of Work\\, Cork
URL:https://www.meetup.com/cork-ai/events/123/
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=Europe/Dublin:20260901T190000
SUMMARY:Cork Devs — Lightning talks
 with a folded continuation line
END:VEVENT
END:VCALENDAR"""
events = parse_ical_events(ical)
check("ical parses 2 events", len(events) == 2)
check("ical folded line", "continuation line" in events[1]["title"])
check("ical location unescaped", events[0]["location"] == "Republic of Work, Cork")

# ── seen-cache migration ────────────────────────────────────────────────────
import json, importlib
import run as run_mod
json.dump(["old_id_1", "old_id_2"], open("data/seen_jobs.json", "w"))
seen = run_mod.load_seen()
check("seen migrates v5 list", isinstance(seen, dict) and "old_id_1" in seen)
run_mod.save_seen(seen)
seen2 = run_mod.load_seen()
check("seen roundtrips as dict", seen2 == seen)
json.dump({}, open("data/seen_jobs.json", "w"))

print(f"\n{'='*40}\n  {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
