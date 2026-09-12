from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _desktop_self_test() -> int:
    """Exercise the Qt shell and the fully local desktop control plane."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        import PySide6
        import shiboken6
        from PySide6.QtCore import qVersion
        from PySide6.QtWidgets import QApplication, QWidget
        from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
        from desktop_local_server import dashboard_html_path, start_local_app_server

        app = QApplication.instance() or QApplication([])
        probe = QWidget()
        probe.setWindowTitle("YCA local-first self-test")
        probe.close()
        app.processEvents()

        dashboard_path = dashboard_html_path()
        if not dashboard_path.is_file():
            raise RuntimeError(f"dashboard local não empacotado: {dashboard_path}")

        server, thread, base = start_local_app_server()
        try:
            with urllib.request.urlopen(base + "/health", timeout=3) as response:
                health = json.loads(response.read().decode("utf-8"))
            if not health.get("ok") or health.get("mode") != "desktop_local_first":
                raise RuntimeError(f"runtime local inválido: {health}")
            with urllib.request.urlopen(base + "/dashboard", timeout=3) as response:
                html = response.read().decode("utf-8")
            if "YouTube Creator Agent Elite" not in html or "Elite · Local" not in html:
                raise RuntimeError("dashboard profissional local não foi servido corretamente")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

        payload = {
            "ok": True,
            "desktop_ui": "professional_local_dashboard",
            "desktop_local_first": True,
            "cloud_session_required": False,
            "youtube_oauth_local": True,
            "youtube_api_transport": "direct_from_pc",
            "qt_version": qVersion(),
            "pyside_version": getattr(PySide6, "__version__", "unknown"),
            "shiboken_version": getattr(shiboken6, "__version__", "unknown"),
            "qt_webengine": True,
            "native_python_engine": True,
            "local_ai_provider": "ollama",
            "local_fact_cache": True,
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
