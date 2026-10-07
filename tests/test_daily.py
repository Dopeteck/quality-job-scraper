import json
from datetime import datetime, timezone

import pytest
import requests

from quality_jobs import cli
from quality_jobs.daily import day_key, published_today, record_published
from quality_jobs.state import load_seen
from quality_jobs.text import canonicalize_url, fingerprint
from quality_jobs.models import Job


def test_quota_resets_at_lagos_midnight(tmp_path):
    path = str(tmp_path / 'seen.json')
    before = datetime(2026, 10, 7, 22, 59, tzinfo=timezone.utc)
    after = datetime(2026, 10, 7, 23, 0, tzinfo=timezone.utc)
    record_published(path, 2, before)
    assert published_today(path, before) == 2
    assert day_key(after) == '2026-10-08'
    assert published_today(path, after) == 0


def test_corrupt_quota_fails_closed(tmp_path):
    (tmp_path / 'daily.json').write_text('{broken')
    with pytest.raises(json.JSONDecodeError):
        published_today(str(tmp_path / 'seen.json'))


def test_backup_skips_collection_after_daily_limit(monkeypatch, tmp_path, capsys):
    path = str(tmp_path / 'seen.json')
    record_published(path, 2)
    monkeypatch.setenv('STATE_PATH', path)
    monkeypatch.setattr('sys.argv', ['quality-jobs', '--daily-limit', '2'])
    monkeypatch.setattr(cli, 'collect', lambda *args: pytest.fail('quota must stop network calls'))
    assert cli.main() == 0
    assert 'Daily quota reached' in capsys.readouterr().out


def test_partial_delivery_preserves_seen_and_remaining_quota(monkeypatch, tmp_path):
    path = str(tmp_path / 'seen.json')
    monkeypatch.setenv('STATE_PATH', path)
    monkeypatch.setenv('MAKE_WEBHOOK_URL', 'https://example.com/webhook')
    monkeypatch.setattr('sys.argv', ['quality-jobs', '--daily-limit', '2'])
    jobs = [Job(source='Test', title=f'Junior AI Evaluator {i}', company='Example',
                location='Worldwide', direct_url=f'https://example.com/jobs/{i}') for i in range(2)]
    for job in jobs:
        job.canonical_url = canonicalize_url(job.direct_url)
        job.fingerprint = fingerprint(job.title, job.company)
    monkeypatch.setattr(cli, 'collect', lambda *args: jobs)
    monkeypatch.setattr(cli, 'process', lambda *args: (jobs, []))
    sent = []
    def deliver(settings, batch):
        if sent:
            raise requests.ConnectionError('second row failed')
        sent.extend(batch)
    monkeypatch.setattr(cli, 'send_jobs', deliver)
    with pytest.raises(requests.ConnectionError):
        cli.main()
    assert published_today(path) == 1
    urls, fingerprints = load_seen(path)
    assert jobs[0].canonical_url in urls and jobs[1].canonical_url not in urls
    assert jobs[0].fingerprint in fingerprints


def test_remaining_quota_reduces_next_batch(monkeypatch, tmp_path):
    path = str(tmp_path / 'seen.json')
    record_published(path, 1)
    monkeypatch.setenv('STATE_PATH', path)
    monkeypatch.setenv('MAKE_WEBHOOK_URL', 'https://example.com/webhook')
    monkeypatch.setattr('sys.argv', ['quality-jobs', '--daily-limit', '2'])
    monkeypatch.setattr(cli, 'collect', lambda *args: [])
    limits = []
    def process(jobs, settings, *args):
        limits.append(settings.max_per_run)
        return [], []
    monkeypatch.setattr(cli, 'process', process)
    monkeypatch.setattr(cli, 'send_site_jobs', lambda *args: None)
    assert cli.main() == 0
    assert limits == [1]
    assert published_today(path) == 1


def test_preview_does_not_change_quota(monkeypatch, tmp_path):
    path = str(tmp_path / 'seen.json')
    record_published(path, 2)
    monkeypatch.setenv('STATE_PATH', path)
    monkeypatch.setattr('sys.argv', ['quality-jobs', '--dry-run', '--daily-limit', '2'])
    monkeypatch.setattr(cli, 'collect', lambda *args: [])
    assert cli.main() == 0
    assert published_today(path) == 2
