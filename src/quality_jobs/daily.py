"""Persist a Lagos-day quota so delayed and backup runs do not overpost."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def day_key(now: datetime | None = None) -> str:
    return (now or datetime.now(ZoneInfo("Africa/Lagos"))).astimezone(
        ZoneInfo("Africa/Lagos")
    ).date().isoformat()


def quota_path(state_path: str) -> Path:
    return Path(state_path).with_name("daily.json")


def published_today(state_path: str, now: datetime | None = None) -> int:
    path = quota_path(state_path)
    if not path.exists():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("day") != day_key(now):
        return 0
    count = data.get("published", 0)
    if not isinstance(count, int) or count < 0:
        raise ValueError("Invalid daily publication count")
    return count


def record_published(state_path: str, count: int, now: datetime | None = None) -> None:
    path = quota_path(state_path)
    total = published_today(state_path, now) + count
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"day": day_key(now), "published": total}) + "\n",
                    encoding="utf-8")
