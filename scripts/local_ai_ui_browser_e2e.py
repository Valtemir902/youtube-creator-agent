from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from desktop_web_shell import DesktopWindow  # noqa: E402


class E2EState:
    event = threading.Event()
    report: dict | None = None
    requests: list[dict] = []


class FakeLocalAiHandler(BaseHTTPRequestHandler):
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
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record(self, method: str) -> None:
        E2EState.requests.append({"method": method, "path": self.path, "origin": self.headers.get("Origin")})

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
                    "hardware": {"gpu_name": "Windows CI GPU", "vram_mb": 6144, "ram_mb": 16384},
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
            self._send(200, {"ok": True, "provider": "local", "model": "qwen2.5:1.5b", "text": "LOCAL_AI_E2E_OK", "elapsed_ms": 5})
            return
        if self.path == "/v1/e2e-report":
            try:
                E2EState.report = json.loads(raw.decode("utf-8"))
            except Exception as exc:
                E2EState.report = {"ok": False, "stage": "report_decode", "error": f"{type(exc).__name__}: {exc}"}
            E2EState.event.set()
            self._send(200, {"ok": True})
            return
        self._send(404, {"ok": False, "error": "not_found"})


def browser_probe_source() -> str:
    return r"""
(async()=>{
  const report = async (payload) => {
    try {
      await fetch('http://127.0.0.1:17823/v1/e2e-report', {
        method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)
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
    if (!chat || chat.text !== 'LOCAL_AI_E2E_OK') throw new Error('chat_failed:' + JSON.stringify(chat));
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
    await report({ok:false, stage:'browser_probe', error:String(e && (e.stack || e.message) || e)});
  }
})();
"""


def main() -> int:
    E2EState.event.clear()
    E2EState.report = None
    E2EState.requests = []
    fake = ThreadingHTTPServer(("127.0.0.1", 17823), FakeLocalAiHandler)
    thread = threading.Thread(target=fake.serve_forever, name="yca-browser-e2e-fake", daemon=True)
    thread.start()
    window = None
    try:
        app = QApplication.instance() or QApplication([])
        window = DesktopWindow(extra_document_ready_scripts=(("yca-local-ai-browser-e2e", browser_probe_source()),))
        window.show()
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline and not E2EState.event.is_set():
            QCoreApplication.processEvents()
            time.sleep(0.01)
        if not E2EState.event.is_set():
            payload = {"ok": False, "stage": "python_wait", "error": "browser_report_timeout", "requests": E2EState.requests}
            print(json.dumps(payload, ensure_ascii=False), flush=True)
            return 98
        report = dict(E2EState.report or {})
        report["requests"] = E2EState.requests
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
                print(json.dumps({"ok": False, "stage": "python_validation", "error": f"{key}={report.get(key)!r} esperado={expected!r}"}, ensure_ascii=False), flush=True)
                return 98
        return 0
    finally:
        if window is not None:
            window.close()
            QCoreApplication.processEvents()
        fake.shutdown()
        fake.server_close()
        thread.join(timeout=3)


if __name__ == "__main__":
    raise SystemExit(main())
