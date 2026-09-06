from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from creator_service.onboarding_api import create_app


class FakeDB:
    def ensure_tenant(self, tenant_id: str) -> str:
        if tenant_id != "u_testtenant":
            raise RuntimeError("unexpected tenant")
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
            return SimpleNamespace(
                subject="user-1",
                scopes=["yca:read"],
                claims={"tenant_id": "u_testtenant"},
            )
        if token == "write-token":
            return SimpleNamespace(
                subject="user-1",
                scopes=["yca:read", "yca:write"],
                claims={"tenant_id": "u_testtenant"},
            )
        return None


def client() -> TestClient:
    return TestClient(
        create_app(
            resolver=FakeResolver(),
            verifier=FakeVerifier(),
            session_store=FakeSessionStore(),
        )
    )


def test_health_is_public():
    response = client().get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["version"] == 14


def test_root_sends_anonymous_browser_to_login():
    response = client().get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_page_is_public_mobile_ready_and_has_no_precaptcha_gate():
    response = client().get("/login")
    assert response.status_code == 200
    assert "Criar conta" in response.text
    assert "Esqueci minha senha" in response.text
    assert "challenges.cloudflare.com" not in response.text
    assert "turnstile" not in response.text.lower()
    assert "viewport" in response.text.lower()


def test_auth_config_reports_identity_provider_ready_state_without_captcha_secret(monkeypatch):
    monkeypatch.setenv("YCA_TURNSTILE_SITE_KEY", "legacy-site-key")
    monkeypatch.setenv("YCA_TURNSTILE_SECRET_KEY", "legacy-secret")
    response = client().get("/api/auth/config")
    assert response.status_code == 200
    body = response.json()
    assert body["turnstile_required"] is False
    assert body["turnstile_ready"] is True
    assert body["turnstile_bypass"] is True
    assert body["turnstile_site_key"] == ""
    assert "legacy-secret" not in response.text


def test_auth_begin_fails_closed_when_server_storage_is_unavailable():
    response = client().post(
        "/api/auth/begin",
        json={"mode": "login", "next": "/dashboard", "turnstile_token": ""},
    )
    assert response.status_code == 503
    assert "armazenamento" in response.json()["detail"].lower()


def test_me_requires_authentication():
    response = client().get("/api/me")
    assert response.status_code == 401


def test_me_uses_tenant_from_authenticated_token():
    response = client().get(
        "/api/me",
        headers={"Authorization": "Bearer read-token"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "tenant_id": "u_testtenant",
        "subject": "user-1",
        "scopes": ["yca:read"],
        "auth_method": "bearer",
    }


def test_write_endpoint_rejects_read_only_token_before_business_logic():
    response = client().post(
        "/api/youtube/connect",
        headers={"Authorization": "Bearer read-token"},
    )
    assert response.status_code == 403
    assert "yca:write" in response.json()["detail"]


def test_invalid_token_is_rejected():
    response = client().get(
        "/api/me",
        headers={"Authorization": "Bearer invalid"},
    )
    assert response.status_code == 401


def test_public_information_pages_are_available_without_authentication():
    for path, expected_text in (
        ("/privacy", "Política de Privacidade"),
        ("/terms", "Termos de Uso"),
        ("/support", "silvadigitaltech@gmail.com"),
    ):
        response = client().get(path)
        assert response.status_code == 200
        assert expected_text in response.text
