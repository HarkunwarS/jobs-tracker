# Production activation / operator steps

The tracker checks Python 3.11 tests, performs a first-run no-notification baseline, commits the state, and only then attempts permitted notifications. The events digest remains disabled.

## Credentials — GitHub repository Actions secrets

Go to **Settings → Secrets and variables → Actions → New repository secret** (or use the `production` environment if configured). No secret values belong in chat, code or PRs.

Required for email:
- `EMAIL_SENDER` — Gmail account used for sending
- `EMAIL_PASSWORD` — Google App Password for that account (never the main password)
- `EMAIL_RECIPIENT` — intended recipient

Required for Telegram:
- `TELEGRAM_BOT_TOKEN` — existing bot token
- `TELEGRAM_CHAT_ID` — destination chat ID

Notification delivery additionally requires `NOTIFICATION_APPROVAL_PUBLIC_KEY_B64`, `EMAIL_APPROVAL_GRANT_B64` and `TELEGRAM_APPROVAL_GRANT_B64`, generated **locally** with `scripts/sign_standing_grant.py`. The private signing key remains on the user's computer, never uploaded. Run:

```bash
python -m pip install 'cryptography==46.0.4'
python scripts/sign_standing_grant.py --channel email --private-key ~/.job-tracker-operator-key.pem --days 14
python scripts/sign_standing_grant.py --channel telegram --private-key ~/.job-tracker-operator-key.pem --days 14
```

Add both resulting signed grants and the identical public key to GitHub Secrets. These grants expire and require renewal within 30 days. If any credential or grant is missing/expired, delivery remains blocked while discovery still runs. No events digest grant should be set.

Optional job sources: `JOOBLE_API_KEY`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`.

## Monitoring and manual check

See **Actions → Ireland Job Tracker — Production Discovery**. Choose **Run workflow** (on `main`) for the first run; scheduled runs also occur at **08:17, 14:17 and 20:17 UTC**. GitHub schedules can be delayed. Check that all Python 3.11 tests pass, the seen-state count never decreases, the initial run reports `Initial production baseline` and does not dispatch historical alerts, the state push succeeds, and receipts are recorded following actual email/Telegram delivery. Existing queued entries that predate the first baseline are deliberately not replayed.

The first run is expected to prepare and preserve state without notifications. A later run can send only newly queued jobs and only while credentials and signed channel grants remain valid. For a one-message delivery test, use a dedicated isolated test recipient/chat and a single synthetic job; the workflow does not automatically send mass historical alerts. **Do not assume delivery succeeded without email/Telegram receipts and logs.**

## Recovery

The pinned pre-activation GitHub branch is `backup/pre-activation-20261014`, SHA `4a550cef34004e67eaaa23bfa431c4028a744bdb`. Maintain a separate off-GitHub backup of live state before operating long-term. Do not reset `main` to older snapshots or overwrite its 95,851-ID state with the 93,296-ID archive. Each Actions run also uploads an encrypted-at-rest Actions artifact for short-term recovery, subject to GitHub retention and repository access policy.