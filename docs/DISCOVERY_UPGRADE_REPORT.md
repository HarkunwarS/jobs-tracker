# Discovery upgrade audit — 18 October 2026

## State of the work

Implementation is saved in [PR #2](https://github.com/HarkunwarS/jobs-tracker/pull/2), code commit `4a11ca1aa2dd9bdcb5c308d4871811a34da771c9`.
It is **not merged or deployed**. Automatic approval review rejected merging to the default branch, requesting explicit user approval for the live-tracker change while the additional live scan was running. No workaround was attempted.

Recovery point: [backup/pre-discovery-upgrade-20261018](https://github.com/HarkunwarS/jobs-tracker/tree/backup/pre-discovery-upgrade-20261018), commit `f09dc1f137e3be84b18767e71573b3a8065f07ea`.

## Research and audit

The [source inventory](SOURCE_INVENTORY.md) and [machine-readable registry](../source_registry.json) cover 44 researched source routes. A researched source is not necessarily an operational adapter. The live report measures configured employer endpoints separately.

The old pipeline had fixed first-page limits in Workday/SmartRecruiters, three GradIreland pages, narrow aggregator searches, limited LinkedIn coverage, incorrect Ashby fields and missing-ID collisions. Its seen-ID cache and notification history did not constitute an application ledger. The email limit of 20 was a delivery batch limit, not a total discovery cap.

Both base CVs were located/read in the Career Hub project during the original audit, not edited. Their immigration wording was not accepted as proof of current permission.

## Implemented changes

- Paginate ATS and aggregator listings until exhaustion/repetition or a disclosed time budget; overlapping query results no longer prevent later pages being searched.
- Broaden graduate/junior role queries and add ESB/GradPad, Arista and Ryanair routes; repair the Stryker board name.
- Persist a vacancy catalogue, CSV export, per-source health, verification evidence, dates, eligibility and transparent ranking independently of notification thresholds.
- Merge strong identifiers/canonical URLs; flag company/title/location similarities for review instead of collapsing distinct requisitions.
- Keep missing visa wording eligible for Irish discovery; separate sponsorship, international-candidate consideration, relocation and explicit restrictions.
- Recheck stale historical vacancies, expire passed deadlines even when an item no longer appears in a feed, and avoid treating blocked pages as proof of closure.
- Verify Workday/SmartRecruiters detail data and reject explicit Workday `canApply=false`.
- Keep an independent application ledger and status history. Discovery never marks an application submitted.
- Preserve signed notification grants and existing delivery/state safeguards.
- Configure the proposed production schedule for 00:00, 08:00 and 17:00 Europe/Dublin.

## Test evidence

Initial implementation: **61 legacy checks + 124 unittest tests passed**.
[Initial completed live validation](https://github.com/HarkunwarS/jobs-tracker/actions/runs/39126942158).

Final code: **24 focused tests passed locally**. Full regression workflow passed:
[Final regression run](https://github.com/HarkunwarS/jobs-tracker/actions/runs/39153153326).

The final additional live scan is separate:
[Live validation run](https://github.com/HarkunwarS/jobs-tracker/actions/runs/39153148457).
Its results must be read after completion; no success or new vacancy count is claimed here. It uses disposable state and does not send notifications or push production records.

The local full suite could not run because that Python environment lacks YAML/cryptography dependencies and package-network access; the GitHub runner supplies the pinned environment and passed the suite.

## Completed live scan results

These numbers are from the initial completed scan, not the newer pending scan.

| Measure | Count |
|---|---:|
| Raw listings fetched | 15,670 |
| Strong duplicates removed in run | 1,330 |
| Unique fetched listings before relevance reduction | 14,340 |
| Catalogue candidates including imported history | 529 |
| New catalogue candidates | 331 |
| Ireland-classified catalogue candidates | 226 |
| Verified open across all countries | 190 |
| Unverified | 202 |
| Access blocked | 103 |
| Passed deadline | 34 |
| Configured endpoints returning jobs without recorded errors | 41 |
| Partial endpoints | 2 |
| Failed endpoints | 97 |
| Empty/unverified endpoints | 8 |

These are **not 529 suitable open jobs**. The initial report does not give the intersection of open and Ireland-classified records. The final code adds that count, stale-record counts and possible-duplicate counts.

SmartRecruiters returned 248 Arista, 138 Ryanair and 5,079 Bosch listings across locations/levels before suitability filtering. Direct ESB returned 14 role-matching cards and GradPad 42 cards. Those raw counts do not establish that every listing is open, Irish or suitable.

## Sample employer-page checks

Checked separately on 18 October 2026; these are examples for review, not confirmation of application eligibility or submission.

| Employer / role | Evidence and fit | Unknowns / checks |
|---|---|---|
| [ESB — IT Graduate Development Programme 2027, Data & Analytics](https://careers.esb.ie/job/Dublin-IT-Graduate-Development-Programme-2027-Data-&-Analytics-D/1372550257/) | Live employer page and application control; Dublin, full-time, hybrid, closing 19 October 2026; minimum 2.1 and relevant degree. DS base track. | Essential undergraduate work-placement condition needs confirmation against training dates; current work permission and sponsorship unknown. Salary amount not published. |
| [Arista — Software Engineer Graduate 2026/2027](https://jobs.smartrecruiters.com/aristanetworks/744000152521250-software-engineer-graduate-2026-2027) | Live employer ATS description and application control; full-time; computing-related degree and one or more listed programming technologies. SE base track; Python/Java/React relevant. | Networking/embedded work is a stretch; permission, salary, deadline and work model not established by this check. |

Stryker's graduate page timed out during this turn's direct recheck, so it is not claimed as newly verified here.

## History and status tracking

The PR does not modify existing CV/state files. Main's intervening commits only changed normal discovery/outbox/seen state; a normal merge must retain them. Original audit recorded 98,069 seen IDs and 424 notification records; live production has continued since then.

After activation, use `data/vacancies.csv` for ranked discovery and `data/applications.json` for application history. The explicit local command is:

```sh
python scripts/applications.py CATALOGUE_ID Shortlisted --note "Reviewed"
```

Only record Applied/Assessment/Interview/etc. after the user confirms the actual event. A local edit is not remotely synchronised until committed/pushed through the authorised workflow.

## Scheduling and activation

- Existing GitHub production remains operational: run 39149244840 succeeded on 18 October, finishing 17:26 UTC / 18:26 Dublin.
- The existing ChatGPT automation “Ireland Tech Job Scan” is enabled at 00:00/08:00/17:00 Europe/Dublin from 19 October. No last run was recorded at inspection.
- No new automation was created.
- The proposed GitHub schedule is on the PR branch only and is **not yet operational**.
- Before activation completes, scope the existing ChatGPT prompt to read GitHub results and cover only manual/failed-source gaps, avoiding another ATS/API sweep and duplicate digests.
- GitHub supports timezone-aware schedules but actual starts can be delayed: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

## Remaining limits / next action

Many configured employer endpoints are obsolete or inaccessible; those routes are not claimed as working. Several agency/general portals remain manual-only. Adzuna credentials are absent. Time budgets can yield partial coverage, and no source guarantees the entire market. Candidate work permission remains unconfirmed. Ranking is an evidence-based heuristic rather than an interview probability.

**Next action:** user explicitly approves merging PR #2 after the final live scan passes. Then merge, verify state preservation and the active schedule, and narrow the existing ChatGPT automation to complementary coverage. No applications, CV changes or outreach are part of this work.


> Note (v7): references above to signed grants and the ROLE allowlist are historical; both were removed in v7.
