"""Unit tests for env_data_mcp.feeds (TTL cache, quota governor, feed meta) and the EventRecord
schema.

All tests are offline.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from env_data_mcp import feeds
from env_data_mcp.models import EventRecord, EventResponse, ResponseMeta

_LIC = {"license": "Public domain", "license_url": "https://example.org", "citation": "x"}


@pytest.fixture(autouse=True)
def _fresh_state():
    feeds.cache().clear()
    feeds.reset_governors()
    yield
    feeds.cache().clear()
    feeds.reset_governors()


# ---------------------------------------------------------------------------
# TtlCache
# ---------------------------------------------------------------------------


def test_ttl_cache_returns_within_ttl_and_expires_after(monkeypatch):
    c = feeds.TtlCache()
    now = [1000.0]
    monkeypatch.setattr(feeds.time, "monotonic", lambda: now[0])
    fetched = c.set("k", {"a": 1}, ttl_s=60)
    assert fetched.endswith("Z")
    hit = c.get("k")
    assert hit is not None and hit[0] == {"a": 1} and hit[1] == fetched
    now[0] += 59.9
    assert c.get("k") is not None
    now[0] += 0.2
    assert c.get("k") is None  # expired: the next call refetches


def test_cache_key_is_order_independent():
    assert feeds.cache_key("s", {"a": 1, "b": 2}) == feeds.cache_key("s", {"b": 2, "a": 1})
    assert feeds.cache_key("s", {"a": 1}) != feeds.cache_key("t", {"a": 1})


# ---------------------------------------------------------------------------
# QuotaGovernor
# ---------------------------------------------------------------------------


def test_quota_governor_counts_and_refuses_at_the_limit(monkeypatch):
    now = [5000.0]
    monkeypatch.setattr(feeds.time, "monotonic", lambda: now[0])
    g = feeds.QuotaGovernor(limit=3, window_s=600)
    for i in range(3):
        ok, q = g.try_acquire()
        assert ok and q["used"] == i + 1 and q["remaining"] == 3 - (i + 1)
    ok, q = g.try_acquire()  # the 4th call in the window is refused
    assert not ok and q["used"] == 3 and q["remaining"] == 0 and q["resets_in_s"] == 600.0
    now[0] += 601
    ok, q = g.try_acquire()  # the window slid: allowed again
    assert ok and q["used"] == 1


def test_governor_registry_keeps_one_per_source_and_retunes_on_new_limits():
    a = feeds.governor("x", 10, 60)
    assert feeds.governor("x", 10, 60) is a
    b = feeds.governor("x", 1000, 3600)  # a key tier raised the limit → a fresh governor
    assert b is not a and b.limit == 1000


def test_quota_refused_response_shape():
    g = feeds.QuotaGovernor(limit=1, window_s=60)
    g.try_acquire()
    ok, q = g.try_acquire()
    assert not ok
    r = feeds.quota_refused("s", {"a": 1}, _LIC, q, ttl_s=30, auth_required=True)
    assert r["data"] == [] and r["_meta"]["success"] is False and r["_meta"]["quota"]["limit"] == 1
    assert "resets in" in r["_meta"]["error"]
    ResponseMeta.model_validate(r["_meta"])


# ---------------------------------------------------------------------------
# feed_meta / key_missing / nc gate
# ---------------------------------------------------------------------------


def test_feed_meta_carries_ttl_fetched_at_cached_and_quota():
    m = feeds.feed_meta(
        "s",
        {"q": 1},
        3,
        0.01,
        _LIC,
        ttl_s=300,
        quota={"limit": 5, "window_s": 60, "used": 1, "remaining": 4, "resets_in_s": 59},
    )
    ResponseMeta.model_validate(m)
    assert m["ttl_s"] == 300.0 and m["cached"] is False and m["fetched_at"].endswith("Z")
    assert (
        m["quota"]["remaining"] == 4 and m["total_records_returned"] == 3 and m["success"] is True
    )
    m2 = feeds.feed_meta("s", {}, 0, 0.0, _LIC, ttl_s=1)
    assert "quota" not in m2


def test_key_missing_is_a_response_not_an_exception(monkeypatch):
    monkeypatch.delenv("SOME_KEY", raising=False)
    assert feeds.read_key("SOME_KEY") == ""
    r = feeds.key_missing("s", "SOME_KEY", "https://example.org/signup", {"a": 1}, _LIC, ttl_s=60)
    assert (
        r["data"] == []
        and r["_meta"]["auth_required"] is True
        and r["_meta"]["auth_present"] is False
    )
    assert "SOME_KEY" in r["_meta"]["error"] and "https://example.org/signup" in r["_meta"]["error"]
    monkeypatch.setenv("SOME_KEY", "  abc \n")
    assert feeds.read_key("SOME_KEY") == "abc"


def test_nc_gate_reads_env(monkeypatch):
    monkeypatch.delenv("ENV_DATA_ALLOW_NC", raising=False)
    assert feeds.nc_allowed() is False
    monkeypatch.setenv("ENV_DATA_ALLOW_NC", "1")
    assert feeds.nc_allowed() is True


def test_iso_or_none_converts_epoch_millis():
    assert feeds.iso_or_none(1789212739200) == "2026-09-12T11:32:19Z"
    assert (
        feeds.iso_or_none(None) is None
        and feeds.iso_or_none("2026-09-12T00:00:00Z") == "2026-09-12T00:00:00Z"
    )


# ---------------------------------------------------------------------------
# EventRecord
# ---------------------------------------------------------------------------


def test_event_record_schema_and_response():
    rec = EventRecord(
        id="a",
        source="s",
        kind="fire",
        title="t",
        lat=1.0,
        lon=2.0,
        t_start="2026-09-12T00:00:00Z",
        url="u",
        licence="l",
    )
    assert rec.geometry is None and rec.t_end is None and rec.magnitude is None
    with pytest.raises(ValidationError):
        EventRecord(id="a", source="s", kind="fire", title="t", lat=91.0, lon=2.0, t_start="x")
    resp = EventResponse.model_validate(
        {"data": [rec.model_dump()], "_meta": feeds.feed_meta("s", {}, 1, 0.0, _LIC, ttl_s=1)}
    )
    assert resp.data[0].kind == "fire" and resp.meta.ttl_s == 1.0  # type: ignore[attr-defined]
