"""Job Tracker v6 P0 hardening — prepare an outbox, commit, then deliver.

GitHub Actions runs `--prepare`, persists state to the remote branch, runs
`--deliver`, and persists delivery receipts. Default `python run.py` does
both for local use, but cannot guard against an external git-push failure.
The outbox provides at-least-once delivery; exactly-once is not achievable
with SMTP/Telegram without provider idempotency guarantees.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from sources.ats import fetch_all_companies
from sources.aggregators import fetch_adzuna, fetch_arbeitnow, fetch_jooble, fetch_remoteok, fetch_remotive
from sources.gradboards import fetch_gradireland
from sources.linkedin import enrich_descriptions, fetch_linkedin_sweep, lookback_hours
from sources.filters import filter_jobs, scope_of
from sources.scoring import route_jobs, score_jobs
from sources.notify import send_email, send_telegram
from sources.approval import approved
from sources.state import (StateError, load_json, save_json, validate_discovery,
                           validate_outbox, validate_seen)
from sources.outbox import (due, empty_outbox, enqueue, iso, pending_count,
                            prune_delivered, record_delivery, utcnow)

CONFIG_FILE = Path("config.yaml")
COMPANIES_FILE = Path("companies.yaml")
SEEN_FILE = Path("data/seen_jobs.json")
OUTBOX_FILE = Path("data/notification_outbox.json")
DISCOVERY_FILE = Path("data/discovery_state.json")


def load_yaml(path: Path) -> Dict:
    with open(path, encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


def load_seen() -> Dict[str, str]:
    return load_json(SEEN_FILE, validate_seen, {})


def save_seen(seen: Dict[str, str]) -> None:
    # Intentionally retain all historical IDs. Old v6 120-day automatic
    # pruning would violate the user-requested preservation guarantee.
    save_json(SEEN_FILE, seen, validate_seen)


def load_outbox():
    return load_json(OUTBOX_FILE, validate_outbox, empty_outbox())


def save_outbox(outbox):
    save_json(OUTBOX_FILE, outbox, validate_outbox)


def load_discovery():
    return load_json(DISCOVERY_FILE, validate_discovery, {"linkedin_last_sweep_at": ""})


def save_discovery(state):
    save_json(DISCOVERY_FILE, state, validate_discovery)


def unique_by_id(jobs):
    """Within-run ID dedup; keeps existing source IDs intact."""
    result, keys = [], set()
    for job in jobs:
        jid = str(job.get("id", "") or "")
        if not jid or jid in keys:
            continue
        keys.add(jid)
        result.append(job)
    return result


def prepare() -> int:
    print(f"\n🔍 Job Tracker v6 P0 — prepare {iso()}")
    cfg = load_yaml(CONFIG_FILE)
    companies = load_yaml(COMPANIES_FILE)
    seen = load_seen()
    outbox = load_outbox()
    discovery = load_discovery()
    print(f"  📋 {len(seen)} historical seen IDs; {pending_count(outbox)} outstanding deliveries")

    kw_cfg = cfg.get("keywords", {})
    agg_cfg = cfg.get("aggregators", {})
    li_cfg = cfg.get("linkedin", {})
    all_jobs: List[Dict] = []

    print("\n🌐 ATS & company career sites…")
    all_jobs += fetch_all_companies(companies)
    print("\n🎓 Graduate boards…")
    all_jobs += fetch_gradireland(pages=int(cfg.get("gradireland", {}).get("pages", 3)))
    print("\n📦 Aggregators…")
    if agg_cfg.get("jooble", True):
        all_jobs += fetch_jooble(kw_cfg.get("aggregator_queries", ["graduate"]), location="Ireland")
    if agg_cfg.get("adzuna", True):
        all_jobs += fetch_adzuna(kw_cfg.get("aggregator_queries", ["graduate"]),
                                 countries=agg_cfg.get("adzuna_countries", ["gb"]))
    if agg_cfg.get("arbeitnow", True):
        all_jobs += fetch_arbeitnow(visa_only=True)
    if agg_cfg.get("remotive", True):
        all_jobs += fetch_remotive()
    if agg_cfg.get("remoteok", True):
        all_jobs += fetch_remoteok()

    minimum_hours = max(96, int(li_cfg.get("window_hours", 96)))
    maximum_hours = max(minimum_hours, int(li_cfg.get("maximum_window_hours", 168)))
    lookback = lookback_hours(discovery.get("linkedin_last_sweep_at"),
                              minimum=minimum_hours, maximum=maximum_hours)
    print("\n🔗 LinkedIn…")
    all_jobs += fetch_linkedin_sweep(
        ireland_keywords=kw_cfg.get("linkedin_ireland", ["graduate"]),
        abroad_keywords=kw_cfg.get("linkedin_abroad", ["graduate programme"]),
        abroad_locations=li_cfg.get("abroad_locations", []),
        window_hours=lookback,
        pages_per_search=int(li_cfg.get("pages_per_search", 2)),
    )

    all_jobs = unique_by_id(all_jobs)
    fresh = [job for job in all_jobs if job["id"] not in seen]
    print(f"\n📥 {len(fresh)} fresh unique IDs (of {len(all_jobs)} fetched unique IDs)")

    kept, unverified, counters = filter_jobs(fresh, cfg)
    li_unverified = [job for job in unverified if job.get("li_job_id")]
    if li_unverified:
        print(f"\n🔎 {len(li_unverified)} LinkedIn sponsorship candidates need descriptions…")
        enrich_descriptions(li_unverified, cap=int(li_cfg.get("detail_fetch_cap", 15)))
        for job in li_unverified:
            scope = scope_of(job, cfg)
            if scope and scope not in ("visa_unverified", "eligibility_unverified"):
                job["scope"] = scope
                kept.append(job)
                counters["kept"] += 1

    print(f"\n📊 Filters: kept {counters['kept']} · senior {counters['senior']} · "
          f"sector {counters['sector']} · out-of-scope {counters['out_of_scope']} · "
          f"sponsorship-unverified {counters['unverified']}")

    scoring_failed = False
    alerts, rest = [], []
    if kept:
        scoring_cfg = cfg.get("scoring", {})
        cv_path = scoring_cfg.get("cv_text_file", "data/cv_text.txt")
        print(f"\n🎯 Scoring {len(kept)} jobs against CV…")
        try:
            if Path(cv_path).exists():
                scored = score_jobs(kept, cv_path)
                alerts, rest, dropped = route_jobs(scored, scoring_cfg)
                print(f"  {len(alerts)} alert-worthy · {len(rest)} email-only · {len(dropped)} below floor")
            else:
                print(f"  ⚠️  CV file missing: {cv_path}; enqueueing unscored email digest")
                rest = [dict(job, score=0.0) for job in kept]
        except Exception as exc:
            scoring_failed = True
            print(f"  ❌ Scoring failed: {type(exc).__name__}: {exc}")
            rest = [dict(job, score=0.0) for job in kept]

    notif_cfg = cfg.get("notifications", {})
    # Queue BEFORE seen even while delivery is OFF; deferred approvals must
    # never erase queued work. These are NOT authorisations to send.
    enqueue(outbox, alerts, rest, email_enabled=True, telegram_enabled=True)

    # Ordering is crucial: never mark fetched jobs seen before queuing
    # every eligible notification durably. Fail closed if outbox save fails.
    save_outbox(outbox)
    today = datetime.now(timezone.utc).date().isoformat()
    unresolved = {job["id"] for job in unverified
                  if scope_of(job, cfg) in ("visa_unverified", "eligibility_unverified")}
    # Missing descriptions are not negative sponsorship evidence. Defer
    # marking those jobs seen so the next overlapping sweep can retry.
    for job in fresh:
        if job["id"] not in unresolved:
            seen.setdefault(job["id"], today)
    if unresolved:
        print(f"  ⚠️  {len(unresolved)} unverified jobs deferred for retry; not marked seen")
    save_seen(seen)
    # Successful sweep is not proof that guest endpoint returned all results.
    # 96h minimum overlap mitigates transient source errors/delays.
    discovery["linkedin_last_sweep_at"] = iso()
    save_discovery(discovery)
    print(f"  ✅ Prepared state: {len(seen)} seen IDs; {pending_count(outbox)} queued channel deliveries")
    return 1 if scoring_failed else 0


def deliver() -> int:
    """Replay stored deliveries without fetching/scoring jobs or mutating seen."""
    cfg = load_yaml(CONFIG_FILE)
    outbox = load_outbox()
    now = utcnow()
    retries_failed = 0
    email_due = [(jid, entry) for jid, entry in outbox["jobs"].items()
                 if approved('email', cfg) and due(entry, "email", now)]
    if email_due:
        alerts = [entry["job"] for jid, entry in email_due if "telegram" in entry["channels"]]
        rest = [entry["job"] for jid, entry in email_due if "telegram" not in entry["channels"]]
        print(f"\n✉️  Sending {len(email_due)} queued email entries")
        try:
            success = bool(send_email(alerts, rest))
            error = None if success else "Email notifier failed or is not configured"
        except Exception as exc:
            success, error = False, f"{type(exc).__name__}: {exc}"
        for jid, entry in email_due:
            record_delivery(entry, "email", success, now=now, error=error)
        save_outbox(outbox)
        if not success:
            retries_failed += len(email_due)

    max_telegram = max(1, int(cfg.get("scoring", {}).get("max_telegram_per_run", 10)))
    telegram_due = [(jid, entry) for jid, entry in outbox["jobs"].items()
                    if approved('telegram', cfg) and due(entry, "telegram", now)]
    print(f"\n📱 Telegram due: {len(telegram_due)}; current run cap: {max_telegram}")
    for jid, entry in telegram_due[:max_telegram]:
        try:
            success = bool(send_telegram([entry["job"]], max_per_run=1))
            error = None if success else "Telegram notifier failed or is not configured"
        except Exception as exc:
            success, error = False, f"{type(exc).__name__}: {exc}"
        record_delivery(entry, "telegram", success, now=now, error=error)
        save_outbox(outbox)  # receipt immediately after each send
        if not success:
            retries_failed += 1

    prune_delivered(outbox)
    save_outbox(outbox)
    pending = pending_count(outbox)
    print(f"  {'❌' if retries_failed else '✅'} Delivery attempts failed: {retries_failed}; "
          f"outstanding queued: {pending}")
    # Fail the stage on actual delivery failures; queue survives and retries
    # after exponential backoff on subsequent --deliver invocations.
    return 1 if retries_failed else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Job Tracker v6 P0 (offline-safe test harness)")
    parser.add_argument("--prepare", action="store_true", help="Fetch/score and persist queue only")
    parser.add_argument("--deliver", action="store_true", help="Deliver ONLY with operator-signed approvals")
    parser.add_argument("--dry-run", action="store_true", help="Read-only state validation; NO sources, writes or sends")
    args = parser.parse_args(argv)
    if sum((args.prepare, args.deliver, args.dry_run)) > 1:
        parser.error("Use at most one stage flag")
    try:
        cfg = load_yaml(CONFIG_FILE)
        if args.dry_run:
            seen, outbox, discovery = load_seen(), load_outbox(), load_discovery()
            print(f"SAFE READ-ONLY dry-run: {len(seen)} seen, {pending_count(outbox)} pending; "
                  "zero sources, zero writes, zero notifications")
            return 0
        if cfg.get('runtime', {}).get('mode') != 'production':
            print('DENIED: staging mode cannot prepare or deliver; use --dry-run', file=sys.stderr)
            return 3
        if not (args.prepare or args.deliver):
            print('DENIED: explicit --prepare or --deliver required', file=sys.stderr)
            return 3
        if args.deliver and not any(approved(c, cfg) for c in ('email', 'telegram')):
            print('DENIED: no operator-signed channel approvals', file=sys.stderr)
            return 3
        if args.prepare:
            return prepare()
        if args.deliver:
            return deliver()
        p = prepare()
        if p:
            return p  # persist queue; CI can still run delivery as separate step
        return deliver()
    except (StateError, OSError, ValueError) as exc:
        print(f"❌ State/workflow failure: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())