import json
from pathlib import Path

from scripts import yca_local_ai_setup as setup
from src.local_ai import desktop


def test_native_bridge_health_does_not_require_browser_network(monkeypatch):
    monkeypatch.setattr(desktop, "ensure_config", lambda: {"model": "qwen2.5:1.5b"})
    bridge = desktop.NativeLocalAIBridge()
    response = bridge.bridge_request("/v1/health")
    payload = json.loads(response["body"])
    assert response["status"] == 200
    assert payload == {"ok": True, "service": "yca-local-ai", "transport": "native"}


def test_native_bridge_capabilities_are_in_process(monkeypatch):
    config = {"model": "qwen2.5:1.5b"}
    monkeypatch.setattr(desktop, "ensure_config", lambda: config)
    monkeypatch.setattr(
        desktop,
        "local_status",
        lambda active: {"ok": True, "model": active["model"], "model_ready": True, "ollama_ready": True},
    )
    bridge = desktop.NativeLocalAIBridge()
    response = bridge.bridge_request("/v1/capabilities", headers={"Authorization": "anything"})
    payload = json.loads(response["body"])
    assert response["status"] == 200
    assert payload["transport"] == "native"
    assert payload["model_ready"] is True


def test_native_bridge_chat_routes_directly_to_ollama(monkeypatch):
    monkeypatch.setattr(desktop, "ensure_config", lambda: {"model": "qwen2.5:1.5b"})
    calls = []

    def fake_ollama(method, path, body, timeout):
        calls.append((method, path, body, timeout))
        return {"model": "qwen2.5:1.5b", "message": {"content": "Resposta local"}, "eval_count": 5}

    monkeypatch.setattr(desktop, "_ollama_json", fake_ollama)
    bridge = desktop.NativeLocalAIBridge()
    response = bridge.bridge_request(
        "/v1/chat",
        method="POST",
        body=json.dumps({"messages": [{"role": "user", "content": "teste"}]}),
    )
    payload = json.loads(response["body"])
    assert response["status"] == 200
    assert payload["provider"] == "local"
    assert payload["transport"] == "native"
    assert payload["text"] == "Resposta local"
    assert calls[0][0:2] == ("POST", "/api/chat")


def test_fetch_shim_only_intercepts_local_ai_loopback():
    assert "http://127.0.0.1:17823" in desktop._FETCH_SHIM
    assert "window.pywebview.api.bridge_request" in desktop._FETCH_SHIM
    assert "return nativeFetch(input, init)" in desktop._FETCH_SHIM


def test_windows_protocol_launches_desktop_shell():
    executable = Path(r"C:\Users\Example\AppData\Local\YouTubeCreatorAgent\LocalAI\YCA-Local-AI.exe")
    command = setup.protocol_command(executable)
    assert command.startswith(f'"{executable}" --desktop')
    assert '"%1"' in command
    assert setup.APP_PROTOCOL == "yca-creator-agent"
