from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import creator_service.oauth_compat_app as composed
from creator_service.onboarding_api import create_app as create_base_app


class FakeDB:
    path = None

    def ensure_tenant(self, tenant_id: str) -> str:
        return tenant_id


class FakeResolver:
    def __init__(self) -> None:
        self.db = FakeDB()

    def resolve(self, tenant_id: str):
        raise AssertionError("Browser fixture must not resolve real tenant services")


class FakeVerifier:
    async def verify_token(self, token: str):
        return SimpleNamespace(
            subject="browser-fixture",
            scopes=["yca:read"],
            claims={"tenant_id": "fixture-tenant"},
        )


class FakeSessionStore:
    def resolve(self, token: str):
        if token == "browser-fixture":
            return SimpleNamespace(tenant_id="fixture-tenant", scopes=("yca:read",))
        return None

    def exchange_launch(self, token: str):
        raise PermissionError("fixture")

    def revoke(self, token: str):
        return None


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts" / "recovery-dashboard.html"
    output.parent.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("YCA_ROOT", str(root / ".browser-fixture"))
    os.environ.setdefault("YCA_DATA_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    os.environ.setdefault("YCA_SECURE_COOKIES", "0")

    def fake_extended_app():
        return create_base_app(
            resolver=FakeResolver(),
            verifier=FakeVerifier(),
            session_store=FakeSessionStore(),
        )

    original = composed.create_extended_app
    composed.create_extended_app = fake_extended_app
    try:
        app = composed.create_app()
        client = TestClient(app)
        client.cookies.set("yca_onboarding_session", "browser-fixture")
        response = client.get("/dashboard", follow_redirects=False)
        if response.status_code != 200:
            raise SystemExit(f"dashboard fixture returned HTTP {response.status_code}")
        html = response.text
    finally:
        composed.create_extended_app = original

    required = [
        "data-yca-stability-guard",
        "ycaInitialLoad();",
        "professional-v1.11-fast-independent-boot",
    ]
    # The revision lives in Python state rather than HTML, so assert it directly.
    if app.state.dashboard_ui_revision != required[-1]:
        raise SystemExit(f"unexpected dashboard revision: {app.state.dashboard_ui_revision}")
    for marker in required[:-1]:
        if marker not in html:
            raise SystemExit(f"missing composed dashboard marker: {marker}")

    forbidden = [
        "data-yca-pro-dashboard",
        "data-yca-native-ux",
        "data-yca-connection-health",
        "data-yca-activity-ux",
        "Verificando YouTube API",
    ]
    for marker in forbidden:
        if marker in html:
            raise SystemExit(f"passive/legacy dashboard layer still present: {marker}")

    output.write_text(html, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
