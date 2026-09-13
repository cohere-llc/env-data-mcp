"""ARM Live: the credential rides in the query string (no header form) and is redacted from every
log line; no credential → auth flags, never an exception; the files parse; a rejected credential
is a response."""

from __future__ import annotations

import logging

from env_data_mcp import feeds
from env_data_mcp.models import ToolResponse
from env_data_mcp.sources.arm_live._constants import ARMLIVE_BASE_URL, KEY_NAME
from env_data_mcp.sources.arm_live.tools import arm_live_files

SECRET = "aparkin:0123456789abcdefABCDEF"


def test_no_credential_is_a_response_with_auth_flags(monkeypatch):
    monkeypatch.delenv(KEY_NAME, raising=False)
    feeds.cache().clear()
    r = arm_live_files(datastream="sgpmetE13.b1", start="2024-01-01", end="2024-01-02")
    assert r["_meta"]["auth_required"] is True and r["_meta"]["auth_present"] is False
    assert r["data"] == []


def test_files_listed_and_the_credential_never_logged(monkeypatch, httpx_mock, caplog):
    monkeypatch.setenv(KEY_NAME, SECRET)
    feeds.cache().clear()
    httpx_mock.add_response(
        url=(
            f"{ARMLIVE_BASE_URL}/query?user={SECRET}&ds=sgpmetE13.b1"
            "&start=2024-01-01&end=2024-01-02&wt=json"
        ),
        json={
            "status": "success",
            "files": ["sgpmetE13.b1.20240101.000000.cdf", "sgpmetE13.b1.20240102.000000.cdf"],
        },
    )
    with caplog.at_level(logging.DEBUG):
        r = arm_live_files(datastream="sgpmetE13.b1", start="2024-01-01", end="2024-01-02")
    ToolResponse.model_validate(r)
    assert r["_meta"]["success"] is True and len(r["data"]) == 2
    assert r["data"][0]["date"] == "2024-01-01"
    assert r["data"][0]["download"].startswith(ARMLIVE_BASE_URL)
    assert SECRET not in caplog.text and SECRET not in str(r)
    assert "user=<redacted>" in caplog.text or "HTTP Request" not in caplog.text


def test_rejected_credential_is_a_response(monkeypatch, httpx_mock):
    monkeypatch.setenv(KEY_NAME, SECRET)
    feeds.cache().clear()
    httpx_mock.add_response(json={"status": "failed", "reason": "authentication failed"})
    r = arm_live_files(datastream="sgpmetE13.b1", start="2024-01-01", end="2024-01-01")
    assert r["_meta"]["success"] is False and "rejected" in r["_meta"]["error"]
    assert r["data"] == []
