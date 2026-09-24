from __future__ import annotations

import requests

from .config import Settings
from .models import Job
from .sheets import HEADERS, row


def payload(job: Job) -> dict[str, object]:
    """Return the flat, header-compatible object expected by the Make webhook."""
    return dict(zip(HEADERS, row(job), strict=True))


def send_jobs(settings: Settings, jobs: list[Job]) -> None:
    for job in jobs:
        response = requests.post(
            settings.make_webhook_url,
            json=payload(job),
            timeout=settings.request_timeout_seconds,
            headers={"User-Agent": settings.user_agent},
        )
        response.raise_for_status()
