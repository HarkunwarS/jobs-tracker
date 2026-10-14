"""Durable per-job/per-channel at-least-once notification outbox."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def utcnow():
    return datetime.now(timezone.utc)


def iso(now=None):
    return (now or utcnow()).isoformat(timespec="seconds")


def empty_outbox():
    return {"schema_version": 1, "jobs": {}}


def enqueue(outbox, alerts, rest, email_enabled=True, telegram_enabled=True, now=None):
    now = now or utcnow()
    alert_ids = {j["id"] for j in alerts}
    for job in alerts + rest:
        jid = job["id"]
        # Store only the serializable presentation data used for notifications.
        channels = []
        if email_enabled:
            channels.append("email")
        if telegram_enabled and jid in alert_ids:
            channels.append("telegram")
        if not channels:
            continue
        entry = outbox["jobs"].setdefault(jid, {"job": dict(job), "channels": {}, "created_at": iso(now)})
        # Do not reset existing retry state or a delivered channel.
        for channel in channels:
            entry["channels"].setdefault(channel, {"status": "pending", "attempts": 0, "next_retry_at": None})
    return outbox


def due(entry, channel, now=None):
    now = now or utcnow()
    status = entry["channels"].get(channel)
    if not status or status["status"] == "sent":
        return False
    retry = status.get("next_retry_at")
    if not retry:
        return True
    return datetime.fromisoformat(retry) <= now


def record_delivery(entry, channel, success, now=None, error=None):
    now = now or utcnow()
    delivery = entry["channels"][channel]
    delivery["attempts"] += 1
    delivery["last_attempt_at"] = iso(now)
    if success:
        delivery["status"] = "sent"
        delivery["sent_at"] = iso(now)
        delivery["next_retry_at"] = None
        delivery.pop("last_error", None)
    else:
        delivery["status"] = "pending"
        # 30, 60, 120, 240... up to 24h, across workflow restarts.
        wait = min(30 * 2 ** min(delivery["attempts"] - 1, 6), 24 * 60)
        delivery["next_retry_at"] = iso(now + timedelta(minutes=wait))
        delivery["last_error"] = (error or "Notifier returned False")[:300]
    return delivery


def pending_count(outbox):
    return sum(1 for e in outbox["jobs"].values() for s in e["channels"].values() if s["status"] == "pending")


def prune_delivered(outbox, now=None, retention_days=30):
    now = now or utcnow()
    cutoff = now - timedelta(days=retention_days)
    for jid, entry in list(outbox["jobs"].items()):
        channels = entry["channels"].values()
        if channels and all(s["status"] == "sent" for s in channels):
            newest = max(datetime.fromisoformat(s["sent_at"]) for s in channels)
            if newest < cutoff:
                del outbox["jobs"][jid]