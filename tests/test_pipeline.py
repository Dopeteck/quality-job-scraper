from datetime import datetime, timedelta, timezone

from quality_jobs.config import Settings
from quality_jobs.models import Job
from quality_jobs.pipeline import process
from quality_jobs.text import canonicalize_url
from quality_jobs.sources import _date
from quality_jobs.state import load_seen, save_seen
from quality_jobs.webhook import payload


def settings(**overrides) -> Settings:
    base = dict(
        google_sheet_id="",
        google_worksheet="QualityJobs",
        google_service_account_json="",
        make_webhook_url="",
        state_path="data/seen.json",
        mercor_referral_url="",
        outlier_referral_url="",
        min_quality_score=8,
        max_job_age_days=10,
        max_per_run=20,
        max_per_source=6,
        max_referral_share=0.2,
        entry_priority_share=0.35,
        ai_priority_share=0.30,
        link_check_enabled=False,
        require_known_location=True,
        request_timeout_seconds=2,
        allowed_remote_scopes=frozenset({"worldwide", "africa", "unknown"}),
        user_agent="test",
    )
    base.update(overrides)
    return Settings(**base)


def job(**overrides) -> Job:
    base = dict(
        source="Remotive",
        title="Junior AI Response Evaluator",
        company="Example Labs",
        location="Worldwide",
        direct_url="https://example.com/jobs/123?utm_source=test",
        published_at=datetime.now(timezone.utc) - timedelta(hours=12),
        description=(
            "Evaluate artificial intelligence responses using written guidelines. "
            "This is a remote entry-level contract opportunity open worldwide."
        ),
        salary="$18–$25/hour",
    )
    base.update(overrides)
    return Job(**base)


def test_canonical_url_removes_tracking():
    assert canonicalize_url("HTTPS://Example.com/jobs/1/?utm_source=x&id=2#top") == (
        "https://example.com/jobs/1?id=2"
    )


def test_epoch_timestamp_is_parsed():
    assert _date(1790078119) == datetime(2026, 9, 22, 11, 55, 19, tzinfo=timezone.utc)


def test_good_ai_entry_job_is_accepted_and_formatted():
    accepted, rejected = process([job()], settings())
    assert len(accepted) == 1
    assert not rejected
    item = accepted[0]
    assert item.category == "ai"
    assert item.experience_level == "entry"
    assert item.africa_eligible is True
    assert item.quality_score >= 8
    assert "#AIJobs" in item.telegram_post
    assert "Referral disclosure" not in item.telegram_post


def test_old_job_is_rejected():
    accepted, rejected = process(
        [job(published_at=datetime.now(timezone.utc) - timedelta(days=14))], settings()
    )
    assert not accepted
    assert "days old" in rejected[0].quality_reasons[0]


def test_unpaid_promotion_is_rejected():
    accepted, rejected = process(
        [job(title="Volunteer Ambassador", description="Join our volunteer ambassador program")],
        settings(),
    )
    assert not accepted
    assert rejected[0].quality_score == -100


def test_duplicate_title_and_company_is_rejected():
    first = job(direct_url="https://a.example/jobs/1")
    second = job(direct_url="https://b.example/jobs/99")
    accepted, rejected = process([first, second], settings())
    assert len(accepted) == 1
    assert any("duplicate" in item.quality_reasons[0] for item in rejected)


def test_mercor_unspecified_location_is_not_treated_as_worldwide():
    item = job(
        source="Mercor",
        location="",
        description="Evaluate AI answers using your subject-matter expertise.",
        referral_url="https://example.com/referral",
    )
    accepted, rejected = process(
        [item],
        settings(
            min_quality_score=-10,
            allowed_remote_scopes=frozenset({"us_ca_uk_eu"}),
        ),
    )
    assert not rejected
    assert accepted[0].remote_scope == "us_ca_uk_eu"
    assert accepted[0].africa_eligible is False
    assert "Referral disclosure" in accepted[0].telegram_post


def test_unknown_location_is_rejected_when_strict():
    accepted, rejected = process(
        [job(location="Remote", description="A fresh remote software role.")], settings()
    )
    assert not accepted
    assert len(rejected) == 1


def test_referral_share_is_capped():
    items = []
    for index in range(10):
        items.append(
            job(
                title=f"Junior AI Evaluator {index}",
                direct_url=f"https://example.com/jobs/{index}",
                referral_url="https://example.com/referral",
            )
        )
    accepted, _ = process(
        items,
        settings(max_per_run=10, max_per_source=20, max_referral_share=0.2),
    )
    assert len(accepted) == 2


def test_make_payload_matches_sheet_headers():
    accepted, _ = process([job()], settings())
    data = payload(accepted[0])
    assert len(data) == 26
    assert data["title"] == "Junior AI Response Evaluator"
    assert data["processed"] is False
    assert data["telegram_post"]


def test_seen_state_round_trip(tmp_path):
    accepted, _ = process([job()], settings())
    state_path = tmp_path / "seen.json"

    save_seen(str(state_path), set(), set(), accepted)
    urls, fingerprints = load_seen(str(state_path))

    assert accepted[0].canonical_url in urls
    assert accepted[0].fingerprint in fingerprints


def test_seen_state_rejects_job_on_later_run(tmp_path):
    accepted, _ = process([job()], settings())
    state_path = tmp_path / "seen.json"
    save_seen(str(state_path), set(), set(), accepted)
    urls, fingerprints = load_seen(str(state_path))

    repeated, rejected = process([job()], settings(), urls, fingerprints)

    assert not repeated
    assert rejected[0].quality_reasons == ["rejected: duplicate"]
