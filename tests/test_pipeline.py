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
        salary="$18â€“$25/hour",
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


def test_customer_support_is_classified_and_post_includes_listing_context():
    listing = job(
        title="Customer Support Specialist",
        description="Help customers troubleshoot account and billing issues. Remote worldwide.",
        location="Worldwide",
        salary="",
    )
    accepted_jobs, _ = process([listing], settings())
    assert accepted_jobs[0].category == "support"
    assert "Help customers troubleshoot account" in accepted_jobs[0].telegram_post
    assert "Pay not disclosed" in accepted_jobs[0].telegram_post


def test_verified_africa_scope_is_not_scored_below_worldwide_for_scope_alone():
    worldwide = job(title="Support Specialist", remote_scope="worldwide", africa_eligible=True)
    africa = job(title="Support Specialist", remote_scope="africa", africa_eligible=True)
    from quality_jobs.scoring import score_job

    score_job(worldwide, settings())
    score_job(africa, settings())
    assert worldwide.quality_score == africa.quality_score


def test_country_restricted_african_job_keeps_country_eligibility_visible():
    listing = job(
        title="Customer Support Specialist",
        location="Nigeria",
        description="Remote from Nigeria. Support customers using our product.",
    )
    accepted_jobs, _ = process(
        [listing],
        settings(allowed_remote_scopes=frozenset({"worldwide", "africa", "africa_nigeria"})),
    )
    assert accepted_jobs[0].remote_scope == "africa_nigeria"
    assert accepted_jobs[0].africa_eligible is True
    assert "Nigeria only" in accepted_jobs[0].telegram_post
    assert "#NigeriaOnly" in accepted_jobs[0].telegram_post


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
                title="Ù…Ø´Ø±ÙˆØ¹ ØªØ³Ø¬ÙŠÙ„ ØµÙˆØªÙŠ Ù„Ù„Ø¹Ù…Ù„ Ø¹Ù† Ø¨Ø¹Ø¯",
                description=(
                    "Ù†Ø¨Ø­Ø« Ø¹Ù† Ù…ØªØ­Ø¯Ø«ÙŠÙ† Ø¨Ø§Ù„Ù„ØºØ© Ø§Ù„Ø¹Ø±Ø¨ÙŠØ© Ù„ØªØ³Ø¬ÙŠÙ„ Ø¹Ø¨Ø§Ø±Ø§Øª Ù‚ØµÙŠØ±Ø© "
                    "Ø¨Ø§Ø³ØªØ®Ø¯Ø§Ù… Ø§Ù„Ù‡Ø§ØªÙ Ù…Ù† Ø§Ù„Ù…Ù†Ø²Ù„ Ù…Ù‚Ø§Ø¨Ù„ Ø£Ø¬Ø± Ø¨Ø¹Ø¯ Ù…Ø±Ø§Ø¬Ø¹Ø© Ø§Ù„Ø¬ÙˆØ¯Ø©."
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
    for index in range(10):ã-¢G§²ÚîÆ­y×G3¢ò÷BæÖW&6÷"æ6öÒôƒg4‚"•ÒÀ¢6WGF–æw2†Ö…÷&VfW'&Å÷6†&SÓ’À¢¢FFÒ6—FU÷–ÆöB†66WFVE³Ò¢76W'BFF²&Ç•÷W&Â%ÒÓÒ&‡GG3¢ò÷BæÖW&6÷"æ6öÒôƒg4‚ ¢76W'BFF²&F—&V7E÷W&Â%Òç7F'G7v—F‚‚&‡GG3¢òöW†×ÆRæ6öÒö¦ö'2ó#2"¢76W'BFF²'&VÖ÷FU÷66÷R%ÒÓÒ'v÷&ÆGv–FR ¢76W'BFF²'V&Æ—6†VEöB%ÒæVæG7v—F‚‚%¢"¢76W'BFF²'67&VEöB%ÒæVæG7v—F‚‚%¢"  ¦FVbFW7E÷6—FU÷7VÖÖ'•÷&W7V7G5ö•öÆ–Ö—E÷v—F†÷WEöÆ÷6–æu÷66÷&–æu÷&WV—&VÖVçG2‚“ ¢—FVÒÒ¦ö"†FW67&—F–öãÒvr¢3““’²uÅScF&"r²u&WV—&W2R–V'2öbW‡W&–Væ6Râr¢S¢÷&–v–æÂÒ—FVÒæFW67&—F–öà¢FFÒ6—FU÷–ÆöB†—FVÒ¢76W'BÆVâ†FF²w7VÖÖ'’uÒæVæ6öFR‚wWFbÓbÖÆRr’’ÃÒƒ ¢76W'B—FVÒæFW67&—F–öâÓÒ÷&–v–æÀ¢76W'B6—FU÷–ÆöB†¦ö"†FW67&—F–öãÒu6†÷'BFW67&—F–öâr’•²w7VÖÖ'’uÒÓÒu6†÷'BFW67&—F–öâp  ¦FVbFW7E÷6VVå÷7FFU÷&÷VæE÷G&—‡F×÷F‚“ ¢66WFVBÂòÒ&ö6W72…¶¦ö"‚•ÒÂ6WGF–æw2‚’¢7FFU÷F‚ÒF×÷F‚ò'6VVâæ§6öâ  ¢6fU÷6VVâ‡7G"‡7FFU÷F‚’Â6WB‚’Â6WB‚’Â66WFVB¢W&Ç2Âf–ævW'&–çG2ÒÆöE÷6VVâ‡7G"‡7FFU÷F‚’ ¢76W'B66WFVE³Òæ6æöæ–6Å÷W&Â–âW&Ç0¢76W'B66WFVE³Òæf–ævW'&–çB–âf–ævW'&–çG0  ¦FVbFW7E÷6VVå÷7FFU÷&V¦V7G5ö¦ö%ööåöÆFW%÷'Vâ‡F×÷F‚“ ¢66WFVBÂòÒ&ö6W72…¶¦ö"‚•ÒÂ6WGF–æw2‚’¢7FFU÷F‚ÒF×÷F‚ò'6VVâæ§6öâ ¢6fU÷6VVâ‡7G"‡7FFU÷F‚’Â6WB‚’Â6WB‚’Â66WFVB¢W&Ç2Âf–ævW'&–çG2ÒÆöE÷6VVâ‡7G"‡7FFU÷F‚’ ¢&WVFVBÂ&V¦V7FVBÒ&ö6W72…¶¦ö"‚•ÒÂ6WGF–æw2‚’ÂW&Ç2Âf–ævW'&–çG2 ¢76W'Bæ÷B&WVFV@¢76W'B&V¦V7FVE³ÒçVÆ—G•÷&V6öç2ÓÒ²'&V¦V7FVC¢GWÆ–6FR%Ğ   ¦FVbFW7EövÆö&ÅöFVfVÇG5ö&Uö7W&FVB‚“ ¢6öæf–rÒ6WGF–æw2æg&öÕöVçb‚¢76W'B²'v÷&ÆGv–FR"Â'W2"Â&WR"Â&ÆFÒ"Â&6–'ÒÃÒ6öæf–ræÆÆ÷vVE÷&VÖ÷FU÷66÷W0¢76W'B6öæf–ræÖ…÷W%÷'VâÓÒ"æB6öæf–ræÖ…÷W%÷6÷W&6RÓÒ¢76W'B6öæf–ræÖ…ö¦ö%övUöF—2ÓÒræB6öæf–ræÖ–å÷VÆ—G•÷66÷&RÓÒ  ¦FVbFW7EöÆö6F–öå÷&W7G&–7F–öç5ö÷fW'&–FUö6ö×ç•övÆö&Åö6÷’‚“ ¢f÷"Æö6F–öâÂ66÷RÂFr–â°¢‚%Væ—FVB7FFW2öæÇ’"Â'W2"Â"5U4öæÇ’"’À¢‚$URöæÇ’"Â&WR"Â"4UTöæÇ’"’À¢‚$6æF"Â&6æF"Â"46æFöæÇ’"’À¢‚%&VÖ÷FRÒ'&¦–Â"Â&ÆFÒ"Â"4ÄDÒ"’À¢‚$TÔT"Â&VÖV"Â"4TÔT"’À¢Ó ¢—FVÒÒ¦ö"‡F—FÆSÒ$7W7FöÖW"7W÷'B7V6–Æ—7B"ÂÆö6F–öãÖÆö6F–öâÀ¢FW67&—F–öãÒ$÷W"6ö×ç’6W'fW27W7FöÖW'2v÷&ÆGv–FRâ†VÇ7W7FöÖW'2&W6öÇfR&WVW7G2â"¢66WFVBÂòÒ&ö6W72…¶—FVÕÒÂ6WGF–æw2†ÆÆ÷vVE÷&VÖ÷FU÷66÷W3Ög&÷¦Vç6WB‡·66÷WÒ’’¢76W'BÆVâ†66WFVB’ÓÒ¢÷7BÒ66WFVE³ÒçFVÆVw&Õ÷÷7@¢76W'B"57W÷'B"–â÷7BæBFr–â÷7@¢76W'B"5v÷&ÆGv–FR"æ÷B–â÷7@¢76W'BÆö6F–öâ–â÷7@¢76W'B66WFVE³Òæg&–6öVÆ–v–&ÆR—2‡66÷RÓÒ&VÖV"  ¦FVbFW7E÷&öÆU÷Fw5öföÆÆ÷u÷F—FÆUöæ÷Eö6ö×ç•öFW67&—F–öâ‚“ ¢f÷"F—FÆRÂFr–â²‚%6ögGv&RFWfVÆ÷W""Â"4FWfVÆ÷W""’À¢‚$Ö&¶WF–ærÖævW""Â"4Ö&¶WF–ær"’À¢‚%&öGV7BFW6–væW""Â"4FW6–vâ"•Ó ¢66WFVBÂòÒ&ö6W72…¶¦ö"‡F—FÆS×F—FÆR•ÒÂ6WGF–æw2‚’¢76W'BFr–â66WFVE³ÒçFVÆVw&Õ÷÷7@  ¦FVbFW7EövÆö&Åö&F6…öÆ–Ö—EöæE÷6÷W&6UöF—fW'6—G’‚“ ¢—FV×2Ò¶¦ö"‡F—FÆSÖb$’WfÇVF÷"¶—Ò"Â6÷W&6S×6÷W&6RÀ¢F—&V7E÷W&ÃÖb&‡GG3¢òöW†×ÆRæ6öÒö¦ö'2÷¶—Ò"¢f÷"’Â6÷W&6R–âVçVÖW&FR…²%&VÖ÷F—fR"Â%&VÖ÷F—fR"Â%&VÖ÷FTô²%Ò•Ğ¢6VÆV7FVBÂòÒ&ö6W72†—FV×2Â6WGF–æw2†Ö…÷W%÷'VãÓ"ÂÖ…÷W%÷6÷W&6SÓ’¢76W'BÆVâ‡6VÆV7FVB’ÓÒ ¢76W'BÆVâ‡¶—FVÒç6÷W&6Rf÷"—FVÒ–â6VÆV7FVGÒ’ÓÒ   ¦FVbFW7Eö7&÷75÷6÷W&6UöGWÆ–6FUöFöW5öæ÷Eö6öç7VÖUöÆ–æµö6†V6µ÷ööÂ†Ööæ¶W—F6‚“ ¢6†V6¶VBÒµĞ¢FVbfW&–g’†—FVÒÂ6öæf–r“ ¢6†V6¶VBæVæB†—FVÒæF—&V7E÷W&Â¢&WGW&â## ¢Ööæ¶W—F6‚ç6WFGG"‚'VÆ—G•ö¦ö'2ç—VÆ–æRå÷fW&–g•öæEö6†V6²"ÂfW&–g’¢f—'7BÒ¦ö"†F—&V7E÷W&ÃÒ&‡GG3¢òöæW†×ÆRö¦ö"ó"¢GWÆ–6FRÒ¦ö"‡6÷W&6SÒ%&VÖ÷FTô²"ÂF—&V7E÷W&ÃÒ&‡GG3¢òö"æW†×ÆRö¦ö"ó"¢Væ—VRÒ¦ö"‡F—FÆSÒ$§Væ–÷"FFææ÷FF÷""ÂF—&V7E÷W&ÃÒ&‡GG3¢òö2æW†×ÆRö¦ö"ó""¢6VÆV7FVBÂòÒ&ö6W72…¶f—'7BÂGWÆ–6FRÂVæ—VUÒÂ6WGF–æw2†Æ–æµö6†V6µöVæ&ÆVCÕG'VR’¢76W'BÆVâ†6†V6¶VB’ÓÒ"æBÆVâ‡6VÆV7FVB’ÓÒ   ¦FVbFW7E÷&Wf–÷W5÷'VåöGWÆ–6FW5öFõöæ÷Eö6öç7VÖUöÆ–æµö6†V6µ÷ööÂ†Ööæ¶W—F6‚“ ¢6†V6¶VBÒµĞ¢Ööæ¶W—F6‚ç6WFGG"‚'VÆ—G•ö¦ö'2ç—VÆ–æRå÷fW&–g•öæEö6†V6²"À¢ÆÖ&F—FVÒÂ6öæf–s¢6†V6¶VBæVæB†—FVÒçF—FÆR’÷"##"¢f—'7BÂòÒ&ö6W72…¶¦ö"‚•ÒÂ6WGF–æw2‚’¢&WVFVBÒ¦ö"‚¢Væ—VRÒ¦ö"‡F—FÆSÒ$§Væ–÷"FFææ÷FF÷""ÂF—&V7E÷W&ÃÒ&‡GG3¢òöW†×ÆRæ6öÒö¦ö'2ó""¢6VÆV7FVBÂòÒ&ö6W72…·&WVFVBÂVæ—VUÒÂ6WGF–æw2†Æ–æµö6†V6µöVæ&ÆVCÕG'VR’À¢¶f—'7E³Òæ6æöæ–6Å÷W&ÇÒÂ¶f—'7E³Òæf–ævW'&–çGÒ¢76W'B6†V6¶VBÓÒ·Væ—VRçF—FÆUÒæBÆVâ‡6VÆV7FVB’ÓÒ  ¦FVbFW7EöÖ—†VE÷&Vv–öç5ö&Uöæ÷EöÖ—6Æ&VÆVE÷W5ööæÇ’‚“ ¢66WFVBÂ&V¦V7FVBÒ&ö6W72…¶¦ö"†Æö6F–öãÒ%U2æBWW&÷R"À¢FW67&—F–öãÒ%&VÖ÷FR7W÷'B&öÆRâ†æFÆR7W7FöÖW"&WVW7G2â"•ÒÂ6WGF–æw2‚’¢76W'Bæ÷B66WFVBæB&V¦V7FVE³Òç&VÖ÷FU÷66÷RÓÒ'Væ¶æ÷vâ   ¦FVbFW7Eö•ö6æF–FFUövWG5÷fW&–f–VEöÖ–EöÖç•öVçG'•÷&öÆW2†Ööæ¶W—F6‚“ ¢6†V6¶VBÒµĞ¢Ööæ¶W—F6‚ç6WFGG"‚'VÆ—G•ö¦ö'2ç—VÆ–æRå÷fW&–g•öæEö6†V6²"À¢ÆÖ&F—FVÒÂ6öæf–s¢6†V6¶VBæVæB†—FVÒçF—FÆR’÷"##"¢VçG&–W2Ò¶¦ö"‡F—FÆSÖb$§Væ–÷"7W÷'BvVçB¶—Ò"Â6÷W&6SÖb%6÷W&6R¶—Ò"À¢FW67&—F–öãÒ$†VÇ7W7FöÖW'2&W6öÇfR&WVW7G2â&VÖ÷FRv÷&ÆGv–FRâ"À¢F—&V7E÷W&ÃÖb&‡GG3¢òöW†×ÆRæ6öÒöVçG'’÷¶—Ò"’f÷"’–â&ævRƒ‚•Ğ¢’Ò¦ö"‡F—FÆSÒ%6Væ–÷"’6fWG’&W6V&6†W""Â6÷W&6SÒ$ÖW&6÷""À¢FW67&—F–öãÒ$WfÇVFR'F–f–6–Â–çFVÆÆ–vVæ6RÖöFVÇ2â&VÖ÷FRv÷&ÆGv–FRâ"À¢F—&V7E÷W&ÃÒ&‡GG3¢ò÷v÷&²æÖW&6÷"æ6öÒö¦ö'2÷&W6V&6‚"Â&VfW'&Å÷W&ÃÒ&‡GG3¢ò÷BæÖW&6÷"æ6öÒôƒg4‚"¢6VÆV7FVBÂòÒ&ö6W72†VçG&–W2²¶•ÒÂ6WGF–æw2†Ö…÷W%÷'VãÓ"ÂÖ…÷W%÷6÷W&6SÓÀ¢•÷&–÷&—G•÷6†&SÒãBÂVçG'•÷&–÷&—G•÷6†&SÒãBÂÆ–æµö6†V6µöVæ&ÆVCÕG'VR’¢76W'B’çF—FÆR–â6†V6¶V@¢76W'B’–â6VÆV7FV@¢76W'B’æVffV7F—fU÷W&ÂÓÒ&‡GG3¢ò÷BæÖW&6÷"æ6öÒôƒg4‚   ¦FVbFW7Eö7W'&VçEöÖW&6÷%ö•÷F—FÆW5ö&Uö6Æ76–f–VB‚“ ¢g&öÒVÆ—G•ö¦ö'2æ6Æ76–g’–×÷'B6Æ76–g¢f÷"F—FÆR–â²$×VÇF–ÖöFÂ–ÖvRW‡W'B"Â$’6fWG’æBÖöFVÂWfÇVF–öâ"Â$’Væv–æVW""Â$ÄÄÒ&W6V&6†W"%Ó ¢76W'B6Æ76–g’†¦ö"‡F—FÆS×F—FÆRÂFW67&—F–öãÒ$WfÇVFR÷WGWG2â"’’æ6FVv÷'’ÓÒ&’   ¦FVbFW7EöWFöÖF–öåö&Vv–ææW%÷&öÆW5ö&U÷&–÷&—F—¦VEöæE÷FvvVB‚“ ¢WFöÖF–öâÒ¦ö"‡F—FÆSÒt§Væ–÷"v÷&¶fÆ÷rWFöÖF–öâ76—7FçBrÂ6÷W&6SÒtV×Æ÷–W"rÀ¢FW67&—F–öãÒt'V–ÆBÖ¶Ræ6öÒæBã†âv÷&¶fÆ÷w2âæòW‡W&–Væ6R&WV—&VBârÀ¢F—&V7E÷W&ÃÒv‡GG3¢òöW†×ÆRæ6öÒöWFöÖF–öâr¢6Væ–÷"Ò¦ö"‡F—FÆSÒu6Væ–÷"’&W6V&6†W"rÂ6÷W&6SÒtÖW&6÷"rÂ6Æ'“ÒrCö†÷W"rÀ¢F—&V7E÷W&ÃÒv‡GG3¢òöW†×ÆRæ6öÒ÷6Væ–÷"r¢6VÆV7FVBÂòÒ&ö6W72…·6Væ–÷"ÂWFöÖF–öåÒÂ6WGF–æw2†Ö…÷W%÷'VãÓ’¢76W'B6VÆV7FVBÓÒ¶WFöÖF–öåĞ¢76W'Br4WFöÖF–öä¦ö'2r–âWFöÖF–öâçFVÆVw&Õ÷÷7@¢76W'Br4VçG'”ÆWfVÂr–âWFöÖF–öâçFVÆVw&Õ÷÷7@  ¦FVbFW7Eöæõö6öFUö÷%öÖVçF÷&–æuöFöW5öæ÷Eö–×Ç•ö&Vv–ææW"‚“ ¢g&öÒVÆ—G•ö¦ö'2æ6Æ76–g’–×÷'B6Æ76–g¢f÷"FW67&—F–öâ–â²t'V–ÆBæòÖ6öFRv÷&¶fÆ÷w2W6–ærã†âæBÖVçF÷"§Væ–÷"6öÆÆVwVW2ârÀ¢uW6RÖ¶Ræ6öÒâ&WV—&W2R²–V'2öbW‡W&–Væ6RâuÓ ¢—FVÒÒ6Æ76–g’†¦ö"‡F—FÆSÒtWFöÖF–öâ7V6–Æ—7BrÂFW67&—F–öãÖFW67&—F–öâ’¢76W'B—FVÒæW‡W&–Væ6UöÆWfVÂÒvVçG'’p  ¦FVbFW7Eö6ö×ç•öWFöÖF–öåö6÷•öFöW5öæ÷Eö7&VFUöWFöÖF–öå÷Fr‚“ ¢g&öÒVÆ—G•ö¦ö'2æ6Æ76–g’–×÷'B—5öWFöÖF–öà¢76W'Bæ÷B—5öWFöÖF–öâ†¦ö"‡F—FÆSÒt’FFææ÷FF÷"rÀ¢FW67&—F–öãÒt÷W"6ö×ç’&÷f–FW2WFöÖF–öâ6W'f–6W2âÆ&VÂ–ÖvW2âr’¢76W'B—5öWFöÖF–öâ†¦ö"‡F—FÆSÒt÷W&F–öç27V6–Æ—7BrÀ¢FW67&—F–öãÒt'V–ÆBv÷&¶fÆ÷w2W6–ærÖ¶Ræ6öÒæBã†ââr’  ¦FVbFW7E÷&WV—&VÖVçG5ö÷fW'&–FUö§Væ–÷%÷F—FÆUöæEö–væ÷&UöÖævW%ö–åöFW67&—F–öâ‚“ ¢g&öÒVÆ—G•ö¦ö'2æ6Æ76–g’–×÷'B6Æ76–g¢76W'B6Æ76–g’†¦ö"‡F—FÆSÒt§Væ–÷"WFöÖF–öâFWfVÆ÷W"rÀ¢FW67&—F–öãÒu&WV—&W2>(	3R–V'2öb&öfW76–öæÂW‡W&–Væ6Râr’’æW‡W&–Væ6UöÆWfVÂÓÒvÖ–Bp¢76W'B6Æ76–g’†¦ö"‡F—FÆSÒt§Væ–÷"WFöÖF–öâ76—7FçBrÀ¢FW67&—F–öãÒu&W÷'BFòÖævW"âæòW‡W&–Væ6R&WV—&VBâr’’æW‡W&–Væ6UöÆWfVÂÓÒvVçG'’p  ¦FVbFW7E÷FÆVçE÷ööÇ5ö&Uöæ÷E÷&öÖ÷FVEö5öÆ—fU÷f6æ6–W2‚“ ¢f÷"F—FÆR–â²t’G&–æW'2æWGv÷&²ÒVævÆ—6‚rÂtgWGW&R÷÷'GVæ—F–W3¢’FÆVçBööÂrÀ¢t–æ—F–F—fRÆ–6F–öâ†Òöb÷‚’uÓ ¢6VÆV7FVBÂ&V¦V7FVBÒ&ö6W72…¶¦ö"‡F—FÆS×F—FÆR•ÒÂ6WGF–æw2‚’¢76W'Bæ÷B6VÆV7FV@¢76W'B&V¦V7FVE³ÒçVÆ—G•÷66÷&RÓÒÓ   ¦FVbFW7E÷F—FÆUö6÷VçG'•÷&W7G&–7F–öåö÷fW'&–FW5÷v÷&ÆGv–FUöÆö6F–öâ‚“ ¢6VÆV7FVBÂòÒ&ö6W72…¶¦ö"‡F—FÆSÒt’WfÇVF÷"…Væ—FVB7FFW2’rÂÆö6F–öãÒu&VÖ÷FRÂv÷&ÆGv–FRr•ÒÀ¢6WGF–æw2†ÆÆ÷vVE÷&VÖ÷FU÷66÷W3Ög&÷¦Vç6WB‡²wW2wÒ’’¢76W'B6VÆV7FVE³Òç&VÖ÷FU÷66÷RÓÒwW2p¢76W'Br5v÷&ÆGv–FRræ÷B–â6VÆV7FVE³ÒçFVÆVw&Õ÷÷7@