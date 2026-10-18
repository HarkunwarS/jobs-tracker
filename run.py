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
from sources.coverage import tracked
from sources.direct import fetch_direct_sites
from sources.discovery_store import refresh as refresh_catalogue
import json
from sources.aggregators import fetch_adzuna, fetch_arbeitnow, fetch_jooble, fetch_remoteok, fetch_remotive
from sources.gradboards import fetch_gradireland
from sources.linkedin import enrich_descriptions, fetch_linkedin_sweep, lookback_hours
from sources.filters import filter_jobs, scope_of
from sources.scoring import route_jobs, score_jobs
from sources.notify import send_email, send_telegram
from sources.approval import approved
from sources.state import (StateError, load_json, save_json, validate_discovery,
                           validate_outbox, validate_seen)
from sources.outbox import (due, empty_outbox, enqueue, expire_stale, iso, pending_count,
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
    print(f"\n🔍 Job Tracker v7 — prepare {iso()}")
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
    all_jobs += tracked("gradireland", lambda: fetch_gradireland(pages=int(cfg.get("gradireland", {}).get("pages", 0))))
    print("\n📦 Aggregators…")
    if agg_cfg.get("jooble", True):
        all_jobs += tracked("aggregator:Jooble", lambda: fetch_jooble(kw_cfg.get("aggregator_queries", ["graduate"]), location="Ireland"))
    if agg_cfg.get("adzuna", True):
        all_jobs += tracked("aggregator:Adzuna", lambda: fetch_adzuna(kw_cfg.get("aggregator_queries", ["graduate"]),
                                 countries=agg_cfg.get("adzuna_countries", ["gb"])))
    if agg_cfg.get("arbeitnow", True):
        all_jobs += tracked("aggregator:Arbeitnow", lambda: fetch_arbeitnow(visa_only=True, pages=0))
    if agg_cfg.get("remotive", True):
        all_jobs += tracked("aggregator:Remotive", fetch_remotive)
    if agg_cfg.get("remoteok", True):
        all_jobs += tracked("aggregator:RemoteOK", fetch_remoteok)

    minimum_hours = max(24, int(li_cfg.get("window_hours", 48)))
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

    suppressed_ids = set()
    if cfg.get("catalogue", {}).get("enabled", False):
        registry_path = Path(cfg["catalogue"].get("registry", "source_registry.json"))
        if registry_path.exists():
            all_jobs += fetch_direct_sites(json.loads(registry_path.read_text()))
        all_jobs, suppressed_ids = refresh_catalogue(all_jobs, outbox, cfg)
    all_jobs = unique_by_id(all_jobs)
    if not all_jobs and not discovery.get("baseline_initialized_at"):
        print("  ❌ Initial baseline aborted: no jobs returned by any source; no state was changed")
        return 2
    fresh = [job for job in all_jobs if job["id"] not in seen and job["id"] not in suppressed_ids]
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

    if cfg.get("catalogue", {}).get("enabled", False):
        # v7: verification FLAGS a job, it never blocks one. Only jobs we have
        # positive evidence are closed are dropped. No role allowlist.
        CLOSED_STATES = ("closed", "closed_deadline", "unavailable")
        kept = [j for j in kept if j.get("verification_status") not in CLOSED_STATES]
        counters["kept"] = len(kept)
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
    # First successful source sweep establishes a baseline: preserve seen history,
    # do not queue old source results as new alerts. Existing pending outbox is
    # retained as-is. Later sweeps enqueue only IDs not previously seen.
    baseline = not bool(discovery.get('baseline_initialized_at'))
    if baseline:
        print('  🛡  Initial production baseline: mark fetched jobs seen WITHOUT queuing historical alerts')
    else:
        # Keep each channel queued even if credentials are temporarily absent.
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
    if baseline:
        discovery["baseline_initialized_at"] = iso()
    discovery["linkedin_last_sweep_at"] = iso()
    save_discovery(discovery)
    if baseline and __import__('os').environ.get('GITHUB_OUTPUT'):
        with open(__import__('os').environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as f:
            f.write('bootstrapped=true\n')
    print(f"  ✅ Prepared state: {len(seen)} seen IDs; {pending_count(outbox)} queued channel deliveries")
    if scoring_failed:
        print('  ⚠️  Score model unavailable; unscored eligible jobs persisted to queue for review')
    return 0


def deliver() -> int:
    """Replay stored deliveries without fetching/scoring jobs or mutating seen."""
    cfg = load_yaml(CONFIG_FILE)
    outbox = load_outbox()
    now = utcnow()
    retries_failed = 0
    email_batch_cap = max(1, min(int(cfg.get('scoring', {}).get('max_email_per_run', 60)), 120))
    baseline_at = load_discovery().get('baseline_initialized_at')
    catalogue_index = {}
    if cfg.get("catalogue",{}).get("enabled",False):
        from sources.catalogue import validate_catalogue, empty_catalogue, identities
        catalogue = load_json(Path("data/vacancies.json"), validate_catalogue, empty_catalogue())
        catalogue_index = {a:j for j in catalogue["jobs"].values() for a in j.get("aliases",[])}
    expiry_days = int(cfg.get("scoring", {}).get("queue_expiry_days", 10))
    CLOSED_STATES = ("closed", "closed_deadline", "unavailable")

    from sources.filters import seniority_of

    def eligible_for_delivery(entry):
        # Only skip a job when we have evidence it is closed, senior, or the alert is stale.
        if seniority_of(entry["job"].get("title", "")) == "senior":
            return False
        try:
            created = datetime.fromisoformat(str(entry.get("created_at", "")))
            if (now - created).days > expiry_days:
                return False
        except ValueError:
            pass
        if catalogue_index:
            record = next((catalogue_index[a] for a in identities(entry["job"]) if a in catalogue_index), {})
            if record.get("verification_status") in CLOSED_STATES:
                return False
            if record.get("deadline") and str(record["deadline"])[:10] < now.date().isoformat():
                return False
        return not baseline_at or str(entry.get('created_at', '')) >= baseline_at

    INTERN = __import__("re").compile(r"\bintern(?:ship)?s?\b|\bplacement|\bco-?op\b|\bstudents?\b", __import__("re").I)

    def priority(item):
        # Best first: full-time roles before internships, then highest score.
        entry = item[1]
        job = entry["job"]
        return (1 if INTERN.search(job.get("title", "")) else 0,
                1 if job.get("category", "other") == "other" else 0,
                -float(job.get("score", 0) or 0))

    email_due = sorted([(jid, entry) for jid, entry in outbox["jobs"].items()
                        if approved('email', cfg) and eligible_for_delivery(entry) and due(entry, "email", now)],
                       key=priority)[:email_batch_cap]
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

    max_telegram = max(1, int(cfg.get("scoring", {}).get("max_telegram_per_run", 12)))
    telegram_due = sorted([(jid, entry) for jid, entry in outbox["jobs"].items()
                           if approved('telegram', cfg) and eligible_for_delivery(entry) and due(entry, "telegram", now)],
                          key=priority)
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
    expired = expire_stale(outbox, expiry_days, now)
    if expired:
        print(f"  🗑  Expired {expired} undelivered entries older than {expiry_days} days")
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
    parser.add_argument("--deliver", action="store_true", help="Deliver queued alerts")
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
            print('DENIED: no channel enabled in config.yaml', file=sys.stderr)
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
