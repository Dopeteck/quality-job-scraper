from __future__ import annotations

from datetime import timezone

import gspread

from .config import Settings
from .models import Job


HEADERS = [
    # Keep the first seven columns compatible with the existing Make scenario.
    "scrape_timestamp",
    "source",
    "title",
    "company",
    "location",
    "job_url",
    "processed",
    "published_at",
    "summary",
    "category",
    "opportunity_type",
    "experience_level",
    "salary",
    "remote_scope",
    "africa_eligible",
    "search_keywords",
    "quality_score",
    "quality_reasons",
    "telegram_post",
    "is_referral",
    "referral_disclosure",
    "direct_url",
    "canonical_url",
    "fingerprint",
    "source_job_id",
    "link_status",
]


def _client(settings: Settings) -> gspread.Client:
    info = settings.service_account_info()
    if not info:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON is required unless --dry-run is used")
    return gspread.service_account_from_dict(info)


def worksheet(settings: Settings) -> gspread.Worksheet:
    spreadsheet = _client(settings).open_by_key(settings.google_sheet_id)
    try:
        ws = spreadsheet.worksheet(settings.google_worksheet)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(
            title=settings.google_worksheet, rows=2000, cols=len(HEADERS)
        )
    first_row = ws.row_values(1)
    if not first_row:
        ws.append_row(HEADERS, value_input_option="RAW")
    elif first_row != HEADERS:
        raise ValueError(
            f"Worksheet header mismatch in {settings.google_worksheet}. "
            "Use a new empty tab or replace row 1 with the documented headers."
        )
    return ws


def existing_keys(ws: gspread.Worksheet) -> tuple[set[str], set[str]]:
    records = ws.get_all_records(expected_headers=HEADERS)
    urls = {str(row.get("canonical_url", "")).strip() for row in records}
    fingerprints = {str(row.get("fingerprint", "")).strip() for row in records}
    return {x for x in urls if x}, {x for x in fingerprints if x}


def _iso(value) -> str:
    if not value:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def row(job: Job) -> list[object]:
    return [
        _iso(job.scraped_at),
        job.source,
        job.title,
        job.company,
        job.location,
        job.effective_url,
        False,
        _iso(job.published_at),
        job.description,
        job.category,
        job.opportunity_type,
        job.experience_level,
        job.salary,
        job.remote_scope,
        job.africa_eligible,
        job.search_keywords,
        job.quality_score,
        "; ".join(job.quality_reasons),
        job.telegram_post,
        job.is_referral,
        job.referral_disclosure,
        job.direct_url,
        job.canonical_url,
        job.fingerprint,
        job.source_job_id,
        job.link_status,
    ]


def append_jobs(ws: gspread.Worksheet, jobs: list[Job]) -> None:
    if jobs:
        ws.append_rows([row(job) for job in jobs], value_input_option="RAW")

