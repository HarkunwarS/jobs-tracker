"""
Job Tracker v6 — Ireland-first, broad early-career recall
═════════════════════════════════════════════════════════════════════════════

Pipeline (every 30 min on weekdays via GitHub Actions):
  1. Load config + seen-cache
  2. Fetch in parallel: ATS/company sources (Greenhouse, Lever, Ashby,
     Workable, SmartRecruiters, Personio, Workday, Jibe career sites),
     gradireland, LinkedIn sweep, aggregators (Jooble, Adzuna, Arbeitnow,
     Remotive, RemoteOK)
  3. Dedup against seen-cache
  4. Filter: reject-first (senior / wrong sector / out of scope);
     fetch LinkedIn descriptions for visa-gate candidates
  5. Score against CV (MiniLM cosine + keyword boosts)
  6. Persist seen-cache  ←  BEFORE notifications, so a notify failure can
     never cause duplicate alerts or a re-processing loop
  7. Notify: Telegram (per-scope thresholds) + email (everything, grouped)

Config: config.yaml + companies.yaml
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from sources.ats import fetch_all_companies
from sources.aggregators import (
    fetch_adzuna, fetch_arbeitnow, fetch_jooble, fetch_remoteok, fetch_remotive,
)
from sources.gradboards import fetch_gradireland
from sources.linkedin import enrich_descriptions, fetch_linkedin_sweep
from sources.filters import filter_jobs, scope_of
from sources.scoring import route_jobs, score_jobs
from sources.notify import send_email, send_telegram

CONFIG_FILE = Path("config.yaml")
COMPANIES_FILE = Path("companies.yaml")
SEEN_FILE = Path("data/seen_jobs.json")
SEEN_MAX_AGE_DAYS = 120


# ── State helpers ─────────────────────────────────────────────────────────

def load_yaml(path: Path) -> Dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_seen() -> Dict[str, str]:
    """seen-cache is {job_id: iso_date_first_seen}. Migrates the old
    v5 list format transparently."""
    if not SEEN_FILE.exists():
        return {}
    try:
        with open(SEEN_FILE) as f:
            data = json.load(f)
    except Exception:
        return {}
    if isinstance(data, list):                      # v5 format
        today = datetime.now().strftime("%Y-%m-%d")
        return {jid: today for jid in data}
    return data if isinstance(data, dict) else {}


def save_seen(seen: Dict[str, str]) -> None:
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    cutoff = (datetime.now() - timedelta(days=SEEN_MAX_AGE_DAYS)).strftime("%Y-%m-%d")
    pruned = {jid: d for jid, d in seen.items() if d >= cutoff}
    with open(SEEN_FILE, "w") as f:
        json.dump(pruned, f)


# ── Main ────────────────────────────────────────────────────────────

def main() -> int:
    print(f"\n🔍 Job Tracker v6 — {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 64)

    cfg = load_yaml(CONFIG_FILE)
    companies = load_yaml(COMPANIES_FILE)
    seen = load_seen()
    print(f"  📋 {len(seen)} jobs in seen-cache")

    kw_cfg = cfg.get("keywords", {})
    agg_cfg = cfg.get("aggregators", {})
    li_cfg = cfg.get("linkedin", {})

    # ── 1. Fetch everything ──
    all_jobs: List[Dict] = []

    print("\n🌐 ATS & company career sites…")
    all_jobs += fetch_all_companies(companies)

    print("\n🎓 Graduate boards…")
    all_jobs += fetch_gradireland(pages=int(cfg.get("gradireland", {}).get("pages", 3)))

    print("\n📦 Aggregators…")
    if agg_cfg.get("jooble", True):
        all_jobs += fetch_jooble(kw_cfg.get("aggregator_queries", ["graduate"]), location="Ireland")
    if agg_cfg.get("adzuna", True):
        all_jobs += fetch_adzuna(
            kw_cfg.get("aggregator_queries", ["graduate"]),
            countries=agg_cfg.get("adzuna_countries", ["gb"]),
        )
    if agg_cfg.get("arbeitnow", True):
        all_jobs += fetch_arbeitnow(visa_only=True)
    if agg_cfg.get("remotive", True):
        all_jobs += fetch_remotive()
    if agg_cfg.get("remoteok", True):
        all_jobs += fetch_remoteok()

    print("\n🔗 LinkedIn…")
    all_jobs += fetch_linkedin_sweep(
        ireland_keywords=kw_cfg.get("linkedin_ireland", ["graduate"]),
        abroad_keywords=kw_cfg.get("linkedin_abroad", ["graduate programme"]),
        abroad_locations=li_cfg.get("abroad_locations", []),
        window_hours=int(li_cfg.get("window_hours", 3)),
    )

    # ── 2. Dedup ──
    fresh = [j for j in all_jobs if j["id"] not in seen]
    print(f"\n📥 {len(fresh)} fresh (of {len(all_jobs)} fetched)")
    if not fresh:
        print("  No new jobs. Done.")
        return 0

    # ── 3. Filter ──
    kept, unverified, counters = filter_jobs(fresh, cfg)

    # LinkedIn visa-gate candidates: fetch their descriptions, re-check
    if unverified:
        li_unverified = [j for j in unverified if j.get("li_job_id")]
        if li_unverified:
            print(f"\n🔎 {len(li_unverified)} visa-gate candidates need descriptions…")
            enrich_descriptions(li_unverified, cap=int(li_cfg.get("detail_fetch_cap", 15)))
            for j in li_unverified:
                scope = scope_of(j, cfg)
                if scope and scope != "visa_unverified":
                    j["scope"] = scope
                    kept.append(j)
                    counters["kept"] += 1

    print(f"\n📊 Filters: kept {counters['kept']} · senior {counters['senior']} · "
          f"wrong-sector {counters['sector']} · out-of-scope {counters['out_of_scope']} · "
          f"visa-unverified {counters['unverified']}")

    # Everything fetched this run is now "seen", relevant or not
    today = datetime.now().strftime("%Y-%m-%d")
    for j in fresh:
        seen.setdefault(j["id"], today)

    if not kept:
        save_seen(seen)
        print("\n  No relevant jobs after filtering. Done.")
        return 0

    # ── 4. Score ──
    scoring_cfg = cfg.get("scoring", {})
    cv_path = scoring_cfg.get("cv_text_file", "data/cv_text.txt")
    print(f"\n🎯 Scoring {len(kept)} jobs against CV…")
    scoring_failed = False
    try:
        if Path(cv_path).exists():
            kept = score_jobs(kept, cv_path)
            alerts, rest, dropped = route_jobs(kept, scoring_cfg)
            print(f"  {len(alerts)} alert-worthy · {len(rest)} email-only · {len(dropped)} below floor")
        else:
            print(f"  ⚠️  CV file {cv_path} missing — skipping scoring, all to email")
            for j in kept:
                j["score"] = 0.0
            alerts, rest = [], kept
    except Exception as e:
        scoring_failed = True
        print(f"  ❌ Scoring failed: {type(e).__name__}: {e}")
        print("  ❌ Sending UNSCORED jobs by email so nothing is lost, but this")
        print("  ❌ run will exit non-zero — check the log and fix scoring!")
        for j in kept:
            j["score"] = 0.0
        alerts, rest = [], kept

    # ── 5. Persist state BEFORE notifying ──
    save_seen(seen)

    # ── 6. Notify (each guarded; a failure can't break the run) ──
    print("\n📤 Notifications…")
    notif_cfg = cfg.get("notifications", {})
    try:
        if notif_cfg.get("email", {}).get("enabled", True):
            send_email(alerts, rest)
    except Exception as e:
        print(f"  ⚠️  Email raised: {e}")
    try:
        if notif_cfg.get("telegram", {}).get("enabled", True) and alerts:
            send_telegram(alerts, max_per_run=int(scoring_cfg.get("max_telegram_per_run", 10)))
    except Exception as e:
        print(f"  ⚠️  Telegram raised: {e}")

    if scoring_failed:
        print(f"\n❌ Done WITH SCORING FAILURE. Seen-cache: {len(seen)} entries.")
        return 1
    print(f"\n✅ Done. Seen-cache: {len(seen)} entries.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
