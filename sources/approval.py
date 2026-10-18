"""Channel gate: delivery is on when config says so. Secrets are the real credential.

The signed-grant scheme from the previous version is gone. It protected nothing
(the repo owner controls the secrets anyway) and silently stopped alerts when a
grant expired. Missing credentials are reported loudly by scripts/notification_gate.py.
"""
from __future__ import annotations

CHANNELS = {"email", "telegram", "events_email"}


def approved(channel: str, cfg: dict | None = None) -> bool:
    if channel not in CHANNELS:
        return False
    if cfg is None:
        import yaml
        from pathlib import Path
        try:
            cfg = yaml.safe_load((Path(__file__).resolve().parents[1] / "config.yaml").read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            return False
    if cfg.get("runtime", {}).get("mode") != "production":
        return False
    return cfg.get("notifications", {}).get(channel, {}).get("enabled") is True
