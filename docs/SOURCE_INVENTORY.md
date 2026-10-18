# Job source inventory — checked 18 October 2026

Website readability does not establish automated access. Live per-tenant results are in `data/discovery_report.json`. Missing facts stay unknown. No login/CAPTCHA bypass is used.

| Source | Coverage and search | Dates / applications | Access evidence and recommended method |
|---|---|---|---|
| [LinkedIn Jobs](https://www.linkedin.com/jobs/) | Global; Ireland search; keyword/location/date/experience | relative dates; board then employer redirect | Guest endpoint already used; login/challenges and incomplete pages possible; **existing_guest_adapter** |
| [Indeed Ireland](https://ie.indeed.com/) | Ireland; keyword/city/county | variable; board/employer redirect | Homepage readable; bulk API/scraping not verified; **manual_search** |
| [IrishJobs](https://www.irishjobs.ie/) | Ireland; keyword/location | variable; board/employer redirect | Web retrieval returned 502; no automation claim; **manual_search** |
| [Jobs.ie](https://www.jobs.ie/) | Ireland; keyword/location | variable; board/employer redirect | Web retrieval returned 502; no automation claim; **manual_search** |
| [Glassdoor](https://www.glassdoor.ie/Job/ireland-jobs-SRCH_IL.0,7_IN70.htm) | Ireland/global; keyword/location | relative dates; board/employer redirect | Search page readable; sign-in and dynamic controls; no bulk access verified; **manual_search** |
| [GradIreland](https://gradireland.com/s/jobs/all) | Ireland + overseas graduate programmes; graduate categories/pagination | deadlines on listings; posting date variable; board/employer redirect | Existing runtime returned 36 cards from 3 pages; detail geography must be checked; **existing_html_adapter** |
| [JobsIreland](https://jobsireland.ie/) | Republic of Ireland; keyword/location/sector | variable; closing dates; job detail/application instructions | Homepage readable; API not verified; **manual_search** |
| [Publicjobs](https://www.publicjobs.ie/en/) | Irish public sector; campaign/category | campaign deadlines; competition page | Readable; eligibility booklet and citizenship rules must be checked per competition; **manual_search** |
| [Morgan McKinley](https://www.morganmckinley.com/ie/jobs) | Ireland + global; keyword/location/discipline | variable; agency vacancy | Readable listing; no bulk API verified; **manual_search** |
| [Hays Ireland](https://www.hays.ie/jobs) | Ireland; keyword/location/discipline | variable; agency vacancy | Readable sector/search page; search backend not verified; **manual_search** |
| [CPL](https://www.cpl.com/jobs) | Ireland/global; keyword/location | variable; agency vacancy | Readable portal; dynamic search; no API verified; **manual_search** |
| [IT Search](https://itsearch.ie/jobs/) | Ireland/selected global; technical disciplines/pagination | detail-dependent; agency vacancy | Readable cards with salary/location; live adapter needs schema check; **manual_search** |
| [Reperio Human Capital](https://www.reperiohumancapital.com/jobs) | Ireland/UK/USA; keyword/location/specialism | unknown in check; agency vacancy | URL inaccessible to web tool; not evidence site is down; **manual_search** |
| [FRS Recruitment](https://www.frsrecruitment.com/jobs/) | Ireland; keyword/location | unknown in check; agency vacancy | URL inaccessible to web tool; **manual_search** |
| [GemPool](https://www.gempool.ie/jobs) | Ireland technology; technical jobs | unknown in check; agency vacancy | URL inaccessible to web tool; **manual_search** |
| [Berkley](https://www.berkley-group.com/jobs/) | Ireland/UK; technology/life-sciences/engineering | unknown in check; agency vacancy | Page readable but job content not exposed in retrieved text; **manual_search** |
| [UCC vacancies](https://www.ucc.ie/en/hr/vacancies/) | Cork; research/admin/technical | closing dates per advert; official HR system | Readable directory; research roles may be fixed-term; **manual_search** |
| [University Vacancies](https://universityvacancies.com/) | Irish universities; institution/category | per vacancy; institution vacancy | Landing page readable; dynamic listings not verified; **manual_search** |
| [EURAXESS](https://euraxess.ec.europa.eu/jobs) | Europe/global research; country/research field/career stage | dates and deadlines; employer/application instructions | Readable; degree/PhD and contract duration filters essential; **manual_search** |
| [Dogpatch Labs](https://dogpatchlabs.com/) | Irish startups; company/member discovery | not a vacancy feed; employer careers after company discovery | Readable ecosystem directory; not automatically live jobs; **employer_discovery** |
| [Irish Tech News Jobs](https://irishtechnews.ie/jobs/) | Ireland tech; portal | unknown in check; job portal | Retrieved page crawl was 9 months old; recheck before use; **manual_search** |
| [Welcome to the Jungle](https://www.welcometothejungle.com/en) | Europe/global startups; role/location/company | per vacancy; employer/board application | Readable landing page; employer/international terms need per-job verification; **manual_search** |
| [Gradcracker](https://www.gradcracker.com/search/computing-technology/graduate-jobs) | UK primarily; discipline/degree/location/deadline | deadlines; employer links | Readable computing graduate results; citizenship/sponsorship per vacancy; **manual_search** |
| [Prospects](https://www.prospects.ac.uk/graduate-jobs) | UK; graduate search | per vacancy; employer links | Page shell readable; result retrieval not verified; **manual_search** |
| [EURES](https://eures.europa.eu/jobseekers_en) | Europe; occupation/country | per vacancy; national/employer links | Readable portal; listing is not proof non-EU sponsorship; **manual_search** |
| [Relocate.me](https://relocate.me/) | International relocation; country/employer | per vacancy; employer | Readable portal now emphasises relocation information; vacancy feed not established; **manual_search** |
| [Japan Dev](https://japan-dev.com/) | Japan; role/company/relocation | per vacancy; employer/job detail | Readable jobs; English and overseas hiring signals checked per role; **manual_search** |
| [TokyoDev](https://www.tokyodev.com/) | Japan; role/location/apply abroad | per vacancy; employer/job detail | Readable jobs; many experienced roles; junior availability not assumed; **manual_search** |
| [MyCareersFuture](https://www.mycareersfuture.gov.sg/) | Singapore; occupation/location/pay | per vacancy; portal/employer | Only JS shell retrieved; employment-pass support not implied; **manual_search** |
| [JobStreet Malaysia](https://my.jobstreet.com/) | Malaysia; role/location/pay | per vacancy; board/employer | Readable portal; international consideration must be explicit; **manual_search** |
| [Bayt UAE](https://www.bayt.com/en/uae/jobs/) | UAE/Middle East; keyword/location/level | relative dates; board/employer | Readable listings; work visa support not inferred from UAE location; **manual_search** |
| [Built In](https://builtin.com/jobs) | USA/global technology; role/location/remote | per vacancy; employer | Readable jobs; sponsorship must be evidenced, not inferred from employer history; **manual_search** |
| [Arbeitnow](https://www.arbeitnow.com/api/job-board-api) | Europe chiefly Germany; API pages | created timestamp when supplied; board URL | Public JSON verified; absent visa_sponsorship field means unknown; **existing_api_adapter** |
| [Jooble](https://jooble.org/api/about) | Ireland/global; keyword/location/page | updated field is not first posted; aggregator links | Existing run returned 110 across 7 queries; key required; source inclusion not exhaustive; **existing_keyed_api** |
| [Adzuna](https://developer.adzuna.com/) | Configured GB/DE/NL/SG; country/query/date/page | created date; redirect URL | Existing run skipped: API ID/key absent; no operational coverage; **credentials_missing** |
| [Remotive](https://remotive.com/api/remote-jobs) | Remote/global; public API | publication date; board URL | Existing run returned 13; residence restrictions still apply; **existing_api_adapter** |
| [RemoteOK](https://remoteok.com/api) | Remote/global; public JSON | date; board URL | Existing run returned 99; unknown remote eligibility is not worldwide permission; **existing_api_adapter** |
| [ESB](https://careers.esb.ie/go/All-Jobs/882102/) | Ireland; some UK; keyword/location/pagination | listing date may refresh; deadline on detail; direct employer | Live readable official vacancies; replaces incorrect Workday configuration; **html_listing** |
| [Arista Networks](https://jobs.smartrecruiters.com/AristaNetworks) | Ireland/global; SmartRecruiters public postings | release date; direct employer ATS | Live graduate detail verified; API access to be verified in Actions; **configured_api_probe** |
| [Ryanair](https://jobs.smartrecruiters.com/RyanairGroupHoldings) | Ireland/Europe; SmartRecruiters public postings | release date; direct employer ATS | Live IT graduate detail has unrestricted-right condition; API probe configured; **configured_api_probe** |
| [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html) | Global employer boards; all published jobs; content=true | first_published vs updated_at; absolute_url | Official public API docs checked; tenant health reported separately; **existing_api_adapter** |
| [Ashby Job Board API](https://developers.ashbyhq.com/docs/public-job-posting-api) | Global employer boards; public board; compensation optional | publishedAt; jobUrl/applyUrl | Official schema checked; repaired incorrect fields and missing-ID collisions; **existing_api_adapter** |
| [SmartRecruiters Posting API](https://developers.smartrecruiters.com/docs/endpoints) | Global employer boards; offset/limit/totalFound + detail | releasedDate; direct ATS link | Official pagination docs checked; tenant health reported separately; **existing_api_adapter** |

## Discovery across industries

Keep the existing employer routes across technology, finance, insurance, consulting, pharma/healthcare, manufacturing, travel/logistics and retail. ESB adds direct energy coverage; Arista adds networking software; Ryanair adds aviation technology. Agency and public-sector portals remain researched manual sources until their actual endpoints/parsers are validated. Startup directories identify employers; they do not count as open vacancies.

## Research-backed corrections

- SmartRecruiters pagination: https://developers.smartrecruiters.com/docs/customer-overview
- Ashby fields and published postings: https://developers.ashbyhq.com/docs/public-job-posting-api
- Greenhouse published versus update timestamps: https://docs.greenhouse.io/job-board.html
- GitHub scheduling timezone and delay caveats: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
