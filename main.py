from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


class _FakeLocalAiHandler(BaseHTTPRequestHandler):
    token = "windows-local-ai-e2e-token-1234567890"

    def log_message(self, fmt: str, *args) -> None:
        return

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        origin = self.headers.get("Origin")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin, Access-Control-Request-Private-Network")
        if self.headers.get("Access-Control-Request-Private-Network", "").lower() == "true":
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, {})

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/v1/health":
            self._send(200, {"ok": True, "service": "yca-local-ai"})
            return
        if self.path == "/v1/install-status":
            self._send(200, {"ok": True, "service": "yca-local-ai", "status": "ready"})
            return
        if self.path == "/v1/capabilities":
            if self.headers.get("Authorization") != f"Bearer {self.token}":
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            self._send(
                200,
                {
                    "ok": True,
                    "service": "yca-local-ai",
                    "manifest_version": "e2e",
                    "profile": "local_standard",
                    "supported": True,
                    "model": "qwen2.5:1.5b",
                    "model_display_name": "Qwen 2.5 1.5B",
                    "model_estimated_download_mb": 1000,
                    "model_ready": True,
                    "ollama_ready": True,
                    "repair_needed": False,
                    "repair_reasons": [],
                    "install_state": {"status": "ready"},
                    "hardware": {
                        "gpu_name": "Windows CI GPU",
                        "vram_mb": 6144,
                        "ram_mb": 16384,
                    },
                },
            )
            return
        self._send(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/v1/pair":
            self._send(200, {"ok": True, "service": "yca-local-ai", "token": self.token})
            return
        if self.path == "/v1/chat":
            if self.headers.get("Authorization") != f"Bearer {self.token}":
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            self._send(
                200,
                {
                    "ok": True,
                    "provider": "local",
                    "model": "qwen2.5:1.5b",
                    "text": "LOCAL_AI_E2E_OK",
                    "elapsed_ms": 5,
                },
            )
            return
        self._send(404, {"ok": False, "error": "not_found"})


def _desktop_local_ai_ui_self_test() -> int:
    """Verify an explicit Local AI recheck moves the desktop UI to ready.

    The production dashboard intentionally does not probe Local AI on startup.
    This E2E mirrors the user's explicit "Reavaliar dispositivo" action, then
    validates pairing, capabilities and local chat end to end. It remains fully
    read-only with respect to YouTube.
    """

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    fake = None
    fake_thread = None
    window = None
    try:
        from PySide6.QtCore import QEventLoop, QTimer
        from PySide6.QtWidgets import QApplication
        from desktop_web_shell import DesktopWindow, local_ai_webengine_source

        if "Ativa neste dispositivo" not in local_ai_webengine_source():
            raise RuntimeError("bundle desktop não contém o estado ativo da IA Local")

        fake = ThreadingHTTPServer(("127.0.0.1", 17823), _FakeLocalAiHandler)
        fake_thread = threading.Thread(target=fake.serve_forever, name="yca-fake-local-ai", daemon=True)
        fake_thread.start()

        app = QApplication.instance() or QApplication([])
        window = DesktopWindow()
        window.show()

        load_loop = QEventLoop()
        load_ok = {"value": False}

        def on_loaded(ok: bool) -> None:
            load_ok["value"] = bool(ok)
            load_loop.quit()

        window.web.loadFinished.connect(on_loaded)
        QTimer.singleShot(15000, load_loop.quit)
        load_loop.exec()
        if not load_ok["value"]:
            raise RuntimeError("dashboard local não terminou de carregar no WebEngine")

        def js(code: str, timeout_ms: int = 4000):
            loop = QEventLoop()
            box = {"done": False, "value": None}

            def done(value):
                box["done"] = True
                box["value"] = value
                loop.quit()

            window.web.page().runJavaScript(code, 0, done)
            QTimer.singleShot(timeout_ms, loop.quit)
            loop.exec()
            if not box["done"]:
                raise RuntimeError(f"JavaScript não respondeu: {code[:80]}")
            return box["value"]

        # Production boot is intentionally passive. Wait for the injected bridge,
        # then exercise the same explicit refresh behind "Reavaliar dispositivo".
        bridge_deadline = time.monotonic() + 8
        bridge_ready = False
        while time.monotonic() < bridge_deadline:
            app.processEvents()
            bridge_ready = bool(js("!!(window.ycaLocalAI && window.ycaLocalAI.refresh)", 1500))
            if bridge_ready:
                break
            time.sleep(0.1)
        if not bridge_ready:
            raise RuntimeError("bridge da IA Local não ficou disponível no WebEngine")

        js(
            "window.__ycaLocalAiRefreshE2E='pending';"
            "window.ycaLocalAI.refresh()"
            ".then(()=>window.__ycaLocalAiRefreshE2E='done')"
            ".catch(e=>window.__ycaLocalAiRefreshE2E='ERR:'+e.message);"
        )

        refresh_deadline = time.monotonic() + 12
        refresh_result = "pending"
        while time.monotonic() < refresh_deadline:
            app.processEvents()
            refresh_result = str(js("window.__ycaLocalAiRefreshE2E || ''", 1500) or "")
            if refresh_result != "pending":
                break
            time.sleep(0.1)
        if refresh_result != "done":
            raise RuntimeError(f"reavaliação explícita da IA Local falhou: {refresh_result}")

        deadline = time.monotonic() + 8
        status_text = ""
        while time.monotonic() < deadline:
            app.processEvents()
            status_text = str(js("document.getElementById('localAiStatus')?.innerText || ''", 1500) or "")
            if "Ativa neste dispositivo" in status_text:
                break
            time.sleep(0.1)
        if "Ativa neste dispositivo" not in status_text:
            raise RuntimeError(f"IA Local não mudou para ativa. Estado final: {status_text[:500]}")

        state = js("window.ycaLocalAI ? window.ycaLocalAI.state : null")
        if not isinstance(state, dict) or not state.get("ready"):
            raise RuntimeError(f"estado JS da IA Local não ficou pronto: {state}")

        js(
            "window.__ycaLocalAiE2E='pending';"
            "window.ycaLocalAI.chat([{role:'user',content:'ping'}])"
            ".then(r=>window.__ycaLocalAiE2E=r.text)"
            ".catch(e=>window.__ycaLocalAiE2E='ERR:'+e.message);"
        )
        deadline = time.monotonic() + 8
        chat_result = "pending"
        while time.monotonic() < deadline:
            app.processEvents()
            chat_result = str(js("window.__ycaLocalAiE2E || ''", 1500) or "")
            if chat_result != "pending":
                break
            time.sleep(0.1)
        if chat_result != "LOCAL_AI_E2E_OK":
            raise RuntimeError(f"chat local não respondeu pelo bridge da interface: {chat_result}")

        print(
            json.dumps(
                {
                    "ok": True,
                    "ui_status": "Ativa neste dispositivo",
                    "explicit_recheck": True,
                    "paired": True,
                    "capabilities_ready": True,
                    "local_chat": chat_result,
                    "cloud_session_required": False,
                    "youtube_write_actions_executed": False,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 98
    finally:
        if window is not None:
            try:
                window.close()
            except Exception:
                pass
        if fake is not None:
            fake.shutdown()
            fake.server_close()
        if fake_thread is not None:
            fake_thread.join(timeout=3)


def main() -> int:
    if "--self-test" in sys.argv:
        return _desktop_self_test()
    if "--local-ai-ui-self-test" in sys.argv:
        return _desktop_local_ai_ui_self_test()

    from desktop_web_shell import run

    return int(run())


if __name__ == "__main__":
    raise SystemExit(main())
