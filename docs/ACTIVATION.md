# Setup (v7)

Delivery is controlled by `config.yaml` (`notifications.email.enabled`, `notifications.telegram.enabled`)
plus these repository secrets (Settings > Secrets and variables > Actions):

- Email: `EMAIL_SENDER`, `EMAIL_PASSWORD` (Gmail app password), `EMAIL_RECIPIENT`
- Telegram: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- Optional sources: `JOOBLE_API_KEY`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`

The signed-grant system (`NOTIFICATION_APPROVAL_PUBLIC_KEY_B64`, `*_APPROVAL_GRANT_B64`) is gone.
You can delete those three secrets. If both channels lack credentials or are disabled, the
"Check delivery channels" step now FAILS the run, so GitHub emails you instead of staying silently green.

## Schedule and minutes
The workflow runs hourly (`7 * * * *`, UTC). A run takes roughly 10 to 15 minutes, so this needs a
PUBLIC repo (unlimited Actions minutes). On a private repo the 2,000 free minutes/month would run out in about a week.
For 30-minute runs change the cron to `7,37 * * * *`.

## Checking a run
Look for: tests pass, "Delivery channels: email, telegram", "Sending N queued email entries",
and "Delivery attempts failed: 0". Email arrives best-first; internships are in their own block at the bottom.
