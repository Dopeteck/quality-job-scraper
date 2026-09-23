# Quality Job Scraper

A zero-paid-API pipeline that finds, checks, scores and formats recent remote tech,
Web3, AI-training and accessible entry-level opportunities. Accepted jobs are appended
to a Google Sheets tab that an existing Make scenario can publish to Telegram.

## What it fixes

- rejects jobs older than the configured maximum (10 days by default)
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

Create a new empty tab named `QualityJobs` in the existing **Job Aggregator Database**.
The scraper creates its header automatically. Its first seven columns remain compatible
with the old `RawJobs` layout:

```text
scrape_timestamp | source | title | company | location | job_url | processed
```

It then adds the fields required for quality control and better Telegram posts, including
`published_at`, `category`, `experience_level`, `quality_score`, `telegram_post`,
`is_referral`, `direct_url`, `canonical_url` and `fingerprint`.

Do not point Make at `QualityJobs` until a dry run and one controlled live row have been
checked. The unidentified legacy scraper may continue writing to `RawJobs`; it will no
longer affect the channel after Make is switched.

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

Set `MERCOR_REFERRAL_URL` only to the exact referral URL from the owner's Mercor account.
When present, Mercor posts use it as the main CTA, keep the original listing as a secondary
link, and display an explicit disclosure.

Referral posts are capped at 20% of each run by default. This prevents monetization from
overpowering usefulness. Mercor listings with no stated location are classified as
`us_ca_uk_eu`, not worldwide, in accordance with Mercor's published referral policy.

The `OUTLIER_REFERRAL_URL` setting is reserved for a future source adapter. It is not used
until Outlier provides a stable, permitted listing interface and the owner's exact link is
supplied.

## GitHub deployment

1. Create a GitHub repository and upload this project.
2. Add repository secrets:
   - `GOOGLE_SHEET_ID`
   - `GOOGLE_SERVICE_ACCOUNT_JSON`
   - `MERCOR_REFERRAL_URL` (optional)
   - `OUTLIER_REFERRAL_URL` (optional; currently inactive)
3. Open **Actions → Collect quality jobs → Run workflow**.
4. Keep `dry_run` enabled for the first run and inspect the log.
5. Run it once with `dry_run` disabled. Confirm rows appear in `QualityJobs`.

The scheduled workflow runs once daily at 07:15 West Africa Time and adds no more than
five jobs. GitHub may delay scheduled jobs slightly during busy periods.

## Make change

Clone the working Make scenario before editing it.

1. Change the Google Sheets module's worksheet from `RawJobs` to `QualityJobs`.
2. Keep its filter as `processed = FALSE`.
3. In the Telegram module, map the `telegram_post` column as the message body.
4. Set parse mode to **HTML** and disable link previews if desired.
5. Keep the final Google Sheets update module, but ensure it updates the originating row
   and writes `TRUE` to `processed`.
6. Test with one row before enabling scheduling.

Suggested publishing cadence is three to five posts daily. Make should choose the highest
`quality_score` first and avoid dumping several posts at once.

## Safe operating notes

- `403`, `401` and `429` pages are marked `protected`, not dead, because many legitimate
  job boards block automated link checks.
- A temporary source outage cannot delete or overwrite sheet data.
- The pipeline only appends; Make owns the `processed` update.
- No opportunity requiring payment from an applicant should be published.
- “Entry level” means lower stated requirements, never guaranteed acceptance.
- Keep referral disclosure visible in every monetized post.
