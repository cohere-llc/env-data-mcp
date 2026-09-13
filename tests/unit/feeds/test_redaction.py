"""A credential in a request URL never reaches a log line (path segment or query value)."""

import logging

from env_data_mcp import feeds


def test_firms_path_credential_is_redacted(caplog):
    feeds.install_redaction()
    secret = "0123456789abcdef0123456789abcdef"
    with caplog.at_level(logging.INFO, logger="httpx"):
        logging.getLogger("httpx").info(
            "HTTP Request: GET https://firms.modaps.eosdis.nasa.gov/api/area/csv/%s"
            '/VIIRS_SNPP_NRT/-122,36,-118,39/1 "HTTP/1.1 200 OK"',
            secret,
        )
        logging.getLogger("httpx").info(
            "HTTP Request: GET https://api.example.gov/v2/?api_key=%s&x=1", secret
        )
    assert secret not in caplog.text
    assert "/api/area/csv/<redacted>/VIIRS_SNPP_NRT/" in caplog.text
    assert "api_key=<redacted>&x=1" in caplog.text


def test_install_is_idempotent():
    feeds.install_redaction()
    feeds.install_redaction()
    lg = logging.getLogger("httpx")
    assert sum(isinstance(f, feeds.RedactCredentials) for f in lg.filters) == 1
