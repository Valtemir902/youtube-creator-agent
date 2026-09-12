from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute


_WRONG_OVERVIEW_SELECTOR = "document.getElementById('home')"
_REAL_OVERVIEW_SELECTOR = "document.getElementById('overview')"


def fix_professional_overview_html(source: str) -> str:
    """Align the additive professional layer with the existing dashboard DOM.

    The legacy dashboard's home section has always been named ``overview``.
    Keeping this as a small compatibility layer avoids changing any existing
    navigation IDs or handlers while the professional layer remains additive.
    """
    if _WRONG_OVERVIEW_SELECTOR not in source:
        return source
    return source.replace(_WRONG_OVERVIEW_SELECTOR, _REAL_OVERVIEW_SELECTOR, 1)


def _find_dashboard_route(app: FastAPI) -> APIRoute:
    for route in app.router.routes:
        if isinstance(route, APIRoute) and route.path == "/dashboard" and "GET" in (route.methods or set()):
            return route
    raise RuntimeError("Dashboard route not found for overview compatibility fix.")


def install_dashboard_overview_compat(app: FastAPI) -> None:
    route = _find_dashboard_route(app)
    original = route.endpoint
    app.router.routes.remove(route)

    async def corrected_dashboard(request: Request):
        response = await original(request)
        if not isinstance(response, HTMLResponse):
            return response
        headers = dict(response.headers)
        headers.pop("content-length", None)
        headers.pop("content-type", None)
        return HTMLResponse(
            fix_professional_overview_html(response.body.decode("utf-8")),
            status_code=response.status_code,
            headers=headers,
        )

    app.add_api_route(
        "/dashboard",
        corrected_dashboard,
        methods=["GET"],
        include_in_schema=False,
        name="professional_dashboard_overview_compat",
    )
