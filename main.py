from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _desktop_self_test() -> int:
    """Exercise the exact Qt/WebEngine and local Python runtime used by desktop."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        import PySide6
        import shiboken6
        from PySide6.QtCore import qVersion
        from PySide6.QtWidgets import QApplication, QWidget
        from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineScript  # noqa: F401
        from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
        from desktop_native_runtime import desktop_fetch_bootstrap, start_native_server
        from desktop_web_shell import DEFAULT_DASHBOARD_URL, dashboard_url

        app = QApplication.instance() or QApplication([])
        probe = QWidget()
        probe.setWindowTitle("YCA self-test")
        probe.close()
        app.processEvents()

        url = dashboard_url()
        if url != DEFAULT_DASHBOARD_URL and not url.startswith("https://"):
            raise RuntimeError(f"dashboard URL inválida: {url}")

        with tempfile.TemporaryDirectory(prefix="yca-native-selftest-") as temp_dir:
            native_server, native_thread, native_base = start_native_server(Path(temp_dir) / "cache.json")
            try:
                with urllib.request.urlopen(native_base + "/health", timeout=3) as response:
                    native_health = json.loads(response.read().decode("utf-8"))
                if not native_health.get("ok") or native_health.get("external_ai_used") is not False:
                    raise RuntimeError(f"native runtime inválido: {native_health}")
                bootstrap = desktop_fetch_bootstrap(native_base)
                if "refreshAll()" in bootstrap:
                    raise RuntimeError("desktop bootstrap contém refresh recursivo proibido")
                if "8000" not in bootstrap or "yca:desktop-cache-updated" not in bootstrap:
                    raise RuntimeError("desktop bootstrap não contém timeout/refresh guard esperado")
            finally:
                native_server.shutdown()
                native_server.server_close()
                native_thread.join(timeout=3)

        payload = {
            "ok": True,
            "desktop_ui": "modern_production_dashboard",
            "dashboard_url": url,
            "qt_version": qVersion(),
            "pyside_version": getattr(PySide6, "__version__", "unknown"),
            "shiboken_version": getattr(shiboken6, "__version__", "unknown"),
            "qt_webengine": True,
            "desktop_native_python": True,
            "desktop_native_cache": True,
            "desktop_remote_read_timeout_seconds": 8,
            "desktop_refresh_loop_guard": True,
            "external_ai_called": False,
            "youtube_write_actions_executed": False,
        }
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 97


def main() -> int:
    if "--self-test" in sys.argv:
        return _desktop_self_test()

    from desktop_web_shell import run

    return int(run())


if __name__ == "__main__":
    raise SystemExit(main())
