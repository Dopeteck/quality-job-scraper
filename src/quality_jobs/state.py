from __future__ import annotations

import json
from pathlib import Path

from .models import Job


def load_seen(path: str) -> tuple[set[str], set[str]]:
    state_path = Path(path)
    if not state_path.exists():
        return set(), set()

    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set(), set()

    return set(data.get("urls", [])), set(data.get("fingerprints", []))


def save_seen(
    path: str,
    existing_urls: set[str],
    existing_fingerprints: set[str],
    jobs: list[Job],
) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    urls = existing_urls | {job.canonical_url for job in jobs if job.canonical_url}
    fingerprints = existing_fingerprints | {
        job.fingerprint for job in jobs if job.fingerprint
    }
    state_path.write_text(
        json.dumps(
            {"urls": sorted(urls), "fingerprints": sorted(fingerprints)},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
