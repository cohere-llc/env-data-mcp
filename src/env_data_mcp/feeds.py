"""Shared machinery for the ``feeds`` family (live events) and the point accessors.

Three things every feed shares, kept in one place so no source re-implements them:

* :class:`TtlCache` — an in-process cache keyed by the exact query, honouring each source's TTL.
  A second call inside the TTL returns the cached result with ``_meta.cached = True`` and the
  original ``fetched_at``.
* :class:`QuotaGovernor` — a sliding-window counter per source (``limit`` calls per ``window_s``).
  A keyed source refuses at the limit *before* contacting the host, returning a normal
  ``{data: [], _meta}`` with ``_meta.quota`` filled in and ``_meta.error`` saying when it resets —
  never an exception.
* :func:`feed_meta` — :func:`~env_data_mcp.helpers.build_meta` plus the feed extras: ``ttl_s``,
  ``fetched_at``, ``cached`` and (for keyed or rate-limited sources)
  ``quota = {limit, window_s, used, remaining, resets_in_s}``.

Keys are read from the environment inside the tool that needs them and never echoed:
``query_params`` carries the *name* of the variable, never its value, and no URL containing a key
is ever placed in a response.
"""

from __future__ import annotations

import collections
import datetime
import os
import threading
import time
from collections.abc import Mapping
from typing import Any

from env_data_mcp.helpers import build_meta

# ---------------------------------------------------------------------------
# TTL cache
# ---------------------------------------------------------------------------


class TtlCache:
    """A tiny in-process TTL cache: ``get`` → ``(value, fetched_at)`` or ``None``; ``set(key, value,
    ttl_s)``."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[float, str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> tuple[Any, str] | None:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            expires_at, fetched_at, value = item
            if time.monotonic() >= expires_at:
                del self._items[key]
                return None
            return value, fetched_at

    def set(self, key: str, value: Any, ttl_s: float) -> str:
        fetched_at = utc_now_iso()
        with self._lock:
            self._items[key] = (time.monotonic() + ttl_s, fetched_at, value)
        return fetched_at

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


_CACHE = TtlCache()


def cache() -> TtlCache:
    """The process-wide cache shared by every feed."""
    return _CACHE


def cache_key(source: str, params: Mapping[str, Any]) -> str:
    """A stable key from the resolved query parameters (order-independent)."""
    return source + "|" + "&".join(f"{k}={params[k]!r}" for k in sorted(params))


# ---------------------------------------------------------------------------
# Quota governor (sliding window)
# ---------------------------------------------------------------------------


class QuotaGovernor:
    """``limit`` calls per ``window_s`` seconds, per source.  ``try_acquire`` records a call and
    returns
    ``(allowed, quota_dict)``; at the limit it refuses without recording."""

    def __init__(self, limit: int, window_s: float) -> None:
        self.limit = int(limit)
        self.window_s = float(window_s)
        self._calls: collections.deque[float] = collections.deque()
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        while self._calls and now - self._calls[0] >= self.window_s:
            self._calls.popleft()

    def _snapshot_locked(self, now: float) -> dict[str, Any]:
        """The quota dict at ``now``; the caller holds ``_lock`` (numbers match its decision)."""
        self._prune(now)
        used = len(self._calls)
        resets_in = (self._calls[0] + self.window_s - now) if self._calls else 0.0
        return {
            "limit": self.limit,
            "window_s": self.window_s,
            "used": used,
            "remaining": max(0, self.limit - used),
            "resets_in_s": round(max(0.0, resets_in), 1),
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot_locked(time.monotonic())

    def try_acquire(self) -> tuple[bool, dict[str, Any]]:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            if len(self._calls) >= self.limit:
                allowed = False
            else:
                self._calls.append(now)
                allowed = True
            return allowed, self._snapshot_locked(now)

    def reset(self) -> None:
        with self._lock:
            self._calls.clear()


_GOVERNORS: dict[str, QuotaGovernor] = {}
_GOV_LOCK = threading.Lock()


def governor(source: str, limit: int, window_s: float) -> QuotaGovernor:
    """The per-source governor (created on first use; ``limit``/``window_s`` may be raised by a key
    tier)."""
    with _GOV_LOCK:
        g = _GOVERNORS.get(source)
        if g is None or g.limit != limit or g.window_s != window_s:
            g = QuotaGovernor(limit, window_s)
            _GOVERNORS[source] = g
        return g


def reset_governors() -> None:
    """Tests only."""
    with _GOV_LOCK:
        for g in _GOVERNORS.values():
            g.reset()
        _GOVERNORS.clear()


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------


def read_key(name: str) -> str:
    """The credential named ``name`` from the environment, stripped; empty when unset.  Never log
    the value."""
    return os.environ.get(name, "").strip()


def nc_allowed() -> bool:
    """Non-commercial-only sources (Open-Meteo's free tier) are served only when the operator sets
    ``ENV_DATA_ALLOW_NC=1`` — the attestation that this deployment's use is non-commercial."""
    return os.environ.get("ENV_DATA_ALLOW_NC", "").strip() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------


def utc_now_iso() -> str:
    return (
        datetime.datetime.now(datetime.UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def feed_meta(
    source: str,
    query_params: dict[str, Any],
    n_records: int,
    latency_s: float,
    license_info: Mapping[str, str | list[str]],
    *,
    ttl_s: float,
    fetched_at: str | None = None,
    cached: bool = False,
    quota: dict[str, Any] | None = None,
    auth_required: bool = False,
    auth_present: bool = True,
    success: bool = True,
    error: str | None = None,
    geometries_returned: int | None = None,
) -> dict[str, Any]:
    """``build_meta`` + the feed extras.  ``fetched_at`` defaults to now; ``quota`` is present only
    for keyed or
    rate-limited sources."""
    meta = build_meta(
        source=source,
        query_params=query_params,
        geometries_returned=n_records if geometries_returned is None else geometries_returned,
        total_records_returned=n_records,
        latency_s=latency_s,
        license_info=license_info,
        auth_required=auth_required,
        auth_present=auth_present,
        success=success,
        error=error,
    )
    meta["ttl_s"] = float(ttl_s)
    meta["fetched_at"] = fetched_at or utc_now_iso()
    meta["cached"] = bool(cached)
    if quota is not None:
        meta["quota"] = quota
    return meta


def quota_refused(
    source: str,
    query_params: dict[str, Any],
    license_info: Mapping[str, str | list[str]],
    quota: dict[str, Any],
    *,
    ttl_s: float,
    auth_required: bool = False,
    auth_present: bool = True,
) -> dict[str, Any]:
    """The refusal at the limit: empty data, ``success: False``, the quota block, a reset time."""
    return {
        "data": [],
        "_meta": feed_meta(
            source,
            query_params,
            0,
            0.0,
            license_info,
            ttl_s=ttl_s,
            quota=quota,
            auth_required=auth_required,
            auth_present=auth_present,
            success=False,
            error=(
                f"quota: {quota['limit']} calls per {int(quota['window_s'])} s reached; "
                f"resets in {quota['resets_in_s']:.0f} s"
            ),
        ),
    }


def key_missing(
    source: str,
    key_name: str,
    signup_url: str,
    query_params: dict[str, Any],
    license_info: Mapping[str, str | list[str]],
    *,
    ttl_s: float,
) -> dict[str, Any]:
    """The keyed-source response when the key is unset: ``auth_required: True``,
    ``auth_present: False``, empty data, never an exception (the same shape as
    :func:`~env_data_mcp.helpers.auth_missing_response`)."""
    return {
        "data": [],
        "_meta": feed_meta(
            source,
            query_params,
            0,
            0.0,
            license_info,
            ttl_s=ttl_s,
            auth_required=True,
            auth_present=False,
            success=False,
            error=(
                f"{key_name} environment variable is not set. Register for a free key at "
                f"{signup_url} and set it in your environment or .env file."
            ),
        ),
    }


def bbox_params(min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> dict[str, float]:
    return {"min_lat": min_lat, "max_lat": max_lat, "min_lon": min_lon, "max_lon": max_lon}


def iso_or_none(value: Any) -> str | None:
    """Milliseconds-since-epoch (USGS) or an ISO string → ISO 8601 UTC string; None stays None."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):  # noqa: UP038
        return (
            datetime.datetime.fromtimestamp(float(value) / 1000.0, tz=datetime.UTC)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
    return str(value)
