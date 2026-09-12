from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from creator_service.observability import production_http_middleware


def _client() -> TestClient:
    app = FastAPI()
    app.middleware("http")(production_http_middleware)

    @app.get("/default")
    async def default_route():
        return PlainTextResponse("ok")

    @app.get("/strict")
    async def strict_route():
        return PlainTextResponse("ok", headers={"Referrer-Policy": "no-referrer"})

    return TestClient(app)


def test_middleware_adds_default_referrer_policy_when_route_does_not_choose_one():
    response = _client().get("/default")
    assert response.status_code == 200
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_middleware_preserves_stricter_route_specific_referrer_policy():
    response = _client().get("/strict")
    assert response.status_code == 200
    assert response.headers["referrer-policy"] == "no-referrer"
