# Quality Job Scraper

A zero-paid-API pipeline that finds, checks, scores and formats recent remote tech,
Web3, AI-training and accessible entry-level opportunities. Accepted jobs are appended
to a Google Sheets tab that an existing Make scenario can publish to Telegram.

The recommended production route is GitHub Actions → Make webhook → `QualityJobs` →
the existing Make Telegram publisher. Set `MAKE_WEBHOOK_URL` and the scraper sends one
flat JSON object per accepted job using the same 26 names as the Sheet headers. Direct
Google Sheets writing remains available as a fallback.

## What it fixes

- rejects jobs older than the configured maximum (7 days by default)
- rejects definite dead links (`404` and `410`)
- strips tracking parameters and deduplicates by URL and title/company fingerprint
- blocks courses, bootcamps, unpaid roles and obvious promotional listings
- distinguishes worldwide, Africa-accessible and region-restricted work
- withholds listings whose applicant location cannot be determined
- gives extra weight to fresh, salary-listed, AI and entry-level opportunities
- limits source concentration and referral posts
- generates a clean, search-oriented Telegram HTML message
- leaves `processed` as `FALSE`, preserving the existing Make workflow contract

No paid AI model is required. The classification, scoring and formatting rules are
deterministic and testable.

## Included sources

- Remotive public API
- Remote OK public API
- Arbeitnow public API (remote listings only)
- We Work Remotely RSS
- CryptocurrencyJobs RSS
- CrowdGen by Appen's public project pages
- Mercor's public Explore listing data (fails safely if its page structure changes)

Every source is isolated: one failure is logged and does not stop the remaining sources.
Additional sources should be added only after their access/redistribution terms and
location data have been checked.

## Sheet design

Use the dedicated **Quality Job Scraper** workbook and its `QualityJobs` tab. The supplied
workbook already contains the exact header and a separate `Setup` tab. Its first seven
columns remain compatible with the old `RawJobs` layout:

```text
scrape_timestamp | source | title | company | location | job_url | processed
```

It then adds the fields required for quality control and better Telegram posts, including
`published_at`, `category`, `experience_level`, `quality_score`, `telegram_post`,
`is_referral`, `direct_url`, `canonical_url` and `fingerprint`.

Do not point Make at `QualityJobs` until a dry run and one controlled live row have been
checked. The legacy scraper may continue writing to the old workbook or `RawJobs`; it will
no longer affect the channel after Make is switched.

## Local test

Python 3.11+ is required.

```bash
python -m venv .venv
source .venv/bin/activate       # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -q
quality-jobs --dry-run --no-link-check --source remotive
```

Run a normal network dry run:

```bash
quality-jobs --dry-run
```

## Google Sheets authorization

1. In Google Cloud, enable the Google Sheets API.
2. Create a service account and download its JSON key.
3. Share the existing spreadsheet with the service account's `client_email` as Editor.
4. Copy the spreadsheet ID from the URL between `/d/` and `/edit`.
5. Store the complete service-account JSON as the GitHub secret
   `GOOGLE_SERVICE_ACCOUNT_JSON`.
6. Store the spreadsheet ID as `GOOGLE_SHEET_ID`.

Never commit the service-account JSON file to GitHub.

## Referral configuration

The deployment defaults to the owner's verified `https://t.mercor.com/H06sH` referral
URL. A `MERCOR_REFERRAL_URL` repository secret can override it without changing code.
Mercor posts use it as the main CTA, keep the original listing as a secondary link, and
display an explicit disclosure.

Referral posts are capped at 20% of each run by default, with a minimum allowance of one
when referrals are enabled so small batches can still include a strong Mercor role. This
prevents monetization from overpowering usefulness. Mercor listings with no stated location are classified as
`us_ca_uk_eu`, not worldwide, in accordance with Mercor's published referral policy.

The `OUTLIER_REFERRAL_URL` setting is reserved for a future source adapter. It is not used
until Outlier provides a stable, permitted listing interface and the owner's exact link is
supplied.

## GitHub deployment

1. Create a GitHub repository and upload this project.
2. Add repository secrets:
   - `MAKE_WEBHOOK_URL` (recommended)
   - `GOOGLE_SHEET_ID`
   - `GOOGLE_SERVICE_ACCOUNT_JSON`
   - `MERCOR_REFERRAL_URL` (optional)
   - `OUTLIER_REFERRAL_URL` (optional; currently inactive)
3. Open **Actions → Collect quality jobs → Run workflow**.
4. Keep `dry_run` enabled for the first run and inspect the log.
5. Run it once with `dry_run` disabled. Confirm rows appear in `QualityJobs`.

The primary schedule is 07:15 Lagos time, with recovery attempts at 11:35 and 18:45.
Every live workflow run uses `--daily-limit 2`: only remaining slots are collected;
confirmed submissions are counted in `data/daily.json`, resetting at Lagos midnight.
A zero-job run leaves the slots available for a later recovery attempt. Preview runs
do not consume the quota. The October 7 migration seed records the two jobs already
submitted before this guard was installed. GitHub can still delay or drop scheduled
triggers; these backups reduce that risk but do not guarantee execution times.

Each confirmed Make submission saves its deduplication keys and increments the daily
count before the next row is sent. The workflow saves state even after a later failure,
and uses a different cache key for each retry attempt. The legacy cache is restored
separately during migration so earlier duplicate tracking is preserved.

## Make change

Clone the working Make scenario before editing it.

1. Change the Google Sheets module's worksheet from `RawJobs` to `QualityJobs`.
2. Keep its filter as `processed = FALSE`.
3. In the Telegram module, map the `telegram_post` column as the message body.
4. Set parse mode to **HTML** and disable link previews.
5. Keep the final Google Sheets update module, but ensure it updates the originating row
   and writes `TRUE` to `processed`.
6. Test with one row before enabling scheduling.

The scraper supplies at most two new jobs daily (one per source); empty slots stay empty. Make should choose the highest
`quality_score` first and avoid dumping several posts at once.

## Safe operating notes

- `403`, `401` and `429` pages are marked `protected`, not dead, because many legitimate
  job boards block automated link checks.
- A temporary source outage cannot delete or overwrite sheet data.
- The pipeline only appends; Make owns the `processed` update.
- No opportunity requiring payment from an applicant should be published.
- “Entry level” means lower stated requirements, never guaranteed acceptance.
- Keep referral disclosure visible in every monetized post.



## Global curation update

Channel title: **Remote Jobs Worldwide | Tech, Web3 & More**.
Description: Curated remote jobs in tech, Web3, AI, support, marketing and design.
Worldwide and region-restricted opportunities, with pay and eligibility shown when
available. Search role and region hashtags to find relevant listings.

The global brand does not imply worldwide eligibility for every listing. Original
location details remain visible; #USOnly and #EUOnly are reserved for explicit scopes.
#AfricaEligible remains a filter tag, not the leading brand. Unknown eligibility is held.
Hashtags support browsing/search; no personalized role-alert bot is connected.

Defaults: maximum 2 jobs daily, maximum 1 per source, score at least 9, age at most
7 days. No weaker jobs are added to fill a quota. Cross-source and previous-run
URL/title-company duplicates are excluded before spending the link-check budget.
The 26-column Sheets payload stays unchanged, including the Apply here anchor needed
by Make's existing validity filter.

Posts show title, employer, pay (or Pay not disclosed), location, one factual reason
to apply, application link, Save this to Saved Messages, and role/region tags.
Company-description paragraphs and reaction/share prompts are removed. Referral
posts retain disclosure and the original listing link.

Remaining live Make checks: Telegram parse mode HTML, Disable link preview Yes,
Search Rows limit 1, sort quality_score descending if supported, then mark the
originating row processed only after a successful send. Before switching format,
review old pending rows so stale long posts do not continue to drain from the queue.
Update the Telegram channel title/description using the owner's admin access.


## Beginner AI and automation coverage

Direct public employer feeds now include Welo Data / Welo Global, RWS TrainAI,
Skyward IT Solutions, and Minted, alongside the existing CrowdGen and general job boards.
Only remote AI/automation vacancies from these feeds are candidates; dated listings
still expire after seven days. Talent networks, future-opportunity pools and speculative
applications are held rather than represented as current jobs. No dates are invented.

Beginner AI/automation candidates receive first consideration within the existing
quality, source and referral caps. Make.com, Zapier, n8n and workflow automation roles
use #Automation and #AutomationJobs. Tool names alone do not mean entry-level;
experience requirements override junior titles, and specialist postgraduate
requirements prevent an entry label. The full requirements are checked before the
short Telegram message is generated. The output remains the same 26-column payload.
