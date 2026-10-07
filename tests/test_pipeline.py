from datetime import datetime, timedelta, timezone

from quality_jobs.config import Settings
from quality_jobs.models import Job
from quality_jobs.pipeline import process
from quality_jobs.text import canonicalize_url
from quality_jobs.sources import _date
from quality_jobs.sources import verify_candidate_details
from quality_jobs.state import load_seen, save_seen
from quality_jobs.site import payload as site_payload
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
    assert "Referral:" in accepted[0].telegram_post


def test_unknown_location_is_rejected_when_strict():
    accepted, rejected = process(
        [job(location="Remote", description="A fresh remote software role.")], settings()
    )
    assert not accepted
    assert len(rejected) == 1


def test_arabic_listing_is_rejected():
    accepted, rejected = process(
        [
            job(
                title="مشروع تسجيل صوتي للعمل عن بعد",
                description=(
                    "نبحث عن متحدثين باللغة العربية لتسجيل عبارات قصيرة "
                    "باستخدام الهاتف من المنزل مقابل أجر بعد مراجعة الجودة."
                ),
                location="UAE",
            )
        ],
        settings(allowed_remote_scopes=frozenset({"worldwide", "africa", "emea"})),
    )
    assert not accepted
    assert rejected[0].quality_reasons == ["rejected: non-English listing"]


def test_english_job_outside_target_region_is_rejected():
    accepted, rejected = process(
        [
            job(
                location="United States only",
                description="Remote AI evaluation role for candidates based in the United States.",
            )
        ],
        settings(allowed_remote_scopes=frozenset({"worldwide", "africa", "emea"})),
    )
    assert not accepted
    assert rejected[0].quality_reasons == [
        "rejected: outside target region (us)"
    ]


def test_brazil_restriction_overrides_worldwide_marketing_copy():
    accepted, rejected = process(
        [
            job(
                location="Remote - Brazil",
                description=(
                    "Work remotely from anywhere with no geographical restrictions. "
                    "Location: Remote - Brazil. To be considered, you must reside in Brazil."
                ),
            )
        ],
        settings(allowed_remote_scopes=frozenset({"worldwide", "africa", "emea"})),
    )
    assert not accepted
    assert rejected[0].quality_reasons == ["rejected: outside target region (latam)"]


def test_cryptocurrencyjobs_detail_verifies_location(monkeypatch):
    class Response:
        text = """
        <main><p>Work remotely from anywhere.</p>
        <p><strong>Location</strong>: Remote - Brazil</p>
        <p>To be considered, you must reside in Brazil.</p>
        <p><strong>About the role</strong></p></main>
        """

        def raise_for_status(self):
            return None

    monkeypatch.setattr("quality_jobs.sources.requests.get", lambda *args, **kwargs: Response())
    item = job(source="CryptocurrencyJobs", location="Remote")

    assert verify_candidate_details(item, settings()) is True
    assert item.location == "Remote - Brazil"


def test_telegram_post_is_short_useful_and_filterable():
    accepted, _ = process([job()], settings())
    post = accepted[0].telegram_post
    assert "Why it stands out" in post
    assert "pay disclosed" in post
    assert "Save this to Saved Messages" in post
    assert "#Worldwide" in post and "#AfricaEligible" in post
    assert "React" not in post and "Evaluate artificial intelligence responses" not in post
    assert len(post) < 800


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


def test_small_batch_can_include_one_referral_job():
    items = [
        job(
            title=f"Junior AI Evaluator {index}",
            direct_url=f"https://example.com/jobs/{index}",
            referral_url="https://t.mercor.com/H06sH" if index == 0 else "",
        )
        for index in range(3)
    ]
    accepted, _ = process(
        items,
        settings(max_per_run=3, max_per_source=3, max_referral_share=0.2),
    )
    assert len(accepted) == 3
    assert sum(item.is_referral for item in accepted) == 1


def test_make_payload_matches_sheet_headers():
    accepted, _ = process([job()], settings())
    data = payload(accepted[0])
    assert len(data) == 26
    assert data["title"] == "Junior AI Response Evaluator"
    assert data["processed"] is False
    assert data["telegram_post"]


def test_site_payload_uses_effective_apply_url_and_iso_dates():
    accepted, _ = process(
        [job(referral_url="https://t.mercor.com/H06sH")],
        settings(max_referral_share=1),
    )
    data = site_payload(accepted[0])
    assert data["apply_url"] == "https://t.mercor.com/H06sH"
    assert data["direct_url"].startswith("https://example.com/jobs/123")
    assert data["remote_scope"] == "worldwide"
    assert data["published_at"].endswith("Z")
    assert data["scraped_at"].endswith("Z")


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



def test_global_defaults_are_curated():
    config = Settings.from_env()
    assert {"worldwide", "us", "eu", "latam", "asia"} <= config.allowed_remote_scopes
    assert config.max_per_run == 2 and config.max_per_source == 1
    assert config.max_job_age_days == 7 and config.min_quality_score == 9


def test_location_restrictions_override_company_global_copy():
    for location, scope, tag in [
        ("United States only", "us", "#USOnly"),
        ("EU only", "eu", "#EUOnly"),
        ("Canada", "canada", "#CanadaOnly"),
        ("Remote - Brazil", "latam", "#LATAM"),
        ("EMEA", "emea", "#EMEA"),
    ]:
        item = job(title="Customer Support Specialist", location=location,
                   description="Our company serves customers worldwide. Help customers resolve requests.")
        accepted, _ = process([item], settings(allowed_remote_scopes=frozenset({scope})))
        assert len(accepted) == 1
        post = accepted[0].telegram_post
        assert "#Support" in post and tag in post
        assert "#Worldwide" not in post
        assert location in post
        assert accepted[0].africa_eligible is (scope == "emea")


def test_role_tags_follow_title_not_company_description():
    for title, tag in [("Software Developer", "#Developer"),
                       ("Marketing Manager", "#Marketing"),
                       ("Product Designer", "#Design")]:
        accepted, _ = process([job(title=title)], settings())
        assert tag in accepted[0].telegram_post


def test_global_batch_limit_and_source_diversity():
    items = [job(title=f"AI Evaluator {i}", source=source,
                 direct_url=f"https://example.com/jobs/{i}")
             for i, source in enumerate(["Remotive", "Remotive", "RemoteOK"])]
    selected, _ = process(items, settings(max_per_run=2, max_per_source=1))
    assert len(selected) == 2
    assert len({item.source for item in selected}) == 2


def test_cross_source_duplicate_does_not_consume_link_check_pool(monkeypatch):
    checked = []
    def verify(item, config):
        checked.append(item.direct_url)
        return "200"
    monkeypatch.setattr("quality_jobs.pipeline._verify_and_check", verify)
    first = job(direct_url="https://a.example/job/1")
    duplicate = job(source="RemoteOK", direct_url="https://b.example/job/1")
    unique = job(title="Junior Data Annotator", direct_url="https://c.example/job/2")
    selected, _ = process([first, duplicate, unique], settings(link_check_enabled=True))
    assert len(checked) == 2 and len(selected) == 2


def test_previous_run_duplicates_do_not_consume_link_check_pool(monkeypatch):
    checked = []
    monkeypatch.setattr("quality_jobs.pipeline._verify_and_check",
                        lambda item, config: checked.append(item.title) or "200")
    first, _ = process([job()], settings())
    repeated = job()
    unique = job(title="Junior Data Annotator", direct_url="https://example.com/jobs/2")
    selected, _ = process([repeated, unique], settings(link_check_enabled=True),
                          {first[0].canonical_url}, {first[0].fingerprint})
    assert checked == [unique.title] and len(selected) == 1


def test_mixed_regions_are_not_mislabeled_us_only():
    accepted, rejected = process([job(location="US and Europe",
        description="Remote support role. Handle customer requests.")], settings())
    assert not accepted and rejected[0].remote_scope == "unknown"


def test_ai_candidate_gets_verified_amid_many_entry_roles(monkeypatch):
    checked = []
    monkeypatch.setattr("quality_jobs.pipeline._verify_and_check",
                        lambda item, config: checked.append(item.title) or "200")
    entries = [job(title=f"Junior Support Agent {i}", source=f"Source {i}",
                   description="Help customers resolve requests. Remote worldwide.",
                   direct_url=f"https://example.com/entry/{i}") for i in range(8)]
    ai = job(title="Senior AI Safety Researcher", source="Mercor",
             description="Evaluate artificial intelligence models. Remote worldwide.",
             direct_url="https://work.mercor.com/jobs/research", referral_url="https://t.mercor.com/H06sH")
    selected, _ = process(entries + [ai], settings(max_per_run=2, max_per_source=1,
                          ai_priority_share=.4, entry_priority_share=.4, link_check_enabled=True))
    assert ai.title in checked
    assert ai in selected
    assert ai.effective_url == "https://t.mercor.com/H06sH"


def test_current_mercor_ai_titles_are_classified():
    from quality_jobs.classify import classify
    for title in ["Multimodal Image Expert", "AI Safety and Model Evaluation", "AI Engineer", "LLM Researcher"]:
        assert classify(job(title=title, description="Evaluate outputs.")).category == "ai"


def test_automation_beginner_roles_are_prioritized_and_tagged():
    automation = job(title='Junior Workflow Automation Assistant', source='Employer',
                     description='Build Make.com and n8n workflows. No experience required.',
                     direct_url='https://example.com/automation')
    senior = job(title='Senior AI Researcher', source='Mercor', salary='$100/hour',
                 direct_url='https://example.com/senior')
    selected, _ = process([senior, automation], settings(max_per_run=1))
    assert selected == [automation]
    assert '#AutomationJobs' in automation.telegram_post
    assert '#EntryLevel' in automation.telegram_post


def test_no_code_or_mentoring_does_not_imply_beginner():
    from quality_jobs.classify import classify
    for description in ['Build no-code workflows using n8n and mentor junior colleagues.',
                        'Use Make.com. Requires 5+ years of experience.']:
        item = classify(job(title='Automation Specialist', description=description))
        assert item.experience_level != 'entry'


def test_company_automation_copy_does_not_create_automation_tag():
    from quality_jobs.classify import is_automation
    assert not is_automation(job(title='AI Data Annotator',
        description='Our company provides automation services. Label images.'))
    assert is_automation(job(title='Operations Specialist',
        description='Build workflows using Make.com and n8n.'))


def test_requirements_override_junior_title_and_ignore_manager_in_description():
    from quality_jobs.classify import classify
    assert classify(job(title='Junior Automation Developer',
                        description='Requires 3–5 years of professional experience.')).experience_level == 'mid'
    assert classify(job(title='Junior Automation Assistant',
                        description='Report to a manager. No experience required.')).experience_level == 'entry'


def test_talent_pools_are_not_promoted_as_live_vacancies():
    for title in ['AI Trainers Network - English', 'Future Opportunities: AI Talent Pool',
                  'Initiative application (m/f/x)']:
        selected, rejected = process([job(title=title)], settings())
        assert not selected
        assert rejected[0].quality_score == -100


def test_title_country_restriction_overrides_worldwide_location():
    selected, _ = process([job(title='AI Evaluator (United States)', location='Remote, Worldwide')],
                         settings(allowed_remote_scopes=frozenset({'us'})))
    assert selected[0].remote_scope == 'us'
    assert '#Worldwide' not in selected[0].telegram_post
