"""Validated, atomic JSON state with one recoverable .bak generation.

No silent resets on corrupt state. Writes fsync the file and containing directory;
a valid prior primary is saved as .bak before an atomic replacement.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path


class StateError(RuntimeError):
    pass


def validate_seen(value):
    if isinstance(value, list):  # legacy v5 migration
        if not all(isinstance(x, str) and x for x in value):
            raise StateError("Legacy seen state requires nonempty string IDs")
        return {x: date.today().isoformat() for x in value}
    if not isinstance(value, dict):
        raise StateError("Seen state must be a JSON object (or legacy list)")
    for jid, first_seen in value.items():
        if not isinstance(jid, str) or not jid or not isinstance(first_seen, str):
            raise StateError("Seen state requires ID -> ISO date strings")
        try:
            if date.fromisoformat(first_seen).isoformat() != first_seen:
                raise ValueError("noncanonical date")
        except ValueError as exc:
            raise StateError(f"Invalid seen date for {jid[:80]!r}") from exc
    return value


def validate_outbox(value):
    if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value.get("jobs"), dict):
        raise StateError("Outbox requires schema_version=1 and jobs object")
    for jid, entry in value["jobs"].items():
        if not isinstance(jid, str) or not jid or not isinstance(entry, dict):
            raise StateError("Invalid outbox entry")
        job, channels = entry.get("job"), entry.get("channels")
        if not isinstance(job, dict) or job.get("id") != jid or not isinstance(channels, dict):
            raise StateError(f"Invalid outbox job/channels: {jid}")
        if any(c not in ("email", "telegram") for c in channels):
            raise StateError(f"Unknown outbox channel: {jid}")
        for channel, delivery in channels.items():
            if not isinstance(delivery, dict) or delivery.get("status") not in ("pending", "sent"):
                raise StateError(f"Invalid {channel} delivery status for {jid}")
            if not isinstance(delivery.get("attempts", 0), int) or delivery.get("attempts", 0) < 0:
                raise StateError(f"Invalid {channel} retry count for {jid}")
    return value


def validate_discovery(value):
    if not isinstance(value, dict) or not isinstance(value.get("linkedin_last_sweep_at", ""), str):
        raise StateError("Invalid discovery watermark")
    return value


def _read_valid(path, validator):
    try:
        with open(path, encoding="utf-8") as stream:
            return validator(json.load(stream))
    except (OSError, ValueError, TypeError, StateError) as exc:
        raise StateError(f"Cannot read valid state from {path}: {exc}") from exc


def load_json(path: Path, validator, default):
    path = Path(path)
    backup = path.with_name(path.name + ".bak")
    if not path.exists() and not backup.exists():
        return validator(default)
    if path.exists():
        try:
            return _read_valid(path, validator)
        except StateError as exc:
            print(f"  ⚠️  State recovery: {exc}")
    if backup.exists():
        recovered = _read_valid(backup, validator)
        print(f"  ⚠️  Recovered in memory from validated backup {backup}")
        return recovered
    raise StateError(f"Primary state {path} is corrupt and no valid backup is available. Refusing to run.")


def _atomic_bytes(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
        if os.name == "posix":
            directory_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def save_json(path: Path, value, validator):
    path = Path(path)
    validator(value)
    content = (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    # Never replace a good backup with corrupt primary bytes.
    if path.exists():
        try:
            _read_valid(path, validator)
        except StateError:
            print(f"  ⚠️  Invalid primary at {path}; retaining previous backup")
        else:
            _atomic_bytes(path.with_name(path.name + ".bak"), path.read_bytes())
    _atomic_bytes(path, content)