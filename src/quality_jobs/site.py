from __future__ import annotations

from datetime import datetime

import requests

from .config import Settings
from .models import Job


def _isoformat(value: datetime) -> str:
    """Return an RFC 3339 timestamp that is accepted by strict JSON APIs."""
    return value.isoformat().replace("+00:00", "Z")


def payload(job: Job) -> dict[str, object]:
    """Return the normalized object accepted by the public job hub."""
    return {
        "fingerprint": job.fingerprint,
        "source": job.source,
        "source_job_id": job.source_job_id,
        "title": job.title,
        "company": job.company,
        "location": job.location or "Remote",
        "summary": job.description,
        "category": job.category,
        "opportunity_type": job.opportunity_type,
        "experience_level": job.experience_level,
        "salary": job.salary,
        "remote_scope": job.remote_scope,
        "africa_eligible": job.africa_eligible,
        "search_keywords": job.search_keywords,
        "quality_score": job.quality_score,
        "quality_reasons": "; ".join(job.quality_reasons),
        "apply_url": job.effective_url,
        "direct_url": job.direct_url,
        "published_at": _isoformat(job.published_at) if job.published_at else None,
        "scraped_at": _isoformat(job.scraped_at),
    }


def send_jobs(settings: Settings, jobs: list[Job]) -> None:
    """Upsert jobs into the hub before handing them to the publishing queue."""
    if not settings.site_ingest_url:
        return
    if not settings.site_ingest_token:
        raise ValueError("SITE_INGEST_TOKEN is required when SITE_INGEST_URL is set")

    headers = {
        "Authorization": f"Bearer {settings.site_ingest_token}",
        "User-Agent": settings.user_agent,
    }
    for job in jobs:
        response = requests.post(
            settings.site_ingest_url,
            json=payload(job),
            timeout=settings.request_timeout_seconds,
            headers=headers,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = response.text.strip()[:500]
            message = f"site ingest rejected {job.source_job_id or job.fingerprint}: {exc}"
            if detail:
                message = f"{message}; response={detail}"
            raise requests.HTTPError(
                message,
                response=response,
                request=response.request,
            ) from exc
