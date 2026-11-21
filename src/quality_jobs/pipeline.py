from __future__ import annotations

import logging
import math
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from .classify import classify
from .config import Settings
from .formatting import build_telegram_post
from .linkcheck import check_link
from .models import Job
from .scoring import accepted, score_job
from .sources import verify_candidate_details
from .text import canonicalize_url, fingerprint

LOGGER = logging.getLogger(__name__)


def _prepare(job: Job, settings: Settings) -> Job:
    job.canonical_url = canonicalize_url(job.direct_url)
    job.fingerprint = fingerprint(job.title, job.company)
    classify(job)
    score_job(job, settings)
    return job


def _worth_checking(job: Job, settings: Settings) -> bool:
    return (
        job.quality_score > -100
        and (not settings.require_known_location or job.remote_scope != "unknown")
        and job.quality_score >= settings.min_quality_score - 1
    )


def enrich(job: Job, settings: Settings) -> Job:
    _prepare(job, settings)
    worth_checking = (
        settings.link_check_enabled and _worth_checking(job, settings)
    )
    if worth_checking:
        job.link_status = check_link(
            job.direct_url,
            timeout=settings.request_timeout_seconds,
            user_agent=settings.user_agent,
        )
    score_job(job, settings)
    job.telegram_post = build_telegram_post(job)
    return job


def _verify_and_check(job: Job, settings: Settings) -> str:
    details_verified = verify_candidate_details(job, settings)
    _prepare(job, settings)
    if not details_verified:
        job.remote_scope = "unknown"
        job.africa_eligible = False
        score_job(job, settings)
    if not _worth_checking(job, settings):
        return "unchecked"
    return check_link(
        job.direct_url,
        timeout=settings.request_timeout_seconds,
        user_agent=settings.user_agent,
    )


def _balanced_limit(jobs: list[Job], settings: Settings) -> list[Job]:
    selected: list[Job] = []
    source_counts: Counter[str] = Counter()
    referral_limit = (
        max(1, math.floor(settings.max_per_run * settings.max_referral_share))
        if settings.max_referral_share > 0
        else 0
    )
    referral_count = 0
    ranked = sorted(jobs, key=lambda item: item.quality_score, reverse=True)

    def add_from(pool: list[Job], limit: int) -> None:
        nonlocal referral_count
        added = 0
        for job in pool:
            if len(selected) >= settings.max_per_run or added >= limit:
                break
            if job in selected or source_counts[job.source] >= settings.max_per_source:
                continue
            if job.is_referral and referral_count >= referral_limit:
                continue
            selected.append(job)
            source_counts[job.source] += 1
            referral_count += int(job.is_referral)
            added += 1

    # Give each role category a fair first look before filling remaining slots.
    # This prevents one large AI/entry-level source from monopolising a small batch.
    categories = sorted(
        {job.category for job in ranked},
        key=lambda category: max(
            item.quality_score for item in ranked if item.category == category
        ),
        reverse=True,
    )
    for category in categories:
        if len(selected) >= settings.max_per_run:
            break
        add_from([job for job in ranked if job.category == category], 1)
    add_from(ranked, settings.max_per_run)
    return sorted(selected, key=lambda item: item.quality_score, reverse=True)


def _rejection_category(job: Job, settings: Settings) -> str:
    """Map per-job reasons to stable labels safe for aggregate logs."""
    detail = " ".join(job.quality_reasons).lower()
    categories = (
        ("duplicate", "duplicate"),
        ("missing_application_url", "missing url"),
        ("outside_target_region", "outside target region"),
        ("broken_application_link", "broken application link"),
        ("expired_or_stale", "days old"),
        ("unsupported_language", "non-english listing"),
        ("promotional_or_unpaid", "course, unpaid, or promotional"),
        ("non_specific_vacancy", "talent pool or speculative application"),
        ("generic_or_missing_title", "generic or missing title"),
        ("suspicious_earnings_claim", "suspicious earnings claim"),
    )
    for category, marker in categories:
        if marker in detail:
            return category
    if settings.require_known_location and job.remote_scope == "unknown":
        return "unknown_location"
    if job.quality_score < settings.min_quality_score:
        return "below_quality_threshold"
    if settings.link_check_enabled and job.link_status == "unchecked":
        return "application_link_unverified"
    return "rejected_other"


def _hold_category(job: Job, selected: list[Job], settings: Settings) -> str:
    """Report the first deterministic selection constraint that held a job."""
    if len(selected) >= settings.max_per_run:
        return "per_run_limit"

    source_count = sum(item.source == job.source for item in selected)
    if source_count >= settings.max_per_source:
        return "source_limit"

    referral_limit = (
        max(1, math.floor(settings.max_per_run * settings.max_referral_share))
        if settings.max_referral_share > 0
        else 0
    )
    referral_count = sum(item.is_referral for item in selected)
    if job.is_referral and referral_count >= referral_limit:
        return "referral_limit"
    return "selection_balance_limit"


def process(
    jobs: list[Job],
    settings: Settings,
    existing_urls: set[str] | None = None,
    existing_fingerprints: set[str] | None = None,
) -> tuple[list[Job], list[Job]]:
    seen_urls = set(existing_urls or set())
    seen_fingerprints = set(existing_fingerprints or set())
    prepared = [_prepare(job, settings) for job in jobs]
    if settings.link_check_enabled:
        candidate_pool = sorted(
            (job for job in prepared if _worth_checking(job, settings)),
            key=lambda item: item.quality_score,
            reverse=True,
        )
        # Interleave categories by their best score. The verification budget is
        # deliberately independent of the number of posts allowed in this run.
        categories = sorted(
            {job.category for job in candidate_pool},
            key=lambda category: max(
                item.quality_score for item in candidate_pool if item.category == category
            ),
            reverse=True,
        )
        category_pools = {
            category: [job for job in candidate_pool if job.category == category]
            for category in categories
        }
        priority_pool: list[Job] = []
        while any(category_pools.values()):
            for category in categories:
                if category_pools[category]:
                    priority_pool.append(category_pools[category].pop(0))
        priority_pool.extend(candidate_pool)
        candidates: list[Job] = []
        candidate_source_counts: Counter[str] = Counter()
        candidate_urls: set[str] = set()
        candidate_fingerprints: set[str] = set()
        for job in priority_pool:
            if len(candidates) >= settings.max_link_check_candidates:
                break
            if (job.canonical_url in seen_urls or job.fingerprint in seen_fingerprints
                    or job.canonical_url in candidate_urls
                    or job.fingerprint in candidate_fingerprints):
                continue
            if candidate_source_counts[job.source] >= settings.max_link_check_per_source:
                continue
            candidates.append(job)
            candidate_urls.add(job.canonical_url)
            candidate_fingerprints.add(job.fingerprint)
            candidate_source_counts[job.source] += 1
        LOGGER.info(
            "link_check_candidates=%d candidate_limit=%d per_source_limit=%d",
            len(candidates), settings.max_link_check_candidates,
            settings.max_link_check_per_source,
        )
        workers = min(12, len(candidates))
        if workers:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(_verify_and_check, job, settings): job
                    for job in candidates
                }
                for future in as_completed(futures):
                    futures[future].link_status = future.result()

    for job in prepared:
        score_job(job, settings)
        job.telegram_post = build_telegram_post(job)

    accepted_jobs: list[Job] = []
    rejected_jobs: list[Job] = []

    for job in prepared:
        if not job.canonical_url:
            job.quality_score = -100
            job.quality_reasons = ["rejected: missing URL"]
        if job.canonical_url in seen_urls or job.fingerprint in seen_fingerprints:
            job.quality_score = -100
            job.quality_reasons = ["rejected: duplicate"]
        if accepted(job, settings):
            accepted_jobs.append(job)
            seen_urls.add(job.canonical_url)
            seen_fingerprints.add(job.fingerprint)
        else:
            rejected_jobs.append(job)

    selected = _balanced_limit(accepted_jobs, settings)
    overflow = [job for job in accepted_jobs if job not in selected]
    for job in overflow:
        category = _hold_category(job, selected, settings)
        job.quality_reasons.append(f"held: {category}")
    rejected_jobs.extend(overflow)
    LOGGER.info("accepted=%d rejected_or_held=%d", len(selected), len(rejected_jobs))
    if selected:
        LOGGER.info("selected_by_category=%s", dict(Counter(job.category for job in selected)))
        LOGGER.info("selected_by_source=%s", dict(Counter(job.source for job in selected)))
    reasons = Counter()
    for job in rejected_jobs:
        hold_reasons = [reason for reason in job.quality_reasons if reason.startswith("held:")]
        if hold_reasons:
            # Categories are internal constants generated above, never listing text.
            reasons[hold_reasons[-1].split(":", 1)[1].strip()] += 1
        else:
            reasons[_rejection_category(job, settings)] += 1
    if reasons:
        LOGGER.info("rejected_or_held_by_reason=%s", dict(reasons))
    return selected, rejected_jobs

