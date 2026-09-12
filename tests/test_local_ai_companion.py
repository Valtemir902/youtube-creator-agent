from pathlib import Path

from src.local_ai import companion
from src.local_ai.capability import HardwareSnapshot


def test_config_round_trip_uses_explicit_path(tmp_path: Path):
    path = tmp_path / "config.json"
    companion.save_config({"token": "secret", "model": "qwen2.5:0.5b"}, path)
    assert companion.load_config(path) == {"token": "secret", "model": "qwen2.5:0.5b"}


def test_install_state_public_view_does_not_expose_token_or_hardware(monkeypatch):
    monkeypatch.setattr(
        companion,
        "load_install_state",
        lambda path=None: {
            "stage": "model_download",
            "status": "running",
            "percent": 42,
            "detail": "baixando modelo",
            "model": "qwen2.5:1.5b",
            "estimated_download_mb": 1000,
            "token": "must-not-leak",
            "hardware": {"gpu_name": "private-ish"},
        },
    )
    status = companion.public_install_status()
    assert status["percent"] == 42
    assert status["model"] == "qwen2.5:1.5b"
    assert "token" not in status
    assert "hardware" not in status


def test_local_status_reports_runtime_and_selected_model(monkeypatch):
    snapshot = HardwareSnapshot(
        os_name="Windows",
        architecture="AMD64",
        cpu_count=8,
        ram_mb=16384,
        gpu_name="NVIDIA RTX 3050 Laptop GPU",
        vram_mb=6144,
        nvidia_available=True,
        ollama_available=True,
    )
    monkeypatch.setattr(companion, "probe_hardware", lambda: snapshot)
    monkeypatch.setattr(
        companion,
        "_ollama_json",
        lambda method, path, body=None, timeout=120: {
            "models": [{"name": "qwen2.5:1.5b"}]
        },
    )
    monkeypatch.setattr(companion, "load_install_state", lambda path=None: {"status": "ready"})
    status = companion.local_status({"model": "qwen2.5:1.5b"})
    assert status["supported"] is True
    assert status["ollama_ready"] is True
    assert status["model_ready"] is True
    assert status["repair_needed"] is False
    assert status["profile"] == "local_standard"
    assert status["model_estimated_download_mb"] == 1000
    assert status["manifest_version"]


def test_local_status_detects_missing_model(monkeypatch):
    snapshot = HardwareSnapshot(
        os_name="Windows",
        architecture="AMD64",
        cpu_count=8,
        ram_mb=16384,
        gpu_name="NVIDIA RTX 3050 Laptop GPU",
        vram_mb=6144,
        nvidia_available=True,
        ollama_available=True,
    )
    monkeypatch.setattr(companion, "probe_hardware", lambda: snapshot)
    monkeypatch.setattr(
        companion,
        "_ollama_json",
        lambda method, path, body=None, timeout=120: {"models": []},
    )
    monkeypatch.setattr(companion, "load_install_state", lambda path=None: {})
    status = companion.local_status({"model": "qwen2.5:1.5b"})
    assert status["repair_needed"] is True
    assert "model_missing" in status["repair_reasons"]


def test_default_origins_are_restricted_to_creator_and_local_dev():
    assert "https://creator.silvadigitaltech.com" in companion.DEFAULT_ORIGINS
    assert all(origin.startswith(("https://creator.silvadigitaltech.com", "http://localhost", "http://127.0.0.1")) for origin in companion.DEFAULT_ORIGINS)


def test_pairing_requires_explicit_trusted_browser_origin():
    handler = object.__new__(companion.CompanionHandler)
    handler.server = type("Server", (), {"config": {"origins": ["https://creator.silvadigitaltech.com"]}})()
    handler.headers = {"Origin": "https://creator.silvadigitaltech.com"}
    assert handler._trusted_browser_origin() is True
    handler.headers = {"Origin": "https://evil.example"}
    assert handler._trusted_browser_origin() is False
    handler.headers = {}
    assert handler._trusted_browser_origin() is False
