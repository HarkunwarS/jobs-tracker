"""
Ireland + EU + Remote + Visa-Sponsor Job Tracker v5
═══════════════════════════════════════════════════════════════════════════

Pipeline (every hour, GitHub Actions):
  1. Load config + seen-jobs cache
  2. Fetch from every ATS source: Greenhouse, Lever, Ashby, Workable,
     SmartRecruiters, Personio, Workday
  3. Fetch from LinkedIn (keyword sweep, multi-location)
  4. Deduplicate, filter by location-scope + role + seniority
  5. Score each remaining job against your CV (cosine similarity)
  6. Route:
       score ≥ threshold → Telegram instant alert + email
       score <  threshold → email only

Config: edit config.yaml + companies.yaml
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import yaml

# Make `sources/` importable as a package
sys.path.insert(0, str(Path(__file__).parent))

from sources.ats import fetch_all_companies
from sources.linkedin import fetch_linkedin_sweep
from sources.filters import (
    is_in_scope, is_too_senior, matches_role_category,
)
from sources.scoring import score_jobs, split_by_threshold
from sources.notify import send_email, send_telegram

CONFIG_FILE   = Path("config.yaml")
COMPANIES_FILE = Path("companies.yaml")
SEEN_FILE     = Path("data/seen_jobs.json")


# ── State helpers ───────────────────────────────────────────────────────────

def load_yaml(path: Path) -> Dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_seen() -> set:
    if SEEN_FILE.exists():
        try:
            with open(SEEN_FILE) as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def save_seen(seen: set) -> None:
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Cap at 50k entries to keep the cache from growing forever
    if len(seen) > 50_000:
        seen = set(list(seen)[-50_000:])
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


# ── Filtering pipeline ──────────────────────────────────────────────────────

def filter_jobs(raw_jobs: List[Dict], cfg: Dict) -> List[Dict]:
    """Apply seniority, role, and location filters. Tag each surviving job."""
    role_cfg = cfg.get("role_categories", {})

    kept = []
    counters = {"too_senior": 0, "no_role_match": 0, "out_of_scope": 0, "kept": 0}

    for j in raw_jobs:
        title = j.get("title", "")
        location = j.get("location", "")

        if is_too_senior(title):
            counters["too_senior"] += 1
            continue

        category = matches_role_category(title, role_cfg)
        if category is None:
            counters["no_role_match"] += 1
            continue

        description = j.get("description", "")
        scope = is_in_scope(location, title, description, cfg)
        if scope is None:
            counters["out_of_scope"] += 1
            continue

        j["category"] = category
        j["scope"] = scope
        kept.append(j)
        counters["kept"] += 1

    print(f"\n📊 Filter results: "
          f"kept {counters['kept']}, "
          f"out-of-scope {counters['out_of_scope']}, "
          f"wrong role {counters['no_role_match']}, "
          f"too senior {counters['too_senior']}")
    return kept


# ── LinkedIn query builder ──────────────────────────────────────────────────

def linkedin_queries(cfg: Dict) -> List[str]:
    """Build LinkedIn keyword list from enabled role categories."""
    role_cfg = cfg.get("role_categories", {})
    queries = set()
    # Use just one canonical keyword per category to keep request count down
    canonical = {
        "software_engineering": "software engineer",
        "data_science":         "data scientist",
        "data_engineering":     "data engineer",
        "devops_cloud":         "devops engineer",
        "project_management":   "project manager",
        "other_relevant":       "graduate programme",
    }
    for cat, settings in role_cfg.items():
        if settings.get("enabled", True) and cat in canonical:
            queries.add(canonical[cat])
    return sorted(queries)


def linkedin_locations(cfg: Dict) -> List[str]:
    """Build LinkedIn location list from scope config."""
    locs = []
    scope = cfg.get("locations", {})
    if scope.get("ireland", True):
        locs.append("Ireland")
    if scope.get("eu_remote", True) or scope.get("visa_sponsoring", True):
        locs.extend(["United Kingdom", "Germany", "Netherlands"])
    if scope.get("visa_sponsoring", True):
        # Asia targets
        locs.extend(["Singapore", "Malaysia", "Japan", "South Korea", "Hong Kong"])
    if scope.get("remote_anywhere", True):
        locs.append("Remote")
    return locs


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> int:
    print(f"\n🔍 Job Tracker v5 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 64)

    cfg       = load_yaml(CONFIG_FILE)
    companies = load_yaml(COMPANIES_FILE)
    seen      = load_seen()
    print(f"  📋 {len(seen)} jobs in seen-cache")

    # ── 1. Fetch from ATS sources ──
    print("\n🌐 Fetching from ATS sources…")
    ats_jobs = fetch_all_companies(companies)
    print(f"  Total ATS jobs returned: {len(ats_jobs)}")

    # ── 2. Fetch from LinkedIn ──
    print("\n🔗 Fetching from LinkedIn…")
    li_jobs = fetch_linkedin_sweep(
        keywords=linkedin_queries(cfg),
        locations=linkedin_locations(cfg),
        days=1,
    )
    print(f"  Total LinkedIn jobs returned: {len(li_jobs)}")

    # ── 3. Combine + deduplicate against seen-cache ──
    all_jobs = ats_jobs + li_jobs
    fresh = [j for j in all_jobs if j["id"] not in seen]
    print(f"\n📥 {len(fresh)} fresh jobs after dedup (out of {len(all_jobs)})")

    if not fresh:
        print("  No new jobs. Done.")
        return 0

    # ── 4. Filter by role + location + seniority ──
    kept = filter_jobs(fresh, cfg)

    if not kept:
        # Still mark the fresh ones as seen so we don't re-process them
        seen.update(j["id"] for j in fresh)
        save_seen(seen)
        print("\n  No relevant jobs after filtering. Done.")
        return 0

    # ── 5. Score against CV ──
    scoring_cfg = cfg.get("scoring", {})
    cv_path = scoring_cfg.get("cv_text_file", "data/cv_text.txt")
    threshold = scoring_cfg.get("telegram_threshold", 0.55)

    print(f"\n🎯 Scoring {len(kept)} jobs against CV…")
    if Path(cv_path).exists():
        kept = score_jobs(kept, cv_path)
        strong, rest = split_by_threshold(kept, threshold)
        print(f"  {len(strong)} strong (≥{threshold}), {len(rest)} other")
    else:
        print(f"  ⚠️  CV file {cv_path} not found — skipping scoring; all jobs go to email only")
        for j in kept:
            j["score"] = 0.0
        strong, rest = [], kept

    # ── 6. Send notifications ──
    print("\n📤 Sending notifications…")
    notif_cfg = cfg.get("notifications", {})

    if notif_cfg.get("email", {}).get("enabled", True):
        send_email(strong, rest)

    if notif_cfg.get("telegram", {}).get("enabled", True) and strong:
        max_tg = scoring_cfg.get("max_telegram_per_run", 5)
        send_telegram(strong, max_per_run=max_tg)

    # ── 7. Persist seen-cache ──
    seen.update(j["id"] for j in fresh)
    save_seen(seen)
    print(f"\n✅ Done. Seen-cache now at {len(seen)} entries.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
