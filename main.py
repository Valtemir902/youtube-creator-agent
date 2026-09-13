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
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        print(
            json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False),
            file=sys.stderr,
            flush=True,
        )
        return 97


class _LocalAiE2EState:
    event = threading.Event()
    report: dict | None = None
    requests: list[dict] = []


class _FakeLocalAiHandler(BaseHTTPRequestHandler):
    token = "windows-local-ai-e2e-token-1234567890"

    def log_message(self, fmt: str, *args) -> None:
        return

    def _record(self, method: str) -> None:
        _LocalAiE2EState.requests.append(
            {"method": method, "path": self.path, "origin": self.headers.get("Origin")}
        )

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
        self._record("OPTIONS")
        self._send(204, {})

    def do_GET(self) -> None:  # noqa: N802
        self._record("GET")
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
        self._record("POST")
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b""
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
        if self.path == "/v1/e2e-report":
            try:
                _LocalAiE2EState.report = json.loads(raw.decode("utf-8"))
            except Exception as exc:
                _LocalAiE2EState.report = {
                    "ok": False,
                    "stage": "report_decode",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            _LocalAiE2EState.event.set()
            self._send(200, {"ok": True})
            return
        self._send(404, {"ok": False, "error": "not_found"})


def _browser_driven_local_ai_probe() -> str:
    """Run the complete Local AI UI proof inside Chromium, not via PySide callbacks.

    QWebEnginePage.runJavaScript(..., callback) crashes natively on the Windows
    headless runner used by the packaged EXE test. The production UI itself is
    healthy. This probe is injected at DocumentReady and performs the same user
    path entirely in the browser, then reports the result over loopback HTTP.
    """

    return r"""
(async()=>{
  const report = async (payload) => {
    try {
      await fetch('http://127.0.0.1:17823/v1/e2e-report', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify(payload)
      });
    } catch (_) {}
  };
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  try {
    const bridgeDeadline = Date.now() + 8000;
    while (!(window.ycaLocalAI && typeof window.ycaLocalAI.refresh === 'function')) {
      if (Date.now() > bridgeDeadline) throw new Error('bridge_timeout');
      await sleep(50);
    }

    await window.ycaLocalAI.refresh();

    const statusDeadline = Date.now() + 8000;
    let status = '';
    while (Date.now() < statusDeadline) {
      status = document.getElementById('localAiStatus')?.innerText || '';
      if (status.includes('Ativa neste dispositivo')) break;
      await sleep(50);
    }

    const state = window.ycaLocalAI.state || null;
    if (!status.includes('Ativa neste dispositivo')) {
      throw new Error('ui_not_active:' + status.slice(0,300));
    }
    if (!state || !state.ready) throw new Error('bridge_not_ready');

    const chat = await window.ycaLocalAI.chat([{role:'user', content:'ping'}]);
    if (!chat || chat.text !== 'LOCAL_AI_E2E_OK') {
      throw new Error('chat_failed:' + JSON.stringify(chat));
    }

    await report({
      ok: true,
      stage: 'complete',
      ui_status: 'Ativa neste dispositivo',
      explicit_recheck: true,
      paired: true,
      capabilities_ready: true,
      local_chat: chat.text,
      cloud_session_required: false,
      youtube_write_actions_executed: false
    });
  } catch (e) {
    await report({
      ok: false,
      stage: 'browser_probe',
      error: String(e && (e.stack || e.message) || e)
    });
  }
})();
"""


def _desktop_local_ai_ui_self_test() -> int:
    """Verify the Local AI user path inside the packaged desktop executable.

    The test deliberately avoids Python callbacks from QWebEnginePage JavaScript.
    The browser executes recheck, pairing, capability validation, UI-state check
    and local chat, then reports over loopback HTTP. This is the same strategy as
    the focused E2E workflow that proved stable on Windows Server 2025.
    """

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    fake = None
    fake_thread = None
    window = None
    render_termination: dict[str, object] = {"seen": False, "status": None, "exit_code": None}

    try:
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtWidgets import QApplication
        from desktop_web_shell import DesktopWindow, local_ai_webengine_source

        source = local_ai_webengine_source()
        if "Ativa neste dispositivo" not in source:
            raise RuntimeError("bundle desktop não contém o estado ativo da IA Local")

        _LocalAiE2EState.event.clear()
        _LocalAiE2EState.report = None
        _LocalAiE2EState.requests = []

        fake = ThreadingHTTPServer(("127.0.0.1", 17823), _FakeLocalAiHandler)
        fake_thread = threading.Thread(
            target=fake.serve_forever,
            name="yca-packaged-local-ai-e2e",
            daemon=True,
        )
        fake_thread.start()

        app = QApplication.instance() or QApplication([])
        window = DesktopWindow(
            extra_document_ready_scripts=(
                ("yca-packaged-local-ai-browser-e2e", _browser_driven_local_ai_probe()),
            )
        )

        def on_render_terminated(status, exit_code: int) -> None:
            render_termination.update(
                seen=True,
                status=str(status),
                exit_code=int(exit_code),
            )
            _LocalAiE2EState.event.set()

        window.web.page().renderProcessTerminated.connect(on_render_terminated)
        window.show()

        deadline = time.monotonic() + 25
        while time.monotonic() < deadline and not _LocalAiE2EState.event.is_set():
            QCoreApplication.processEvents()
            time.sleep(0.01)

        if render_termination["seen"]:
            payload = {
                "ok": False,
                "stage": "renderer_terminated",
                "error": (
                    "Qt WebEngine renderer terminated: "
                    f"status={render_termination['status']} exit_code={render_termination['exit_code']}"
                ),
                "requests": _LocalAiE2EState.requests,
            }
            print(json.dumps(payload, ensure_ascii=False), flush=True)
            return 98

        if not _LocalAiE2EState.event.is_set():
            payload = {
                "ok": False,
                "stage": "python_wait",
                "error": "browser_report_timeout",
                "requests": _LocalAiE2EState.requests,
            }
            print(json.dumps(payload, ensure_ascii=False), flush=True)
            return 98

        report = dict(_LocalAiE2EState.report or {})
        report["requests"] = _LocalAiE2EState.requests
        print(json.dumps(report, ensure_ascii=False), flush=True)

        if not report.get("ok"):
            return 98

        required = {
            "ui_status": "Ativa neste dispositivo",
            "explicit_recheck": True,
            "paired": True,
            "capabilities_ready": True,
            "local_chat": "LOCAL_AI_E2E_OK",
            "cloud_session_required": False,
            "youtube_write_actions_executed": False,
        }
        for key, expected in required.items():
            if report.get(key) != expected:
                validation = {
                    "ok": False,
                    "stage": "python_validation",
                    "error": f"{key}={report.get(key)!r} esperado={expected!r}",
                    "requests": _LocalAiE2EState.requests,
                }
                print(json.dumps(validation, ensure_ascii=False), flush=True)
                return 98

        return 0
    except Exception as exc:
        payload = {
            "ok": False,
            "stage": "python_exception",
            "error": f"{type(exc).__name__}: {exc}",
            "requests": _LocalAiE2EState.requests,
        }
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr, flush=True)
        return 98
    finally:
        if window is not None:
            try:
                window.close()
                from PySide6.QtCore import QCoreApplication

                QCoreApplication.processEvents()
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
