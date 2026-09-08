from __future__ import annotations

import json
import subprocess
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.testclient import TestClient

from creator_service.pwa import PWA_ROOT, enhance_pwa_html, install_pwa_routes


def make_test_app(tmp_path: Path) -> FastAPI:
    login = tmp_path / "login.html"
    dashboard = tmp_path / "dashboard.html"
    login.write_text("<!doctype html><html><head><title>Login</title></head><body>login</body></html>", encoding="utf-8")
    dashboard.write_text("<!doctype html><html><head><title>Dashboard</title></head><body>dashboard</body></html>", encoding="utf-8")

    app = FastAPI()

    @app.get("/login")
    async def login_page(request: Request):
        if request.cookies.get("session") == "ok":
            return RedirectResponse("/dashboard", status_code=303)
        return FileResponse(login, media_type="text/html", headers={"Cache-Control": "no-store"})

    @app.get("/dashboard")
    async def dashboard_page(request: Request):
        if request.cookies.get("session") != "ok":
            return RedirectResponse("/login", status_code=303)
        return FileResponse(dashboard, media_type="text/html", headers={"Cache-Control": "no-store"})

    @app.get("/api/private")
    async def private_api():
        return {"secret": "network-only"}

    install_pwa_routes(app)
    return app


def test_html_enhancement_is_idempotent_and_keeps_existing_content():
    source = "<html><head><meta name=\"theme-color\" content=\"#000\"></head><body>safe</body></html>"
    enhanced = enhance_pwa_html(source)
    assert enhanced.count('rel="manifest" href="/manifest.webmanifest"') == 1
    assert '<link rel="stylesheet" href="/pwa/install.css">' in enhanced
    assert '<script defer src="/pwa/bootstrap.js"></script>' in enhanced
    assert '<body>safe</body>' in enhanced
    assert enhance_pwa_html(enhanced) == enhanced


def test_login_and_dashboard_receive_pwa_install_surface_without_html_cache(tmp_path: Path):
    client = TestClient(make_test_app(tmp_path))

    login = client.get("/login", follow_redirects=False)
    assert login.status_code == 200
    assert login.headers["cache-control"] == "no-store"
    assert login.headers["pragma"] == "no-cache"
    assert login.headers["x-pwa-enhanced"] == "1"
    assert 'rel="manifest"' in login.text
    assert '/pwa/install.css' in login.text
    assert '/pwa/bootstrap.js' in login.text

    dashboard = client.get("/dashboard", follow_redirects=False)
    assert dashboard.status_code == 303
    assert dashboard.headers["location"] == "/login"

    client.cookies.set("session", "ok")
    dashboard = client.get("/dashboard", follow_redirects=False)
    assert dashboard.status_code == 200
    assert dashboard.headers["cache-control"] == "no-store"
    assert dashboard.headers["pragma"] == "no-cache"
    assert 'rel="manifest"' in dashboard.text
    assert '/pwa/install.css' in dashboard.text
    assert '/pwa/bootstrap.js' in dashboard.text


def test_install_cta_contract_covers_login_dashboard_native_prompt_and_fallback():
    source = (PWA_ROOT / "bootstrap.js").read_text(encoding="utf-8")

    assert "location.pathname === '/login'" in source
    assert "Instalar Creator Agent" in source
    assert "yca-install-login" in source
    assert "location.pathname === '/dashboard'" in source
    assert "yca-install-dashboard" in source
    assert "document.querySelector('.top-actions')" in source

    assert "beforeinstallprompt" in source
    assert "event.preventDefault()" in source
    assert "deferredPrompt = event" in source
    assert "await deferredPrompt.prompt()" in source
    assert "await deferredPrompt.userChoice" in source

    assert "No Chrome, abra o menu ⋮" in source
    assert "Adicionar à tela inicial" in source
    assert "No Safari, toque em Compartilhar" in source
    assert "Adicionar à Tela de Início" in source
    assert "showFallback()" in source
    assert "installFallback" in source


def test_install_cta_hides_completely_in_standalone_mode():
    source = (PWA_ROOT / "bootstrap.js").read_text(encoding="utf-8")
    assert "matchMedia?.('(display-mode: standalone)').matches === true" in source
    assert "window.navigator.standalone === true" in source
    assert "if (state.installedMode)" in source
    assert "removeInstallUI();" in source
    assert "appinstalled" in source


def test_install_cta_visual_contract_is_premium_and_motion_safe():
    css = (PWA_ROOT / "install.css").read_text(encoding="utf-8")
    assert ".yca-install-login-wrap" in css
    assert ".yca-install-dashboard" in css
    assert ".yca-install-fallback" in css
    assert "@keyframes ycaInstallPulse" in css
    assert "box-shadow:" in css
    assert "prefers-reduced-motion: reduce" in css
    assert "safe-area-inset-bottom" in css


def test_manifest_is_professional_and_points_only_to_declared_icons():
    manifest = json.loads((PWA_ROOT / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["name"] == "Creator Agent Elite"
    assert manifest["short_name"] == "Creator Agent"
    assert manifest["start_url"] == "/dashboard"
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["theme_color"] == "#0B0D12"
    assert manifest["background_color"] == "#0B0D12"
    assert manifest["prefer_related_applications"] is False

    icons = manifest["icons"]
    assert {icon["sizes"] for icon in icons} >= {"192x192", "512x512", "1024x1024"}
    assert any(icon.get("purpose") == "maskable" for icon in icons)
    for icon in icons:
        assert icon["src"].startswith("/pwa/")


def test_service_worker_is_static_only_and_explicitly_bypasses_sensitive_routes():
    source = (PWA_ROOT / "sw.js").read_text(encoding="utf-8")
    for sensitive in ("/oauth", "/auth", "/login", "/callback", "/mcp", "/api", "/onboarding"):
        assert repr(sensitive) in source
    assert "if (isSensitive(url.pathname)) return;" in source
    assert "if (!STATIC_PATHS.has(url.pathname)) return;" in source
    assert "request.method !== 'GET'" in source
    assert "caches.open(CACHE_NAME)" in source
    assert "fetch(request)" in source

    static_block = source.split("const STATIC_PATHS", 1)[1].split("]);", 1)[0]
    assert "/pwa/install.css" in static_block
    for forbidden in ("/login", "/dashboard", "/oauth", "/auth", "/callback", "/api", "/mcp", "/onboarding"):
        assert forbidden not in static_block
    for secretish in ("token", "session", "authorization"):
        assert secretish not in static_block.lower()


def test_service_worker_and_bootstrap_javascript_parse_with_node():
    for name in ("sw.js", "bootstrap.js"):
        subprocess.run(
            ["node", "--check", str(PWA_ROOT / name)],
            check=True,
            capture_output=True,
            text=True,
        )


def test_public_pwa_assets_and_headers(tmp_path: Path):
    client = TestClient(make_test_app(tmp_path))

    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200
    assert manifest.headers["content-type"].startswith("application/manifest+json")
    assert "no-cache" in manifest.headers["cache-control"]

    sw = client.get("/sw.js")
    assert sw.status_code == 200
    assert sw.headers["service-worker-allowed"] == "/"
    assert "no-store" in sw.headers["cache-control"]

    css = client.get("/pwa/install.css")
    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert "no-cache" in css.headers["cache-control"]

    for asset in ("icon-192.png", "icon-512.png", "icon-1024.png", "icon-maskable-512.png", "favicon-32.png", "app-icon.svg"):
        response = client.get(f"/pwa/{asset}")
        assert response.status_code == 200
        assert int(response.headers["content-length"]) > 100

    assert client.get("/pwa/not-declared.png").status_code == 404


def test_pwa_asset_dimensions_are_exact():
    import struct

    expected = {
        "icon-1024.png": (1024, 1024),
        "icon-512.png": (512, 512),
        "icon-192.png": (192, 192),
        "icon-180.png": (180, 180),
        "icon-maskable-512.png": (512, 512),
        "icon-solid-512.png": (512, 512),
        "favicon-32.png": (32, 32),
    }
    for name, size in expected.items():
        data = (PWA_ROOT / name).read_bytes()
        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", data[16:24])
        assert (width, height) == size
