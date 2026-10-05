import json

import pytest

from quality_jobs.config import Settings
from quality_jobs.models import Job
from quality_jobs.sources import collect, fetch_mercor


def mercor_response(monkeypatch, state):
    class Response:
        text = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(state) + '</script>'
        def raise_for_status(self):
            pass
    monkeypatch.setattr("quality_jobs.sources.requests.get", lambda *a, **kw: Response())


@pytest.mark.parametrize("state", [None, {}, {"props": None},
    {"props": {"pageProps": None}},
    {"props": {"pageProps": {"dehydratedState": None}}},
    {"props": {"pageProps": {"dehydratedState": {"queries": None}}}},
    {"props": {"pageProps": {"dehydratedState": {"queries": [None, {"state": None}, {"state": {"data": None}}]}}}},
])
def test_mercor_missing_data_is_a_controlled_source_failure(monkeypatch, state):
    mercor_response(monkeypatch, state)
    with pytest.raises(ValueError, match="Mercor public listings"):
        fetch_mercor(Settings.from_env())


def test_mercor_finds_listings_after_null_queries_and_keeps_referral(monkeypatch):
    mercor_response(monkeypatch, {"props": {"pageProps": {"dehydratedState": {"queries": [
        None, {"state": {"data": None}}, {"state": {"data": {"listings": [None,
            {"listingId": "123", "status": "active", "title": "AI Evaluator",
             "eligibleLocation": ["USA"], "rateMin": 20, "rateMax": 30}
        ]}}}
    ]}}}})
    monkeypatch.setenv("MERCOR_REFERRAL_URL", "https://t.mercor.com/H06sH")
    jobs = fetch_mercor(Settings.from_env())
    assert len(jobs) == 1
    assert jobs[0].effective_url == "https://t.mercor.com/H06sH"
    assert jobs[0].location == "United States"


@pytest.mark.parametrize("error", [ValueError("missing data"), AttributeError("null field"), KeyError("listings")])
def test_one_broken_source_does_not_block_other_sources(monkeypatch, error):
    expected = Job(source="Remotive", title="AI Engineer", company="Example", location="Worldwide", direct_url="https://example.com/job")
    def broken(settings):
        raise error
    monkeypatch.setattr("quality_jobs.sources.SOURCE_FETCHERS", {
        "mercor": broken, "remotive": lambda settings: [expected]})
    assert collect(Settings.from_env()) == [expected]
