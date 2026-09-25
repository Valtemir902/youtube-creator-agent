from __future__ import annotations

import json
from types import SimpleNamespace

from creator_service.dashboard_routes import _youtube_http_error_details


class FakeHttpError:
    def __init__(self, status: int, reason: str = "", message: str = ""):
        self.resp = SimpleNamespace(status=status)
        self.content = json.dumps(
            {"error": {"code": status, "message": message, "errors": [{"reason": reason, "message": message}]}}
        ).encode("utf-8")


def test_quota_error_is_distinguished_from_server_failure():
    status, body = _youtube_http_error_details(FakeHttpError(403, "quotaExceeded", "Quota exceeded"))
    assert status == 403
    assert body["error_code"] == "youtube_quota_exceeded"
    assert body["retryable"] is False
    assert body["upstream_status"] == 403


def test_rate_limit_is_retryable_429():
    status, body = _youtube_http_error_details(FakeHttpError(403, "rateLimitExceeded", "Too many requests"))
    assert status == 429
    assert body["error_code"] == "youtube_rate_limited"
    assert body["retryable"] is True


def test_youtube_5xx_becomes_explicit_503():
    status, body = _youtube_http_error_details(FakeHttpError(500, "backendError", "Backend error"))
    assert status == 503
    assert body["error_code"] == "youtube_upstream_unavailable"
    assert body["retryable"] is True


def test_auth_failure_is_not_reported_as_generic_500():
    status, body = _youtube_http_error_details(FakeHttpError(401, "authError", "Invalid credentials"))
    assert status == 401
    assert body["error_code"] == "youtube_auth_expired"
    assert body["retryable"] is False
