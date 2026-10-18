"""Per-source diagnostics. A 200 response and zero parsed jobs is not coverage."""
from __future__ import annotations
import threading
from datetime import datetime, timezone

_local = threading.local()
_lock = threading.Lock()
_reports = []

def begin(source):
    _local.report = {"source": source, "checked_at": datetime.now(timezone.utc).isoformat(),
                     "requests": 0, "errors": [], "partial": False}

def request_result(status=None, error=None):
    r = getattr(_local, "report", None)
    if r is not None:
        r["requests"] += 1
        if error or (status and status != 200):
            r["errors"].append(error or f"HTTP {status}")

def partial(reason):
    r = getattr(_local, "report", None)
    if r is not None:
        r["partial"] = True
        r["errors"].append(reason)

def finish(jobs):
    r = getattr(_local, "report", None)
    if r is None:
        return
    r["jobs"] = len(jobs)
    r["status"] = ("partial" if r["partial"] or (jobs and r["errors"]) else
                   "failed" if r["errors"] else "ok" if jobs else "empty_unverified")
    with _lock:
        _reports.append(r)
    _local.report = None

def tracked(label, fn):
    begin(label)
    jobs = []
    try:
        jobs = fn()
        for job in jobs:
            job.setdefault("source_key", label)
        return jobs
    except Exception as exc:
        request_result(error=type(exc).__name__)
        return []
    finally:
        finish(jobs)

def reports(reset=False):
    with _lock:
        result = list(_reports)
        if reset:
            _reports.clear()
    return result
