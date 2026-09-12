from fastapi.testclient import TestClient

from creator_service.onboarding_api import COOKIE_NAME, create_app
from creator_service.onboarding_sessions import WebIdentity


class _DB:
    def ensure_tenant(self, tenant_id: str) -> str:
        return tenant_id


class _Resolver:
    def __init__(self) -> None:
        self.db = _DB()


class _Sessions:
    def resolve(self, token: str):
        if token == "still-valid":
            return WebIdentity("desktop-user", ("yca:read", "yca:write"))
        return None

    def exchange_launch(self, token: str):
        raise PermissionError("invalid")

    def revoke(self, token: str) -> None:
        return None


class _Verifier:
    async def verify_token(self, token: str):
        return None


def _client() -> TestClient:
    return TestClient(create_app(resolver=_Resolver(), verifier=_Verifier(), session_store=_Sessions()))


def test_desktop_navigation_does_not_loop_for_valid_or_expired_sessions():
    client = _client()

    expired = client.get("/dashboard", follow_redirects=False)
    assert expired.status_code == 303
    assert expired.headers["location"] == "/onboarding/session-expired"

    expired_page = client.get(expired.headers["location"], follow_redirects=False)
    assert expired_page.status_code == 200
    assert "Entrar novamente" in expired_page.text
    assert "location.href" not in expired_page.text

    client.cookies.set(COOKIE_NAME, "still-valid")
    login = client.get("/login", follow_redirects=False)
    assert login.status_code == 303
    assert login.headers["location"] == "/dashboard"
    dashboard = client.get("/dashboard", follow_redirects=False)
    assert dashboard.status_code == 200


def test_browser_session_cookie_contract_is_persistent_and_not_script_readable():
    source = open("src/creator_service/onboarding_api.py", encoding="utf-8").read()
    cookie_block = source.split("def set_session_cookie", 1)[1].split("def enforce_limit", 1)[0]
    assert "max_age=max_age" in cookie_block
    assert "httponly=True" in cookie_block
    assert "secure=secure_cookie_enabled()" in cookie_block
    assert 'samesite="lax"' in cookie_block
