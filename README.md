# Job Tracker v6 — Ireland-first, broad early-career recall

Automated job tracker: fetches from ~150 company career sites, graduate
boards, aggregator APIs, and LinkedIn every 30 minutes; filters for
early-career roles in scope (Ireland first, then remote/EU/visa-sponsor
countries); scores each job against your CV; alerts via Telegram (strong
matches) and email (everything, grouped Ireland-first). A separate weekly
workflow emails Cork/Ireland tech & careers networking events.

## What changed from v5 (and why you were missing jobs)

1. **v5's email builder crashed on every run that found jobs** (function
   signature bug in `notify.py`), which also killed Telegram and the
   seen-cache save. The tracker was effectively silent. Fixed; state now
   persists BEFORE notifications, and each notifier is exception-safe.
2. **No more role allowlist.** v5 only kept titles matching a keyword list,
   which dropped "AI Trainer", "Supply Chain Graduate", "Programme
   Analyst"... v6 rejects clearly-senior roles and clearly-irrelevant
   sectors, keeps everything else early-career, and lets CV scoring rank.
   Tune by editing the reject patterns in `sources/filters.py`.
3. **New sources:**
   - **Jibe career sites** (`companies.yaml → jibe`) — Susquehanna (SIG)
     included; this ATS class is why you never saw their grad programme.
   - **gradireland** — scraped directly (newest 3 pages per run).
   - **Jooble** (Ireland; indexes IrishJobs.ie/jobs.ie which block direct
     scraping), **Adzuna** (UK/DE/NL/SG), **Arbeitnow** (Europe,
     pre-verified `visa_sponsorship` flag), **Remotive**, **RemoteOK**.
4. **LinkedIn no longer wastes half the run.** v5 searched 9 abroad
   locations whose results were guaranteed to fail the visa gate (LinkedIn
   returns no description; the gate requires one). v6 uses a short
   sponsorship-phrased query set abroad AND fetches descriptions for up to
   15 candidate jobs per run so they can actually pass the gate.
5. **CI fixes:** every-30-min cadence, `concurrency` group (no more racing
   runs → duplicate alerts), `permissions: contents: write` (v5's cache
   push could fail silently), HuggingFace model cached (v5 re-downloaded
   ~90 MB every run), CV embedding cached by content hash (v5's mtime check
   never hit after checkout), seen-cache pruned by age instead of random
   truncation.

## Setup

### 1. Repository secrets (Settings → Secrets and variables → Actions)

| Secret | Required | Where to get it |
|---|---|---|
| `EMAIL_SENDER` | yes | your Gmail address |
| `EMAIL_PASSWORD` | yes | Gmail App Password (myaccount.google.com → Security → App passwords) |
| `EMAIL_RECIPIENT` | yes | where digests go |
| `TELEGRAM_BOT_TOKEN` | recommended | @BotFather |
| `TELEGRAM_CHAT_ID` | recommended | @userinfobot |
| `JOOBLE_API_KEY` | recommended | free, instant: https://jooble.org/api/about — **biggest Ireland recall win** |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | optional | free: https://developer.adzuna.com |

Missing keys never break a run — that source just logs a skip line.

### 2. Actions minutes

The 30-min weekday cadence ≈ 900+ runs/month at ~3–5 min each. **On a
public repo Actions are unlimited and free.** On a private repo the free
tier is 2,000 min/month — either make the repo public (the seen-cache and
config contain nothing sensitive; your CV text does live in
`data/cv_text.txt`, so weigh that), or relax the cron to hourly.

### 3. First run

Trigger manually: Actions → Job Tracker → Run workflow. Expect a **large
first email** — the seen-cache starts empty, so everything currently
posted counts as new. From run two onward you only get genuinely new jobs.

Check the run log/summary for `⚠️` lines: the "Added v6" Greenhouse slugs
and the SIG Jibe endpoint were added from research and should be verified
against a real run (a wrong slug just yields 0 jobs, never an error).

## Tuning

- **Too much email?** Raise `scoring.email_floor` (0.28 → 0.35) in
  `config.yaml`, or set `filtering.include_unspecified_seniority: false`.
- **Telegram too chatty/quiet?** Adjust `scoring.telegram_thresholds`
  (Ireland fires at a lower bar than abroad on purpose).
- **Add a company:** find its ATS slug (instructions at the top of
  `companies.yaml`). For custom career sites, view-source and look for
  `jibecdn.com` — if present, add the host under `jibe:`.
- **Add a meetup group:** append its URL slug to `events.meetup_groups`.
- **CV changed?** Overwrite `data/cv_text.txt` — the embedding cache
  invalidates automatically via content hash.

## Files

    run.py                    main pipeline (every 30 min)
    events_run.py             weekly events digest
    config.yaml               scope, keywords, thresholds, events
    companies.yaml            curated company list by ATS
    sources/filters.py        reject-first filtering (edit to tune scope)
    sources/ats.py            Greenhouse/Lever/Ashby/Workable/SmartRecruiters/
                              Personio/Workday/Jibe, fetched in parallel
    sources/aggregators.py    Jooble/Adzuna/Arbeitnow/Remotive/RemoteOK
    sources/gradboards.py     gradireland scraper
    sources/linkedin.py       guest search + description detail fetch
    sources/scoring.py        MiniLM CV similarity + routing thresholds
    sources/notify.py         email + Telegram
    sources/events.py         Meetup iCal + gradireland events
    test_v6.py                offline test suite (python test_v6.py)
