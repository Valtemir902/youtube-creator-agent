from __future__ import annotations

import faulthandler
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
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr, flush=True)
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
                    "hardware": {"gpu_name": "Windows CI GPU", "vram_mb": 6144, "ram_mb": 16384},
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
            self._send(200, {"ok": True, "provider": "local", "model": "qwen2.5:1.5b", "text": "LOCAL_AI_E2E_OK", "elapsed_ms": 5})
            return
        self._send(404, {"ok": False, "error": "not_found"})


def _desktop_local_ai_ui_self_test() -> int:
    """Verify explicit Local AI recheck, with crash-safe diagnostics.

    The harness intentionally avoids nested QEventLoop.exec() calls around
    QWebEnginePage.runJavaScript. Nested event loops are a known high-risk shape
    for lifecycle/reentrancy bugs in Qt WebEngine, especially on headless CI.
    Each native boundary is persisted to local-ai-ui-e2e-trace.jsonl before and
    after it, so even an access violation leaves the last completed checkpoint.
    """

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    trace_path = Path(os.environ.get("YCA_E2E_TRACE_PATH", "local-ai-ui-e2e-trace.jsonl"))
    crash_path = Path(os.environ.get("YCA_E2E_FAULT_PATH", "local-ai-ui-e2e-faulthandler.log"))
    fake = None
    fake_thread = None
    window = None
    fault_file = None

    def checkpoint(stage: str, **details) -> None:
        record = {"ts": time.time(), "stage": stage, **details}
        line = json.dumps(record, ensure_ascii=False)
        with trace_path.open("a", encoding="utf-8") as fp:
            fp.write(line + "\n")
            fp.flush()
            try:
                os.fsync(fp.fileno())
            except OSError:
                pass
        print(f"E2E_CHECKPOINT {line}", flush=True)

    try:
        trace_path.unlink(missing_ok=True)
        crash_path.unlink(missing_ok=True)
        fault_file = crash_path.open("w", encoding="utf-8")
        faulthandler.enable(file=fault_file, all_threads=True)
        checkpoint("python_start", pid=os.getpid(), platform=sys.platform)

        from PySide6.QtCore import QCoreApplication
        from PySide6.QtWidgets import QApplication
        from desktop_web_shell import DesktopWindow, local_ai_webengine_source

        checkpoint("imports_ok")
        source = local_ai_webengine_source()
        checkpoint("bundle_built", chars=len(source), has_active_label="Ativa neste dispositivo" in source)
        if "Ativa neste dispositivo" not in source:
            raise RuntimeError("bundle desktop não contém o estado ativo da IA Local")

        fake = ThreadingHTTPServer(("127.0.0.1", 17823), _FakeLocalAiHandler)
        fake_thread = threading.Thread(target=fake.serve_forever, name="yca-fake-local-ai", daemon=True)
        fake_thread.start()
        checkpoint("fake_companion_started", port=17823)

        app = QApplication.instance() or QApplication([])
        checkpoint("qapplication_ready")

        window = DesktopWindow()
        checkpoint("desktop_window_constructed", local_base=window.local_base)

        page = window.web.page()
        render_termination = {"seen": False, "status": None, "exit_code": None}

        def on_render_terminated(status, exit_code: int) -> None:
            render_termination.update(seen=True, status=str(status), exit_code=int(exit_code))
            checkpoint("render_process_terminated", status=str(status), exit_code=int(exit_code))

        page.renderProcessTerminated.connect(on_render_terminated)
        checkpoint("render_termination_hooked")

        loaded = {"done": False, "ok": False}

        def on_loaded(ok: bool) -> None:
            loaded["done"] = True
            loaded["ok"] = bool(ok)
            checkpoint("load_finished_signal", ok=bool(ok), url=window.web.url().toString())

        window.web.loadFinished.connect(on_loaded)
        checkpoint("load_signal_hooked")
        window.show()
        checkpoint("window_shown")

        def pump_until(predicate, timeout_s: float, stage: str) -> bool:
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                QCoreApplication.processEvents()
                if predicate():
                    return True
                time.sleep(0.01)
            checkpoint(stage + "_timeout")
            return False

        if not pump_until(lambda: loaded["done"], 15, "page_load"):
            raise RuntimeError("dashboard local não terminou de carregar no WebEngine")
        if not loaded["ok"]:
            raise RuntimeError("dashboard local emitiu loadFinished(false)")
        checkpoint("page_load_ok")

        js_counter = {"value": 0}

        def js(code: str, timeout_ms: int = 4000):
            js_counter["value"] += 1
            call_id = js_counter["value"]
            box = {"done": False, "value": None}
            checkpoint("js_before", call_id=call_id, code=code[:120])

            def done(value):
                box["done"] = True
                box["value"] = value
                checkpoint("js_callback", call_id=call_id, value_type=type(value).__name__)

            page.runJavaScript(code, 0, done)
            checkpoint("js_submitted", call_id=call_id)
            ok = pump_until(lambda: box["done"] or render_termination["seen"], timeout_ms / 1000, f"js_{call_id}")
            if render_termination["seen"]:
                raise RuntimeError(
                    "renderer do Qt WebEngine terminou durante JavaScript: "
                    f"status={render_termination['status']} exit_code={render_termination['exit_code']} call_id={call_id}"
                )
            if not ok or not box["done"]:
                raise RuntimeError(f"JavaScript não respondeu: call_id={call_id} code={code[:80]}")
            checkpoint("js_after", call_id=call_id)
            return box["value"]

        checkpoint("bridge_probe_start")
        bridge_deadline = time.monotonic() + 8
        bridge_ready = False
        while time.monotonic() < bridge_deadline:
            bridge_ready = bool(js("!!(window.ycaLocalAI && window.ycaLocalAI.refresh)", 1500))
            if bridge_ready:
                break
            time.sleep(0.05)
        checkpoint("bridge_probe_done", ready=bridge_ready)
        if not bridge_ready:
            raise RuntimeError("bridge da IA Local não ficou disponível no WebEngine")

        checkpoint("refresh_submit_start")
        js(
            "window.__ycaLocalAiRefreshE2E='pending';"
            "window.ycaLocalAI.refresh()"
            ".then(()=>window.__ycaLocalAiRefreshE2E='done')"
            ".catch(e=>window.__ycaLocalAiRefreshE2E='ERR:'+e.message);"
        )
        checkpoint("refresh_submit_done")

        refresh_deadline = time.monotonic() + 12
        refresh_result = "pending"
        while time.monotonic() < refresh_deadline:
            refresh_result = str(js("window.__ycaLocalAiRefreshE2E || ''", 1500) or "")
            if refresh_result != "pending":
                break
            time.sleep(0.05)
        checkpoint("refresh_result", result=refresh_result)
        if refresh_result != "done":
            raise RuntimeError(f"reavaliação explícita da IA Local falhou: {refresh_result}")

        deadline = time.monotonic() + 8
        status_text = ""
        while time.monotonic() < deadline:
            status_text = str(js("document.getElementById('localAiStatus')?.innerText || ''", 1500) or "")
            if "Ativa neste dispositivo" in status_text:
                break
            time.sleep(0.05)
        checkpoint("ui_status", value=status_text[:500])
        if "Ativa neste dispositivo" not in status_text:
            raise RuntimeError(f"IA Local não mudou para ativa. Estado final: {status_text[:500]}")

        state = js("window.ycaLocalAI ? window.ycaLocalAI.state : null")
        checkpoint("bridge_state", state=state)
        if not isinstance(state, dict) or not state.get("ready"):
            raise RuntimeError(f"estado JS da IA Local não ficou pronto: {state}")

        checkpoint("chat_submit_start")
        js(
            "window.__ycaLocalAiE2E='pending';"
            "window.ycaLocalAI.chat([{role:'user',content:'ping'}])"
            ".then(r=>window.__ycaLocalAiE2E=r.text)"
            ".catch(e=>window.__ycaLocalAiE2E='ERR:'+e.message);"
        )
        deadline = time.monotonic() + 8
        chat_result = "pending"
        while time.monotonic() < deadline:
            chat_result = str(js("window.__ycaLocalAiE2E || ''", 1500) or "")
            if chat_result != "pending":
                break
            time.sleep(0.05)
        checkpoint("chat_result", result=chat_result)
        if chat_result != "LOCAL_AI_E2E_OK":
            raise RuntimeError(f"chat local não respondeu pelo bridge da interface: {chat_result}")

        payload = {
            "ok": True,
            "ui_status": "Ativa neste dispositivo",
            "explicit_recheck": True,
            "paired": True,
            "capabilities_ready": True,
            "local_chat": chat_result,
            "cloud_session_required": False,
            "youtube_write_actions_executed": False,
            "diagnostic_trace": str(trace_path),
        }
        checkpoint("success")
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        try:
            checkpoint("python_exception", error=f"{type(exc).__name__}: {exc}")
        except Exception:
            pass
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}", "diagnostic_trace": str(trace_path)}, ensure_ascii=False), file=sys.stderr, flush=True)
        return 98
    finally:
        if window is not None:
            try:
                checkpoint("window_close_start")
                window.close()
                checkpoint("window_close_done")
            except Exception as exc:
                try:
                    checkpoint("window_close_error", error=str(exc))
                except Exception:
                    pass
        if fake is not None:
            fake.shutdown()
            fake.server_close()
        if fake_thread is not None:
            fake_thread.join(timeout=3)
        if fault_file is not None:
            try:
                faulthandler.disable()
                fault_file.flush()
                fault_file.close()
            except Exception:
                pass


def main() -> int:
    if "--self-test" in sys.argv:
        return _desktop_self_test()
    if "--local-ai-ui-self-test" in sys.argv:
        return _desktop_local_ai_ui_self_test()

    from desktop_web_shell import run

    return int(run())


if __name__ == "__main__":
    raise SystemExit(main())
