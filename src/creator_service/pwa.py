from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.routing import APIRoute


WEB_ROOT = Path(__file__).resolve().parent / "web"
PWA_ROOT = WEB_ROOT / "pwa"

PWA_ASSETS = {
    "app-icon.svg": ("image/svg+xml", "public, max-age=86400"),
    "app-icon-solid.svg": ("image/svg+xml", "public, max-age=86400"),
    "app-icon-maskable.svg": ("image/svg+xml", "public, max-age=86400"),
    "icon-1024.png": ("image/png", "public, max-age=86400"),
    "icon-512.png": ("image/png", "public, max-age=86400"),
    "icon-192.png": ("image/png", "public, max-age=86400"),
    "icon-180.png": ("image/png", "public, max-age=86400"),
    "icon-maskable-512.png": ("image/png", "public, max-age=86400"),
    "icon-solid-512.png": ("image/png", "public, max-age=86400"),
    "favicon-32.png": ("image/png", "public, max-age=86400"),
    "bootstrap.js": ("application/javascript; charset=utf-8", "no-cache"),
    "install.css": ("text/css; charset=utf-8", "no-cache"),
}


_HEAD_MARKUP = """  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="icon" type="image/png" sizes="32x32" href="/pwa/favicon-32.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/pwa/icon-180.png">
  <link rel="stylesheet" href="/pwa/install.css">
  <meta name="application-name" content="Creator Agent Elite">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="Creator Agent">
  <script defer src="/pwa/bootstrap.js"></script>
"""


def enhance_pwa_html(source: str) -> str:
    """Add install metadata without caching or changing authenticated page logic."""
    if 'rel="manifest" href="/manifest.webmanifest"' in source:
        return source
    if "</head>" not in source:
        raise RuntimeError("PWA injection requires a complete HTML <head>.")
    return source.replace("</head>", _HEAD_MARKUP + "</head>", 1)


def _find_get_route(app: FastAPI, path: str) -> APIRoute:
    for route in app.router.routes:
        if isinstance(route, APIRoute) and route.path == path and "GET" in (route.methods or set()):
            return route
    raise RuntimeError(f"Required HTML route not found: {path}")


def _replace_html_route(app: FastAPI, path: str) -> None:
    route = _find_get_route(app, path)
    original = route.endpoint
    app.router.routes.remove(route)

    async def enhanced(request: Request):
        response = await original(request)
        if not isinstance(response, FileResponse):
            return response

        page = Path(response.path)
        source = page.read_text(encoding="utf-8")
        headers = {
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "X-PWA-Enhanced": "1",
        }
        return HTMLResponse(
            enhance_pwa_html(source),
            status_code=response.status_code,
            headers=headers,
        )

    app.add_api_route(
        path,
        enhanced,
        methods=["GET"],
        include_in_schema=False,
        name=f"pwa_{path.strip('/').replace('/', '_') or 'root'}",
    )


def install_pwa_routes(app: FastAPI) -> None:
    """Install an explicit, static-only PWA surface around the existing web routes."""
    _replace_html_route(app, "/login")
    _replace_html_route(app, "/dashboard")

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def pwa_manifest() -> FileResponse:
        return FileResponse(
            PWA_ROOT / "manifest.webmanifest",
            media_type="application/manifest+json",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/sw.js", include_in_schema=False)
    async def pwa_service_worker() -> FileResponse:
        return FileResponse(
            PWA_ROOT / "sw.js",
            media_type="application/javascript; charset=utf-8",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Service-Worker-Allowed": "/",
            },
        )

    @app.get("/pwa/{asset_name}", include_in_schema=False)
    async def pwa_asset(asset_name: str) -> FileResponse:
        metadata = PWA_ASSETS.get(asset_name)
        if metadata is None:
            raise HTTPException(status_code=404, detail="PWA asset not found.")
        media_type, cache_control = metadata
        return FileResponse(
            PWA_ROOT / asset_name,
            media_type=media_type,
            headers={"Cache-Control": cache_control},
        )
