from __future__ import annotations

import re
from datetime import datetime, timezone

from .models import Job
from .text import safe_html, shorten


HASHTAGS = {
    "ai": ["#AIJobs", "#AITraining", "#RemoteJobs"],
    "web3": ["#Web3Jobs", "#CryptoJobs", "#RemoteJobs"],
    "tech": ["#TechJobs", "#RemoteJobs"],
}


def _age_label(job: Job) -> str:
    if not job.published_at:
        return "Recently listed"
    published = job.published_at
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    days = max(0, int((datetime.now(timezone.utc) - published).total_seconds() // 86400))
    if days == 0:
        return "Posted today"
    if days == 1:
        return "Posted yesterday"
    return f"Posted {days} days ago"


def _scope_label(job: Job) -> str:
    labels = {
        "worldwide": "Worldwide remote",
        "africa": "Africa-friendly remote",
        "latam": "LATAM remote",
        "emea": "EMEA remote",
        "europe": "Europe/EMEA remote",
        "us_canada": "US/Canada remote",
        "us_ca_uk_eu": "US/Canada/UK/EU",
        "asia": "Asia/APAC remote",
        "middle_east": "Middle East/MENA remote",
        "unknown": job.location or "Location eligibility not specified",
    }
    return labels.get(job.remote_scope, job.location or job.remote_scope)


def _clean_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    return title.upper()


def build_telegram_post(job: Job) -> str:
    badges: list[str] = []
    if job.africa_eligible:
        badges.append("🌍 AFRICA ELIGIBLE")
    if job.experience_level == "entry":
        badges.append("🌱 ENTRY LEVEL")
    if job.category == "ai":
        badges.append("🤖 AI OPPORTUNITY")
    if job.salary:
        badges.append("💰 SALARY LISTED")

    lines = [f"<b>{safe_html(_clean_title(job.title))}</b>"]
    if badges:
        lines.append(" • ".join(badges))
    lines.extend(
        [
            "",
            f"🏢 <b>{safe_html(job.company)}</b>",
            f"📍 {safe_html(_scope_label(job))}",
        ]
    )
    if job.salary:
        lines.append(f"💵 {safe_html(job.salary)}")
    lines.append(f"🗓 {_age_label(job)}")
    if job.description:
        lines.extend(["", safe_html(shorten(job.description, 280))])
    lines.extend(["", f"🔗 <a href=\"{safe_html(job.effective_url)}\"><b>Apply here</b></a>"])

    if job.is_referral:
        lines.append(
            "<i>Referral disclosure: we may earn if you are accepted and begin paid work.</i>"
        )
        if job.direct_url != job.referral_url:
            lines.append(
                f"<a href=\"{safe_html(job.direct_url)}\">View the original listing</a>"
            )
    lines.extend(
        [
            "",
            "↗️ Forward this to someone looking for work.",
            " ".join(HASHTAGS.get(job.category, HASHTAGS["tech"])),
        ]
    )
    return "\n".join(lines)
