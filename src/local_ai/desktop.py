from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

from .companion import ensure_config, local_status, public_install_status, _ollama_json

DASHBOARD_URL = "https://creator.silvadigitaltech.com/dashboard?yca_desktop=1"
LOCAL_PREFIX = "http://127.0.0.1:17823"


class NativeLocalAIBridge:
    """Minimal native bridge used by the Windows desktop shell.

    The cloud dashboard keeps using the same Local AI HTTP contract, but the
    desktop shell intercepts those calls and executes them in-process. No
    browser localhost permission, CORS, PNA or exposed listening socket is
    required for the desktop experience.
    """

    def __init__(self) -> None:
        self.config = ensure_config()

    @staticmethod
    def _response(status: int, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": int(status),
            "headers": {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"},
            "body": json.dumps(payload, ensure_ascii=False),
        }

    def bridge_request(
        self,
        path: str,
        method: str = "GET",
        body: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        del headers  # Authentication is provided by the trusted desktop shell.
        method = str(method or "GET").upper()
        path = str(path or "").split("?", 1)[0]

        if method == "GET" and path == "/v1/health":
            return self._response(200, {"ok": True, "service": "yca-local-ai", "transport": "native"})
        if method == "GET" and path == "/v1/install-status":
            return self._response(200, public_install_status())
        if method == "POST" and path == "/v1/pair":
            # Existing dashboard code expects a token. It never leaves this
            # WebView and is not used by the native transport for auth.
            return self._response(
                200,
                {
                    "ok": True,
                    "service": "yca-local-ai",
                    "transport": "native",
                    "token": "native-desktop-bridge-token-not-network-auth",
                },
            )
        if method == "GET" and path == "/v1/capabilities":
            payload = local_status(self.config)
            payload["transport"] = "native"
            return self._response(200, payload)

        try:
            payload = json.loads(body) if body else {}
        except (TypeError, ValueError):
            return self._response(400, {"ok": False, "error": "invalid_json"})

        if method == "POST" and path == "/v1/chat":
            model = str(self.config.get("model") or "")
            messages = payload.get("messages")
            if not model or not isinstance(messages, list) or not messages:
                return self._response(400, {"ok": False, "error": "invalid_request"})
            started = time.perf_counter()
            try:
                result = _ollama_json(
                    "POST",
                    "/api/chat",
                    {
                        "model": model,
                        "messages": messages,
                        "stream": False,
                        "options": {
                            "temperature": max(0.0, min(float(payload.get("temperature", 0.2)), 1.5)),
                            "num_predict": max(16, min(int(payload.get("max_output_tokens", 512)), 2048)),
                        },
                    },
                    timeout=180,
                )
                text = str((result.get("message") or {}).get("content") or "").strip()
                if not text:
                    raise RuntimeError("empty_response")
                return self._response(
                    200,
                    {
                        "ok": True,
                        "provider": "local",
                        "transport": "native",
                        "model": result.get("model") or model,
                        "text": text,
                        "elapsed_ms": int((time.perf_counter() - started) * 1000),
                        "prompt_eval_count": result.get("prompt_eval_count"),
                        "eval_count": result.get("eval_count"),
                    },
                )
            except Exception as exc:
                return self._response(
                    503,
                    {"ok": False, "error": "local_model_unavailable", "detail": str(exc)[:200]},
                )

        if method == "POST" and path == "/v1/benchmark":
            model = str(self.config.get("model") or "")
            started = time.perf_counter()
            try:
                result = _ollama_json(
                    "POST",
                    "/api/chat",
                    {
                        "model": model,
                        "messages": [{"role": "user", "content": "Responda apenas: OK"}],
                        "stream": False,
                        "options": {"temperature": 0, "num_predict": 8},
                    },
                    timeout=60,
                )
                elapsed = time.perf_counter() - started
                count = int(result.get("eval_count") or 0)
                return self._response(
                    200,
                    {
                        "ok": True,
                        "transport": "native",
                        "elapsed_ms": int(elapsed * 1000),
                        "tokens_per_second": round(count / elapsed, 2) if elapsed > 0 else None,
                    },
                )
            except Exception as exc:
                return self._response(503, {"ok": False, "error": "benchmark_failed", "detail": str(exc)[:200]})

        return self._response(404, {"ok": False, "error": "not_found"})


_FETCH_SHIM = r"""
(() => {
  if (window.__ycaNativeLocalAI) return;
  window.__ycaNativeLocalAI = true;
  const nativeFetch = window.fetch.bind(window);
  const PREFIX = 'http://127.0.0.1:17823';
  window.fetch = async function(input, init = {}) {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    if (!url.startsWith(PREFIX)) return nativeFetch(input, init);
    const parsed = new URL(url);
    const method = String(init.method || (input && input.method) || 'GET').toUpperCase();
    const headers = {};
    try {
      new Headers(init.headers || (input && input.headers) || {}).forEach((v, k) => { headers[k] = v; });
    } catch (_) {}
    const body = init.body == null ? null : String(init.body);
    const result = await window.pywebview.api.bridge_request(parsed.pathname + parsed.search, method, body, headers);
    return new Response(result.body || '', { status: result.status || 500, headers: result.headers || {} });
  };
  setTimeout(() => document.getElementById('localAiRecheck')?.click(), 250);
})();
"""


def launch_desktop(url: str = DASHBOARD_URL) -> None:
    try:
        import webview
    except ImportError as exc:  # pragma: no cover - exercised by packaged smoke test
        raise RuntimeError("O componente desktop da IA Local não foi empacotado corretamente.") from exc

    bridge = NativeLocalAIBridge()
    profile_dir = Path.home() / "AppData" / "Local" / "YouTubeCreatorAgent" / "WebViewProfile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    window = webview.create_window(
        "YouTube Creator Agent Elite",
        url=url,
        js_api=bridge,
        width=1480,
        height=940,
        min_size=(1080, 700),
    )

    def inject() -> None:
        try:
            window.evaluate_js(_FETCH_SHIM)
        except Exception:
            pass

    window.events.loaded += inject
    webview.start(gui="edgechromium", private_mode=False, storage_path=str(profile_dir), debug=False)


def desktop_self_test() -> dict[str, Any]:
    import webview  # noqa: F401 - proves the packaged desktop dependency exists

    bridge = NativeLocalAIBridge()
    health = json.loads(bridge.bridge_request("/v1/health")["body"])
    return {
        "ok": bool(health.get("ok")),
        "desktop_runtime": "pywebview-edgechromium",
        "native_bridge": health.get("transport") == "native",
    }
