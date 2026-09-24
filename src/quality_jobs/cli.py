from __future__ import annotations

import argparse
import json
import logging
import sys

import requests

from .config import Settings
from .pipeline import process
from .sheets import append_jobs, existing_keys, worksheet
from .site import send_jobs as send_site_jobs
from .sources import SOURCE_FETCHERS, collect
from .state import load_seen, save_seen
from .webhook import send_jobs


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Collect and score quality remote jobs")
    result.add_argument("--dry-run", action="store_true", help="Print accepted jobs; do not write")
    result.add_argument("--no-link-check", action="store_true", help="Skip application URL checks")
    result.add_argument(
        "--source",
        action="append",
        choices=sorted(SOURCE_FETCHERS),
        help="Run only this source; may be repeated",
    )
    result.add_argument("--json", action="store_true", help="Print accepted jobs as JSON")
    return result


def main() -> int:
    args = parser().parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = Settings.from_env()
    if args.no_link_check:
        object.__setattr__(settings, "link_check_enabled", False)

    existing_urls: set[str] = set()
    existing_fingerprints: set[str] = set()
    ws = None
    if not args.dry_run:
        if not settings.make_webhook_url and not settings.google_sheet_id:
            print(
                "MAKE_WEBHOOK_URL or GOOGLE_SHEET_ID is required unless --dry-run is used",
                file=sys.stderr,
            )
            return 2
        if not settings.make_webhook_url:
            ws = worksheet(settings)
            existing_urls, existing_fingerprints = existing_keys(ws)
        else:
            existing_urls, existing_fingerprints = load_seen(settings.state_path)

    raw_jobs = collect(settings, set(args.source or []))
    accepted_jobs, rejected_jobs = process(
        raw_jobs, settings, existing_urls, existing_fingerprints
    )

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "source": job.source,
                        "title": job.title,
                        "company": job.company,
                        "url": job.effective_url,
                        "quality_score": job.quality_score,
                        "telegram_post": job.telegram_post,
                    }
                    for job in accepted_jobs
                ],
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        for job in accepted_jobs:
            print(
                f"ACCEPT {job.quality_score:>2} | {job.source:<16} | "
                f"{job.title} — {job.company}"
            )
        print(f"Summary: accepted={len(accepted_jobs)} rejected_or_held={len(rejected_jobs)}")

    if ws is not None:
        append_jobs(ws, accepted_jobs)
        print(f"Added {len(accepted_jobs)} rows to {settings.google_worksheet}")
    elif not args.dry_run and settings.make_webhook_url:
        # The Make webhook is the primary publishing path because it feeds the
        # Sheet and Telegram queue. A secondary website outage must never block
        # that delivery or cause the full batch to be retried.
        send_jobs(settings, accepted_jobs)
        try:
            send_site_jobs(settings, accepted_jobs)
        except (requests.RequestException, ValueError) as exc:
            logging.warning("site_ingest_failed=%s", exc)
        save_seen(
            settings.state_path,
            existing_urls,
            existing_fingerprints,
            accepted_jobs,
        )
        print(f"Sent {len(accepted_jobs)} rows to Make")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
