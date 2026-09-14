from __future__ import annotations

import json
from pathlib import Path
from urllib.request import urlopen

import desktop_local_server as local


def test_local_dashboard_is_bundled_and_does_not_require_cloud_session(monkeypatch, tmp_path):
    monkeypatch.setattr(local, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(local, "load_credentials", lambda **kwargs: None)
    server, thread, base = local.start_local_app_server()
    try:
        with urlopen(base + "/health", timeout=3) as response:
            health = json.loads(response.read().decode("utf-8"))
        assert health["ok"] is True
        assert health["mode"] == "desktop_local_first"
        assert health["youtube_connected"] is False

        with urlopen(base + "/dashboard", timeout=3) as response:
            html = response.read().decode("utf-8")
        assert "YouTube Creator Agent Elite" in html
        assert "Elite · Local" in html
        assert "Desconectar YouTube" in html
        assert "creator.silvadigitaltech.com/dashboard" not in html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_local_status_advertises_python_ollama_and_no_cloud_session(monkeypatch, tmp_path):
    monkeypatch.setattr(local, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(local, "load_credentials", lambda **kwargs: None)
    monkeypatch.setattr(local, "ensure_config", lambda: {"model": "qwen2.5:1.5b"})
    server, thread, base = local.start_local_app_server()
    try:
        with urlopen(base + "/api/dashboard/status", timeout=3) as response:
            status = json.loads(response.read().decode("utf-8"))
        assert status["youtube_connected"] is False
        assert status["ai_provider"] == "ollama"
        assert status["ai_model"] == "qwen2.5:1.5b"
        assert status["desktop_local"] is True
        assert status["processing_location"] == "this_computer"

        with urlopen(base + "/api/dashboard/capabilities", timeout=3) as response:
            capabilities = json.loads(response.read().decode("utf-8"))
        assert capabilities["desktop_local_first"] is True
        assert capabilities["native_python_engine"] is True
        assert capabilities["local_ai"] is True
        assert capabilities["cloud_session_required"] is False
        assert capabilities["passive_external_ai"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_local_oauth_is_loopback_and_writes_remain_blocked():
    source = Path("src/desktop_local_server.py").read_text(encoding="utf-8")
    assert "InstalledAppFlow" in source
    assert "run_local_server(port=0" in source
    assert "AuthorizedSession" in source
    assert "youtube-token.json" in source
    assert "preview → confirmação → apply" in source
    assert "HTTPStatus.NOT_IMPLEMENTED" in source


def test_windows_shell_loads_localhost_not_production_dashboard():
    source = Path("src/desktop_web_shell.py").read_text(encoding="utf-8")
    assert "start_local_app_server" in source
    assert 'self.local_base + "/dashboard"' in source
    assert "creator.silvadigitaltech.com" not in source
    assert "desktop_fetch_bootstrap" not in source
