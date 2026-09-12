from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
import time
from typing import Any
from urllib import request as urlrequest

from .capability import classify_hardware, probe_hardware
from .manifest import MANIFEST_VERSION, model_for_profile


DEFAULT_PORT = 17823
DEFAULT_ORIGINS = {
    "https://creator.silvadigitaltech.com",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
}


def default_config_dir() -> Path:
    import os

    root = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".youtube-creator-agent")
    return Path(root) / "YouTubeCreatorAgent" / "LocalAI"


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or default_config_dir() / "config.json"
    if not config_path.exists():
        return {}
    return json.loads(config_path.read_text(encoding="utf-8"))


def load_install_state(path: Path | None = None) -> dict[str, Any]:
    state_path = path or default_config_dir() / "install-state.json"
    if not state_path.exists():
        return {}
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def public_install_status() -> dict[str, Any]:
    state = load_install_state()
    allowed = {
        "stage",
        "status",
        "percent",
        "detail",
        "model",
        "estimated_download_mb",
        "updated_at",
    }
    public = {key: state.get(key) for key in allowed if key in state}
    public["ok"] = True
    public["service"] = "yca-local-ai"
    return public


def save_config(config: dict[str, Any], path: Path | None = None) -> Path:
    config_path = path or default_config_dir() / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config_path


def ensure_config() -> dict[str, Any]:
    config = load_config()
    if config.get("token"):
        return config
    snapshot = probe_hardware()
    profile = classify_hardware(snapshot)
    model = model_for_profile(profile)
    config = {
        "token": secrets.token_urlsafe(32),
        "profile": profile.value,
        "model": model.ollama_model if model else None,
        "port": DEFAULT_PORT,
        "origins": sorted(DEFAULT_ORIGINS),
        "manifest_version": MANIFEST_VERSION,
        "created_at": int(time.time()),
    }
    save_config(config)
    return config


def _ollama_json(method: str, path: str, body: dict[str, Any] | None = None, timeout: int = 120) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urlrequest.Request(
        f"http://127.0.0.1:11434{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urlrequest.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def local_status(config: dict[str, Any]) -> dict[str, Any]:
    snapshot = probe_hardware()
    profile = classify_hardware(snapshot)
    selected = model_for_profile(profile)
    ollama_ok = False
    installed_models: list[str] = []
    try:
        tags = _ollama_json("GET", "/api/tags", timeout=3)
        ollama_ok = True
        installed_models = [
            str(item.get("name") or item.get("model"))
            for item in tags.get("models", [])
            if item.get("name") or item.get("model")
        ]
    except Exception:
        pass
    model_name = config.get("model") or (selected.ollama_model if selected else None)
    model_ready = bool(model_name and any(name == model_name or name.startswith(f"{model_name}:") for name in installed_models))
    repair_reasons: list[str] = []
    if selected is not None and not ollama_ok:
        repair_reasons.append("runtime_unavailable")
    if selected is not None and ollama_ok and not model_ready:
        repair_reasons.append("model_missing")
    install_state = load_install_state()
    return {
        "ok": True,
        "service": "yca-local-ai",
        "manifest_version": MANIFEST_VERSION,
        "profile": profile.value,
        "supported": selected is not None,
        "model": model_name,
        "model_display_name": selected.display_name if selected else None,
        "model_estimated_download_mb": selected.estimated_download_mb if selected else None,
        "model_recommended_free_disk_mb": selected.recommended_free_disk_mb if selected else None,
        "model_ready": model_ready,
        "ollama_ready": ollama_ok,
        "repair_needed": bool(repair_reasons),
        "repair_reasons": repair_reasons,
        "install_state": install_state,
        "hardware": snapshot.to_dict(),
    }


class CompanionHandler(BaseHTTPRequestHandler):
    server_version = "YCA-LocalAI/1.1"

    @property
    def config(self) -> dict[str, Any]:
        return self.server.config  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return origin in set(self.config.get("origins") or DEFAULT_ORIGINS)

    def _authorized(self) -> bool:
        expected = str(self.config.get("token") or "")
        supplied = self.headers.get("Authorization", "")
        return bool(expected) and secrets.compare_digest(supplied, f"Bearer {expected}")

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        origin = self.headers.get("Origin")
        if origin and self._origin_allowed():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self._origin_allowed():
            self._send(403, {"ok": False, "error": "origin_not_allowed"})
            return
        self._send(204, {})

    def do_GET(self) -> None:  # noqa: N802
        if not self._origin_allowed():
            self._send(403, {"ok": False, "error": "origin_not_allowed"})
            return
        if self.path == "/v1/health":
            self._send(200, {"ok": True, "service": "yca-local-ai"})
            return
        if self.path == "/v1/install-status":
            self._send(200, public_install_status())
            return
        if not self._authorized():
            self._send(401, {"ok": False, "error": "unauthorized"})
            return
        if self.path == "/v1/capabilities":
            self._send(200, local_status(self.config))
            return
        self._send(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._origin_allowed():
            self._send(403, {"ok": False, "error": "origin_not_allowed"})
            return
        if not self._authorized():
            self._send(401, {"ok": False, "error": "unauthorized"})
            return
        length = min(int(self.headers.get("Content-Length", "0") or 0), 512_000)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            self._send(400, {"ok": False, "error": "invalid_json"})
            return

        if self.path == "/v1/chat":
            model = str(self.config.get("model") or "")
            messages = payload.get("messages")
            if not model or not isinstance(messages, list) or not messages:
                self._send(400, {"ok": False, "error": "invalid_request"})
                return
            body = {
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": max(0.0, min(float(payload.get("temperature", 0.2)), 1.5)),
                    "num_predict": max(16, min(int(payload.get("max_output_tokens", 512)), 2048)),
                },
            }
            started = time.perf_counter()
            try:
                result = _ollama_json("POST", "/api/chat", body, timeout=180)
                text = str((result.get("message") or {}).get("content") or "").strip()
                if not text:
                    raise RuntimeError("empty_response")
                self._send(
                    200,
                    {
                        "ok": True,
                        "provider": "local",
                        "model": result.get("model") or model,
                        "text": text,
                        "elapsed_ms": int((time.perf_counter() - started) * 1000),
                        "prompt_eval_count": result.get("prompt_eval_count"),
                        "eval_count": result.get("eval_count"),
                    },
                )
            except Exception as exc:
                self._send(503, {"ok": False, "error": "local_model_unavailable", "detail": str(exc)[:200]})
            return

        if self.path == "/v1/benchmark":
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
                self._send(200, {"ok": True, "elapsed_ms": int(elapsed * 1000), "tokens_per_second": round(count / elapsed, 2) if elapsed > 0 else None})
            except Exception as exc:
                self._send(503, {"ok": False, "error": "benchmark_failed", "detail": str(exc)[:200]})
            return

        self._send(404, {"ok": False, "error": "not_found"})


def serve(config: dict[str, Any] | None = None) -> None:
    active = config or ensure_config()
    port = int(active.get("port") or DEFAULT_PORT)
    server = ThreadingHTTPServer(("127.0.0.1", port), CompanionHandler)
    server.config = active  # type: ignore[attr-defined]
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    if args.serve:
        serve()
    else:
        print(json.dumps(local_status(ensure_config()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
