"""P0 regression suite: offline, mocked I/O, temporary state only."""
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import yaml

import run
from scripts.persist_state import merge_discovery, merge_outbox, merge_seen
from sources.filters import is_ireland, mentions_visa_sponsorship, scope_of
from sources.linkedin import _search_url, fetch_linkedin, fetch_linkedin_sweep, lookback_hours
from sources.outbox import due, empty_outbox, enqueue, pending_count, record_delivery
from sources.state import StateError, load_json, save_json, validate_outbox, validate_seen

CFG = yaml.safe_load(Path("config.yaml").read_text())


def j(jid="test_1", title="Graduate Software Engineer", location="Cork, Ireland", desc=""):
    return dict(id=jid, title=title, company="Example Ltd", location=location,
                link="https://example.invalid/jobs/1", posted="2026-10-14",
                source="test", description=desc, scope="ireland", score=0.61, category="software")


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "seen.json"

    def test_atomic_roundtrip_and_backup(self):
        first = {"a": "2026-07-21", "b": "2026-10-11"}
        save_json(self.path, first, validate_seen)
        save_json(self.path, {**first, "c": "2026-10-14"}, validate_seen)
        self.assertEqual(load_json(self.path, validate_seen, {}), {**first, "c": "2026-10-14"})
        self.assertEqual(json.loads(Path(str(self.path) + ".bak").read_text()), first)
        self.assertFalse(list(self.path.parent.glob(".*.tmp")))

    def test_corrupt_primary_recovers_from_backup(self):
        previous = {"old": "2026-07-21"}
        save_json(self.path, previous, validate_seen)
        save_json(self.path, {**previous, "new": "2026-10-14"}, validate_seen)
        self.path.write_text("CORRUPT")
        recovered = load_json(self.path, validate_seen, {})
        self.assertEqual(recovered, previous)
        save_json(self.path, {**recovered, "third": "2026-10-14"}, validate_seen)
        self.assertEqual(json.loads(Path(str(self.path) + ".bak").read_text()), previous)

    def test_two_corrupt_copies_fail_closed(self):
        self.path.write_text("NOT-JSON")
        Path(str(self.path) + ".bak").write_text("NOT-JSON")
        with self.assertRaises(StateError):
            load_json(self.path, validate_seen, {})

    def test_corrupt_no_backup_fail_closed(self):
        self.path.write_text("invalid")
        with self.assertRaises(StateError):
            load_json(self.path, validate_seen, {})

    def test_validate_rejects_bad_date(self):
        with self.assertRaises(StateError):
            validate_seen({"id": "today"})

    def test_valid_legacy_list_migration(self):
        self.path.write_text('["one","two"]')
        self.assertEqual(set(load_json(self.path, validate_seen, {})), {"one", "two"})

    def test_outbox_schema_rejects_corrupt_status(self):
        obj = empty_outbox()
        enqueue(obj, [j()], [])
        obj["jobs"]["test_1"]["channels"]["email"]["status"] = "imaginary"
        with self.assertRaises(StateError):
            validate_outbox(obj)

    def test_failed_atomic_replace_does_not_destroy_primary(self):
        save_json(self.path, {"old": "2026-10-14"}, validate_seen)
        with patch("sources.state.os.replace", side_effect=OSError("simulated disk crash")):
            with self.assertRaises(OSError):
                save_json(self.path, {"new": "2026-10-14"}, validate_seen)
        self.assertEqual(load_json(self.path, validate_seen, {}), {"old": "2026-10-14"})

    def test_no_history_pruning(self):
        with patch.object(run, "SEEN_FILE", self.path):
            old = {"old_id": "2026-07-21", "new_id": "2026-10-14"}
            run.save_seen(old)
            self.assertEqual(run.load_seen(), old)


class LocationTests(unittest.TestCase):
    def test_cork(self):
        self.assertEqual(scope_of(j(location="Cork, Republic of Ireland"), CFG), "ireland")

    def test_belfast_not_republic(self):
        self.assertFalse(is_ireland("Belfast, Northern Ireland"))
        self.assertIsNone(scope_of(j(location="Belfast, Northern Ireland"), CFG))

    def test_derry_not_republic(self):
        self.assertIsNone(scope_of(j(location="Derry, Northern Ireland"), CFG))

    def test_title_does_not_override_location(self):
        self.assertNotEqual(scope_of(j(title="Cork Software Engineer", location="London, UK"), CFG), "ireland")

    def test_negative_sponsorship(self):
        desc = "We do not offer visa sponsorship for this position."
        self.assertFalse(mentions_visa_sponsorship(desc, CFG))
        self.assertIsNone(scope_of(j(location="Berlin, Germany", desc=desc), CFG))

    def test_other_negative_sponsorship(self):
        for desc in ("Visa sponsorship is not available", "We cannot sponsor visas", "You must already have the right to work"):
            with self.subTest(desc=desc):
                self.assertFalse(mentions_visa_sponsorship(desc, CFG))

    def test_positive_sponsorship(self):
        self.assertEqual(scope_of(j(location="London, UK", desc="We offer visa sponsorship."), CFG), "visa")

    def test_we_sponsor_visas(self):
        self.assertEqual(scope_of(j(location="Germany", desc="We sponsor visas for successful applicants"), CFG), "visa")

    def test_employment_pass_support(self):
        self.assertEqual(scope_of(j(location="Singapore", desc="Employment pass application supported"), CFG), "asia")

    def test_remoteness_us_only_rejected(self):
        self.assertIsNone(scope_of(j(location="Fully Remote - US only"), CFG))

    def test_remote_global_with_us_only_description_rejected(self):
        self.assertIsNone(scope_of(j(location="Remote worldwide", desc="Candidates must be based in the United States"), CFG))

    def test_unqualified_fully_remote_unknown(self):
        self.assertIsNone(scope_of(j(location="Fully Remote"), CFG))

    def test_worldwide_remote(self):
        self.assertEqual(scope_of(j(location="Remote Worldwide"), CFG), "remote")

    def test_eu_remote(self):
        self.assertEqual(scope_of(j(location="Remote — EU"), CFG), "eu_remote")

    def test_eu_remote_uk_only_rejected(self):
        self.assertIsNone(scope_of(j(location="Remote Europe - UK only"), CFG))

    def test_source_flag_overridden_by_explicit_denial(self):
        job = j(location="Germany", desc="No visa sponsorship",)
        job["sponsors_visa"] = True
        self.assertIsNone(scope_of(job, CFG))

    def test_missing_nonireland_description_unverified(self):
        self.assertEqual(scope_of(j(location="Berlin, Germany"), CFG), "visa_unverified")


class LinkedInTests(unittest.TestCase):
    def test_minimum_lookback_covers_monday_after_friday(self):
        now = datetime(2026, 10, 19, 9, tzinfo=timezone.utc)
        friday = datetime(2026, 10, 16, 19, tzinfo=timezone.utc)
        self.assertGreaterEqual(lookback_hours(friday.isoformat(), now), 96)

    def test_lookback_capped_after_long_outage(self):
        now = datetime(2026, 10, 14, 9, tzinfo=timezone.utc)
        self.assertEqual(lookback_hours((now - timedelta(days=11)).isoformat(), now), 168)

    def test_default_lookback(self):
        self.assertEqual(lookback_hours(None), 96)

    def test_search_query_seconds_and_start(self):
        url = _search_url("graduate", "Ireland", 96 * 3600, start=25)
        self.assertIn("f_TPR=r345600", url)
        self.assertIn("start=25", url)

    def test_sweep_deduplicates_between_keywords(self):
        with patch("sources.linkedin.fetch_linkedin", side_effect=[[j("li_123")], [j("li_123"), j("li_456")]]) as mock_fetch:
            jobs = fetch_linkedin_sweep(["python", "data"], [], [], sleep_between=(0, 0))
        self.assertEqual([x["id"] for x in jobs], ["li_123", "li_456"])
        self.assertTrue(all(call.kwargs["seconds"] == 96 * 3600 for call in mock_fetch.call_args_list))

    def test_pagination_and_duplicate_cards(self):
        one = '<div class="base-card" data-entity-urn="urn:li:jobPosting:123"><h3 class="base-search-card__title">Graduate Engineer</h3><h4 class="base-search-card__subtitle">Acme</h4><span class="job-search-card__location">Dublin</span></div>'
        page1 = one * 25
        another = one + one.replace("123", "456")
        class Response:
            status_code = 200
            def __init__(self, text): self.text = text
        with patch("sources.linkedin.requests.get", side_effect=[Response(page1), Response(another)]) as get:
            got = fetch_linkedin("graduate", "Ireland", pages=2)
        self.assertEqual({x["id"] for x in got}, {"li_123", "li_456"})
        self.assertIn("start=25", get.call_args_list[1].args[0])


class OutboxTests(unittest.TestCase):
    def test_channels_per_job(self):
        obj = enqueue(empty_outbox(), [j("a")], [j("b")])
        self.assertEqual(set(obj["jobs"]["a"]["channels"]), {"email", "telegram"})
        self.assertEqual(set(obj["jobs"]["b"]["channels"]), {"email"})

    def test_failed_email_queued_with_backoff(self):
        obj = enqueue(empty_outbox(), [j()], [])
        entry = obj["jobs"]["test_1"]
        now = datetime(2026, 10, 14, 10, tzinfo=timezone.utc)
        record_delivery(entry, "email", False, now)
        self.assertEqual(entry["channels"]["email"]["status"], "pending")
        self.assertFalse(due(entry, "email", now + timedelta(minutes=29)))
        self.assertTrue(due(entry, "email", now + timedelta(minutes=31)))

    def test_sent_channel_is_not_requeued(self):
        obj = enqueue(empty_outbox(), [j()], [])
        record_delivery(obj["jobs"]["test_1"], "email", True)
        enqueue(obj, [j()], [])
        self.assertFalse(due(obj["jobs"]["test_1"], "email"))
        self.assertEqual(pending_count(obj), 1)

    def test_telegram_failure_email_success_different_status(self):
        obj = enqueue(empty_outbox(), [j()], [])
        e = obj["jobs"]["test_1"]
        record_delivery(e, "email", True)
        record_delivery(e, "telegram", False)
        self.assertEqual(e["channels"]["email"]["status"], "sent")
        self.assertEqual(e["channels"]["telegram"]["status"], "pending")

    def test_merge_seen_preserves_both(self):
        self.assertEqual(merge_seen({"a":"2026-10-14"}, {"a":"2026-10-11", "b":"2026-10-11"}),
                         {"a":"2026-10-11", "b":"2026-10-11"})

    def test_merge_receipt_sent_wins(self):
        a = enqueue(empty_outbox(), [j()], [])
        b = enqueue(empty_outbox(), [j()], [])
        record_delivery(a["jobs"]["test_1"], "email", True)
        record_delivery(b["jobs"]["test_1"], "email", False)
        self.assertEqual(merge_outbox(a,b)["jobs"]["test_1"]["channels"]["email"]["status"], "sent")

    def test_merge_discovery_most_recent(self):
        self.assertEqual(merge_discovery({"linkedin_last_sweep_at":"2026-10-13T00:00:00+00:00"},
                                         {"linkedin_last_sweep_at":"2026-10-14T00:00:00+00:00"})["linkedin_last_sweep_at"],
                         "2026-10-14T00:00:00+00:00")


class PipelineTests(unittest.TestCase):
    def setUp(self):
        # P0 delivery behaviour remains exercised using mocks only.
        approval = patch.object(run, 'approved', return_value=True)
        approval.start(); self.addCleanup(approval.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        paths = dict(SEEN_FILE=Path(self.temp.name)/"seen.json",
                     OUTBOX_FILE=Path(self.temp.name)/"outbox.json",
                     DISCOVERY_FILE=Path(self.temp.name)/"discovery.json")
        for name, value in paths.items():
            p = patch.object(run, name, value)
            p.start(); self.addCleanup(p.stop)
        cfg = yaml.safe_load(Path("config.yaml").read_text())
        cfg["catalogue"] = {"enabled": False}  # New network layer has its own mocked tests.
        cfg["scoring"]["cv_text_file"] = str(Path(self.temp.name)/"missing_cv.txt")
        p = patch.object(run, "load_yaml", side_effect=lambda p: cfg)
        p.start(); self.addCleanup(p.stop)

    def test_unverified_sponsorship_not_permanently_marked_seen(self):
        sample = j(jid="li_987", location="Berlin, Germany")
        sample["li_job_id"] = "987"
        with patch.object(run, "fetch_all_companies", return_value=[sample]), \
             patch.object(run, "fetch_gradireland", return_value=[]), \
             patch.object(run, "fetch_jooble", return_value=[]), \
             patch.object(run, "fetch_adzuna", return_value=[]), \
             patch.object(run, "fetch_arbeitnow", return_value=[]), \
             patch.object(run, "fetch_remotive", return_value=[]), \
             patch.object(run, "fetch_remoteok", return_value=[]), \
             patch.object(run, "fetch_linkedin_sweep", return_value=[]), \
             patch.object(run, "enrich_descriptions", side_effect=lambda jobs, cap: jobs):
            self.assertEqual(run.prepare(), 0)
        self.assertNotIn("li_987", run.load_seen())
        self.assertEqual(pending_count(run.load_outbox()), 0)

    def test_initial_production_baseline_suppresses_historical_alerts(self):
        example=j()
        # No live network and no production state: all paths patched by setUp.
        with patch.object(run, 'fetch_all_companies', return_value=[example,dict(example)]), \
             patch.object(run, 'fetch_gradireland', return_value=[]), \
             patch.object(run, 'fetch_jooble', return_value=[]), \
             patch.object(run, 'fetch_adzuna', return_value=[]), \
             patch.object(run, 'fetch_arbeitnow', return_value=[]), \
             patch.object(run, 'fetch_remotive', return_value=[]), \
             patch.object(run, 'fetch_remoteok', return_value=[]), \
             patch.object(run, 'fetch_linkedin_sweep', return_value=[]):
            self.assertEqual(run.prepare(),0)
        self.assertEqual(set(run.load_seen()), {'test_1'})
        self.assertTrue(run.load_discovery().get('baseline_initialized_at'))
        self.assertEqual(pending_count(run.load_outbox()), 0)

    def test_duplicated_job_queued_once_and_seen(self):
        run.save_discovery({"linkedin_last_sweep_at":"", "baseline_initialized_at":"2026-10-14T00:00:00+00:00"})
        example = j()
        with patch.object(run, "fetch_all_companies", return_value=[example, dict(example)]), \
             patch.object(run, "fetch_gradireland", return_value=[]), \
             patch.object(run, "fetch_jooble", return_value=[]), \
             patch.object(run, "fetch_adzuna", return_value=[]), \
             patch.object(run, "fetch_arbeitnow", return_value=[]), \
             patch.object(run, "fetch_remotive", return_value=[]), \
             patch.object(run, "fetch_remoteok", return_value=[]), \
             patch.object(run, "fetch_linkedin_sweep", return_value=[]):
            self.assertEqual(run.prepare(), 0)
        self.assertEqual(list(run.load_seen()), ["test_1"])
        self.assertEqual(len(run.load_outbox()["jobs"]), 1)

    def test_queue_saved_before_seen_and_fails_closed(self):
        example = j()
        with patch.object(run, "fetch_all_companies", return_value=[example]), \
             patch.object(run, "fetch_gradireland", return_value=[]), \
             patch.object(run, "fetch_jooble", return_value=[]), \
             patch.object(run, "fetch_adzuna", return_value=[]), \
             patch.object(run, "fetch_arbeitnow", return_value=[]), \
             patch.object(run, "fetch_remotive", return_value=[]), \
             patch.object(run, "fetch_remoteok", return_value=[]), \
             patch.object(run, "fetch_linkedin_sweep", return_value=[]), \
             patch.object(run, "save_outbox", side_effect=StateError("disk is full")):
            with self.assertRaises(StateError):
                run.prepare()
        self.assertEqual(run.load_seen(), {})

    def test_failed_notifications_leave_durable_retries(self):
        a = j()
        outbox = enqueue(empty_outbox(), [a], [])
        run.save_outbox(outbox)
        with patch.object(run, "send_email", return_value=False) as email, \
             patch.object(run, "send_telegram", return_value=False) as telegram:
            self.assertEqual(run.deliver(), 1)
            self.assertEqual(email.call_count, 1)
            self.assertEqual(telegram.call_count, 1)
        state = run.load_outbox()["jobs"]["test_1"]["channels"]
        self.assertEqual(state["email"]["status"], "pending")
        self.assertEqual(state["telegram"]["status"], "pending")
        with patch.object(run, "send_email", return_value=True) as email, \
             patch.object(run, "send_telegram", return_value=True) as telegram:
            self.assertEqual(run.deliver(), 0)  # not due until backoff expires
            self.assertEqual(email.call_count, 0)
            self.assertEqual(telegram.call_count, 0)
        outbox = run.load_outbox()
        for entry in outbox["jobs"].values():
            for channel in entry["channels"].values():
                channel["next_retry_at"] = "2026-01-01T00:00:00+00:00"
        run.save_outbox(outbox)
        with patch.object(run, "send_email", return_value=True), \
             patch.object(run, "send_telegram", return_value=True):
            self.assertEqual(run.deliver(), 0)
        self.assertEqual(pending_count(run.load_outbox()), 0)

    def test_email_sent_not_retried_if_telegram_failed(self):
        outbox = enqueue(empty_outbox(), [j()], [])
        run.save_outbox(outbox)
        with patch.object(run, "send_email", return_value=True) as email, \
             patch.object(run, "send_telegram", return_value=False):
            self.assertEqual(run.deliver(), 1)
        o = run.load_outbox()["jobs"]["test_1"]
        self.assertEqual(o["channels"]["email"]["status"], "sent")
        self.assertEqual(o["channels"]["telegram"]["status"], "pending")
        self.assertEqual(email.call_count, 1)


if __name__ == "__main__":
    unittest.main()
