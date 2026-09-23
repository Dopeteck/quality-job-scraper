from datetime import datetime, timezone

from quality_jobs.models import Job
from quality_jobs.sheets import HEADERS, row


def test_sheet_contract_keeps_make_columns_first():
    assert HEADERS[:7] == [
        "scrape_timestamp",
        "source",
        "title",
        "company",
        "location",
        "job_url",
        "processed",
    ]


def test_sheet_row_matches_headers():
    item = Job(
        source="Test",
        title="QA Tester",
        company="Example",
        location="Worldwide",
        direct_url="https://example.com/job",
        published_at=datetime.now(timezone.utc),
    )
    assert len(row(item)) == len(HEADERS)
    assert row(item)[6] is False

