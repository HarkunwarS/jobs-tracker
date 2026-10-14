"""Fail-closed, per-channel OPERATOR-SIGNED approval for production transports.

An approval requires an Ed25519 signature from an offline private key; the
trusted public key must be reviewed/pinned in security/operator_public_key.pem.
No key, invalid signature, stale approval, staging mode, or disabled config
means NO SEND. CLI flags, CI dispatch inputs and env vars cannot sign grants.
"""
from __future__ import annotations
import json
import base64
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANNELS = {"email", "telegram", "events_email"}


def _scheduled_grant(channel: str) -> bool:
    """Check a bounded, Ed25519-signed standing permit provided via Actions secrets.

    Private signing keys never enter GitHub. The permit is valid for at most
    30 days; only on the exact repo/main branch, via Actions schedule/dispatch.
    No env toggle alone authorizes a notification.
    """
    if not (os.environ.get('GITHUB_ACTIONS') == 'true'
            and os.environ.get('GITHUB_REPOSITORY') == 'HarkunwarS/jobs-tracker'
            and os.environ.get('GITHUB_REF_NAME') == 'main'
            and os.environ.get('GITHUB_EVENT_NAME') in ('schedule', 'workflow_dispatch')):
        return False
    try:
        name = {'email': 'EMAIL_APPROVAL_GRANT_B64',
                'telegram': 'TELEGRAM_APPROVAL_GRANT_B64'}.get(channel)
        if not name:
            return False
        document = json.loads(base64.b64decode(os.environ[name], validate=True))
        grant = document['grant']
        if set(grant) != {'channel','environment','repository','scope','issued_at','expires_at'}:
            return False
        if not (grant['channel']==channel and grant['environment']=='production'
                and grant['repository']=='HarkunwarS/jobs-tracker'
                and grant['scope']=='scheduled'):
            return False
        issued=datetime.fromisoformat(grant['issued_at'])
        expires=datetime.fromisoformat(grant['expires_at'])
        now=datetime.now(timezone.utc)
        if not (issued.tzinfo and expires.tzinfo and issued <= now < expires
                and expires - issued <= timedelta(days=30)):
            return False
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        key=load_pem_public_key(base64.b64decode(
            os.environ['NOTIFICATION_APPROVAL_PUBLIC_KEY_B64'],validate=True))
        if not isinstance(key,Ed25519PublicKey):
            return False
        key.verify(bytes.fromhex(document['signature']), json.dumps(
            grant,sort_keys=True,separators=(',',':')).encode('utf-8'))
        return True
    except Exception:
        return False


def approved(channel: str, cfg: dict | None = None) -> bool:
    if channel not in CHANNELS:
        return False
    if cfg is None:
        import yaml
        try:
            cfg = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8')) or {}
        except (OSError, ValueError):
            return False
    if cfg.get('runtime', {}).get('mode') != 'production':
        return False
    if cfg.get('notifications', {}).get(channel, {}).get('enabled') is not True:
        return False
    if _scheduled_grant(channel):
        return True
    # Legacy single-run permit: an operator signs the exact GitHub run ID.
    run_id = os.environ.get('GITHUB_RUN_ID', '')
    if not run_id or not run_id.isdecimal():
        return False
    try:
        key_path = ROOT / 'security/operator_public_key.pem'
        doc = json.loads((ROOT / 'approvals' / f'{channel}.json').read_text(encoding='utf-8'))
        payload = doc['grant']
        if set(payload) != {'channel', 'environment', 'run_id', 'issued_at', 'expires_at'}:
            return False
        if (payload['channel'] != channel or payload['environment'] != 'production'
                or payload['run_id'] != run_id):
            return False
        issued = datetime.fromisoformat(payload['issued_at'])
        expires = datetime.fromisoformat(payload['expires_at'])
        now = datetime.now(timezone.utc)
        if not (issued.tzinfo and expires.tzinfo and
                issued <= now < expires and
                expires - issued <= timedelta(hours=1)):
            return False
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        key = load_pem_public_key(key_path.read_bytes())
        if not isinstance(key, Ed25519PublicKey):
            return False
        signed = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
        key.verify(bytes.fromhex(doc['signature']), signed)
        return True
    except Exception:
        # SECURITY: Deny rather than log token/key content or fall back to flags.
        return False