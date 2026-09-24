from __future__ import annotations

import json
import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    google_sheet_id: str
    google_worksheet: str
    google_service_account_json: str
    make_webhook_url: str
    mercor_referral_url: str
    outlier_referral_url: str
    min_quality_score: int
    max_job_age_days: int
    max_per_run: int
    max_per_source: int
    max_referral_share: float
    entry_priority_share: float
    ai_priority_share: float
    link_check_enabled: bool
    require_known_location: bool
    request_timeout_seconds: int
    allowed_remote_scopes: frozenset[str]
    user_agent: str

    @classmethod
    def from_env(cls) -> "Settings":
        scopes = frozenset(
            part.strip().lower()
            for part in os.getenv(
                "ALLOWED_REMOTE_SCOPES",
                "worldwide,africa,emea,europe,latam,us_canada,us_ca_uk_eu,asia,middle_east",
            ).split(",")
            if part.strip()
        )
        return cls(
            google_sheet_id=os.getenv("GOOGLE_SHEET_ID", "").strip(),
            google_worksheet=os.getenv("GOOGLE_WORKSHEET", "QualityJobs").strip(),
            google_service_account_json=os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip(),
            make_webhook_url=os.getenv("MAKE_WEBHOOK_URL", "").strip(),
            mercor_referral_url=os.getenv("MERCOR_REFERRAL_URL", "").strip(),
            outlier_referral_url=os.getenv("OUTLIER_REFERRAL_URL", "").strip(),
            min_quality_score=int(os.getenv("MIN_QUALITY_SCORE", "8")),
            max_job_age_days=int(os.getenv("MAX_JOB_AGE_DAYS", "10")),
            max_per_run=int(os.getenv("MAX_PER_RUN", "5")),
            max_per_source=int(os.getenv("MAX_PER_SOURCE", "2")),
            max_referral_share=float(os.getenv("MAX_REFERRAL_SHARE", "0.20")),
            entry_priority_share=float(os.getenv("ENTRY_PRIORITY_SHARE", "0.40")),
            ai_priority_share=float(os.getenv("AI_PRIORITY_SHARE", "0.40")),
            link_check_enabled=_bool("LINK_CHECK_ENABLED", True),
            require_known_location=_bool("REQUIRE_KNOWN_LOCATION", True),
            request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "10")),
            allowed_remote_scopes=scopes,
            user_agent=os.getenv("USER_AGENT", "Web3TechJobsHub/1.0").strip(),
        )

    def service_account_info(self) -> dict:
        if not self.google_service_account_json:
            return {}
        try:
            return json.loads(self.google_service_account_json)
        except json.JSONDecodeError as exc:
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON") from exc
