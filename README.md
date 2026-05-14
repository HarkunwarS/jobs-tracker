# Job Tracker v5

Hourly job tracker for Ireland, EU, remote, and visa-sponsoring tech roles. Pulls from ~250 curated companies across 7 ATS platforms plus LinkedIn, scores each job against your CV, and routes high-relevance matches to Telegram while sending everything in scope to email.

## What's new vs v4

| Area | v4 | v5 |
|---|---|---|
| Geography | Ireland only | Ireland + EU remote + remote-anywhere + visa-sponsors |
| ATS platforms | Greenhouse, Lever, Personio | + Ashby, Workable, SmartRecruiters, Workday |
| Companies | ~75 | ~250 |
| Seniority filter | Rejected anything with "lead" | Smart filter respects "Graduate Lead" / "Junior Manager" |
| Location filter | Substring match (caught "pie" via "ie") | Word-boundary regex |
| Role types | Tech only | Tech + grad programmes + PM + analyst + consulting |
| CV relevance scoring | None | Sentence-transformer cosine similarity |
| Notifications | Single email firehose | Email digest + Telegram instant alerts for top matches |
| Configuration | Hardcoded | `config.yaml` + `companies.yaml` |
| Run frequency | Twice daily | Hourly (weekdays), every 2h (weekends) |

## File layout

```
job-tracker-v5/
├── run.py                    # main entrypoint
├── config.yaml               # ★ edit this to change behaviour
├── companies.yaml            # ★ edit this to add/remove companies
├── requirements.txt
├── sources/
│   ├── ats.py                # Greenhouse, Lever, Ashby, Workable, etc.
│   ├── linkedin.py           # LinkedIn scraper with backoff
│   ├── filters.py            # location + seniority + role filtering
│   ├── scoring.py            # CV-vs-job semantic similarity
│   └── notify.py             # email + Telegram senders
├── data/
│   ├── cv_text.txt           # ★ keep this updated when your CV changes
│   ├── seen_jobs.json        # auto-managed dedup cache
│   └── cv_text.embedding.npy # auto-generated CV embedding (gitignored)
└── .github/workflows/tracker.yml   # hourly cron
```

The two files marked ★ are the only ones you'll routinely touch.

## Setup (one-time)

### 1. Push to a new GitHub repo

Create a private repo on GitHub, then:

```bash
cd job-tracker-v5
git init
git add .
git commit -m "Initial commit: job tracker v5"
git remote add origin git@github.com:YOUR_USERNAME/job-tracker.git
git push -u origin main
```

The Actions workflow will pick up automatically.

### 2. Set up email (Gmail SMTP)

Same as your current setup, in case you're starting fresh:

1. Enable 2FA on your Gmail account
2. Go to https://myaccount.google.com/apppasswords and create an app password for "Mail"
3. In your GitHub repo go to Settings → Secrets and variables → Actions → New repository secret, and add:
   - `EMAIL_SENDER` — the Gmail address sending the alerts
   - `EMAIL_PASSWORD` — the 16-character app password from step 2
   - `EMAIL_RECIPIENT` — where alerts should arrive (can be the same as sender)

### 3. Set up Telegram (free, ~5 minutes)

Telegram is free, has no rate-limit issues, and is more reliable than WhatsApp APIs.

**Step A — create your bot**

1. Open Telegram on your phone and search for `@BotFather`
2. Send `/newbot`
3. Pick any name ("My Job Tracker") and any username ending in `bot` (e.g. `harkunwar_jobs_bot`)
4. BotFather will reply with a token like `7842491284:AAH...XYZ`. Save it.

**Step B — get your chat ID**

1. Open Telegram and search for your new bot by its username
2. Send it any message, like "hello"
3. In a browser open: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
4. You'll see JSON with a `"chat":{"id": 1234567}` field. Save that number.

**Step C — add the secrets to GitHub**

In Settings → Secrets and variables → Actions, add:
- `TELEGRAM_BOT_TOKEN` — the token from BotFather
- `TELEGRAM_CHAT_ID` — your chat ID number

If you skip Telegram entirely, the bot still runs — it just sends email only.

### 4. Confirm your CV text

Open `data/cv_text.txt`. I've pre-populated it from your v3 CV. Update it any time you tweak the CV. The bot re-embeds automatically when the file changes.

### 5. Run a smoke test

In your GitHub repo → Actions tab → "Job Tracker" workflow → "Run workflow" button. This triggers an immediate run instead of waiting for the next hour.

Watch the logs. You should see something like:

```
🌐 Fetching from ATS sources…
  → greenhouse: 64 companies
    ✓ Cloudflare: 3 jobs
    ✓ Workhuman: 12 jobs
    ...
🔗 Fetching from LinkedIn…
📥 47 fresh jobs after dedup
📊 Filter results: kept 23, out-of-scope 11, wrong role 9, too senior 4
🎯 Scoring 23 jobs against CV…
  6 strong (≥0.55), 17 other
📤 Sending notifications…
  ✉️  Email sent: 23 jobs (6 strong)
  📱 Telegram: 5 messages sent
```

## Day-to-day usage

### Adding a company

Open `companies.yaml`. Find the section for the ATS the company uses (visit their careers page — the URL tells you). Add a line:

```yaml
greenhouse:
  ...
  My Company: mycompany   # <-- new line
```

Commit and push. Next run picks it up.

### Tuning what comes through

Edit `config.yaml`:

- **Too noisy on email?** Raise `scoring.telegram_threshold` from `0.55` to e.g. `0.60`, and disable some `role_categories` you don't care about.
- **Not enough jobs?** Lower the threshold; enable more categories; add more companies to `companies.yaml`.
- **Want to drop visa-sponsor scope temporarily?** Set `locations.visa_sponsoring: false`.
- **Want different role keywords?** Edit `role_categories` lists — they're plain string matches against the job title.

### Why am I getting [some random role]?

The matcher uses keyword substring on the title. If "engineer" is in your `software_engineering` keywords (it isn't directly, but "software engineer" is), then "Sales Engineer" still wouldn't match. But "Software Sales Engineer" would. If you see consistent false positives, tighten the keywords in `config.yaml`.

### How fresh is "fresh"?

- ATS APIs: when a job appears on the company's careers page, our next hourly run sees it. So worst case ~60 minutes; average ~30.
- LinkedIn: same hourly run, but LinkedIn's own indexing has a delay so they're typically 1–6 hours behind the company's page anyway.
- This is why we hit ATS APIs first — they're the speed advantage.

## Architecture notes

**Why hourly and not every 5 minutes?** GitHub Actions free-tier gives you 2,000 minutes/month. Hourly = ~720 runs/month × 3-4 minutes each ≈ 2,400 minutes. Already cutting it close. Sub-hourly would push you into paid territory or onto a self-hosted runner.

**Why not the official LinkedIn API?** It requires a partner agreement and a corporate use case. The guest-search HTML endpoint we use is rate-limited but doesn't violate ToS in the same way scraping logged-in pages would. Expect occasional empty LinkedIn batches — the ATS sources cover the gap.

**Why sentence-transformers and not a bigger model?** `all-MiniLM-L6-v2` is 22 MB, runs in milliseconds per job, and produces 384-dim embeddings that work well for semantic similarity on short texts (job titles + your CV). Using a bigger model (e.g. `mpnet-base-v2`) would give marginally better scores but ~10× the cold-start time on Actions.

**Why does the workflow commit `seen_jobs.json` back to the repo?** GitHub Actions caches are best-effort and get evicted. Committing the file is a durable backup so if the cache evicts, you don't suddenly re-process every job in the world. The cache action above the commit is the fast path; the commit is the safety net.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `EMAIL_SENDER not set` in logs | Add the secrets at repo Settings → Secrets → Actions |
| Telegram message says nothing arrives | Did you message your bot first? Until you do, `getUpdates` returns nothing and your chat ID is invisible |
| First run pulls hundreds of jobs all at once | Expected — that's the entire current backlog. Subsequent runs only have what's new |
| `boards-api.greenhouse.io/v1/boards/X/jobs returned 404` warnings | The slug in `companies.yaml` is wrong. Check by visiting `https://boards.greenhouse.io/X` in a browser |
| LinkedIn batches consistently return 0 jobs | Rate limited. Will recover after 30+ min. The ATS path keeps working in the meantime |
| Workflow takes longer than 25 min and times out | Too many companies in `companies.yaml`. Either prune the list, or raise `timeout-minutes` in the workflow file |
| Score field is always 0.0 | CV file missing — check that `data/cv_text.txt` is committed |

## Roadmap (things v5 doesn't do yet)

- Job description analysis (currently scores on title; description-aware scoring would be more accurate)
- Reply "applied" to Telegram and have the bot mark the job + track stats
- A weekly summary email of "jobs you might have missed because they were below threshold"
- Auto-tailored cover letter draft for each top match
- Better discovery engine (the v4 one was effectively broken; v5 ships without it and relies on the curated list)

Open an issue / message me when you want any of these.
