from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from creator_service.dashboard_routes import UploadStartRequest, _clean_tags, _validate_schedule
from creator_service.onboarding_api import create_app


class FakeDB:
    def ensure_tenant(self, tenant_id: str) -> str:
        return tenant_id


class FakeResolver:
    def __init__(self):
        self.db = FakeDB()


class FakeSessionStore:
    def resolve(self, token: str):
        return None

    def exchange_launch(self, token: str):
        raise PermissionError("invalid")

    def revoke(self, token: str):
        return None


class FakeVerifier:
    async def verify_token(self, token: str):
        if token == "read-token":
            return SimpleNamespace(subject="u", scopes=["yca:read"], claims={"tenant_id": "t"})
        if token == "write-token":
            return SimpleNamespace(subject="u", scopes=["yca:read", "yca:write"], claims={"tenant_id": "t"})
        return None


def make_client() -> TestClient:
    return TestClient(
        create_app(
            resolver=FakeResolver(),
            verifier=FakeVerifier(),
            session_store=FakeSessionStore(),
        )
    )


def test_dashboard_route_inventory_is_complete():
    app = make_client().app
    paths = {route.path for route in app.routes}
    expected = {
        "/dashboard",
        "/api/dashboard/status",
        "/api/dashboard/capabilities",
        "/api/dashboard/channel",
        "/api/dashboard/videos",
        "/api/dashboard/video/{video_id}",
        "/api/dashboard/evidence",
        "/api/dashboard/audit",
        "/api/dashboard/keywords/validate",
        "/api/dashboard/research/topic",
        "/api/dashboard/strategy/build",
        "/api/dashboard/actions/{video_id}",
        "/api/dashboard/metadata/preview",
        "/api/dashboard/metadata/apply/{action_id}",
        "/api/dashboard/metadata/rollback/{action_id}",
        "/api/dashboard/upload/start",
        "/api/dashboard/upload/chunk/{session_id}",
        "/api/dashboard/upload/finish/{session_id}",
        "/api/dashboard/upload/{session_id}",
        "/api/dashboard/upload/apply/{action_id}",
    }
    assert expected <= paths


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/dashboard/status"),
        ("get", "/api/dashboard/videos"),
        ("get", "/api/dashboard/audit"),
        ("post", "/api/dashboard/metadata/preview"),
        ("post", "/api/dashboard/upload/start"),
    ],
)
def test_dashboard_api_requires_authentication(method: str, path: str):
    client = make_client()
    response = getattr(client, method)(path, json={}) if method == "post" else getattr(client, method)(path)
    assert response.status_code == 401


def test_write_routes_reject_read_only_scope_before_business_logic():
    client = make_client()
    response = client.post(
        "/api/dashboard/metadata/preview",
        headers={"Authorization": "Bearer read-token"},
        json={"video_id": "abc123"},
    )
    assert response.status_code == 403
    assert "yca:write" in response.json()["detail"]


def test_upload_model_rejects_oversized_video():
    with pytest.raises(Exception):
        UploadStartRequest(
            video_name="video.mp4",
            video_size=65 * 1024 * 1024 * 1024,
            title="Teste",
        )


def test_clean_tags_deduplicates_and_caps_count():
    tags = _clean_tags([" Roça ", "roça", "pulverizador", *[f"tag {i}" for i in range(30)]])
    assert tags[0] == "Roça"
    assert tags[1] == "pulverizador"
    assert len(tags) == 12


def test_schedule_requires_timezone_and_future_time():
    with pytest.raises(ValueError):
        _validate_schedule("2026-09-06T10:00:00")
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    value = _validate_schedule(future.isoformat())
    assert value.endswith("Z")
