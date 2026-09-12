from pathlib import Path

from src.local_ai import companion
from src.local_ai.capability import HardwareSnapshot


def test_config_round_trip_uses_explicit_path(tmp_path: Path):
    path = tmp_path / "config.json"
    companion.save_config({"token": "secret", "model": "qwen2.5:0.5b"}, path)
    assert companion.load_config(path) == {"token": "secret", "model": "qwen2.5:0.5b"}


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
    status = companion.local_status({"model": "qwen2.5:1.5b"})
    assert status["supported"] is True
    assert status["ollama_ready"] is True
    assert status["model_ready"] is True
    assert status["profile"] == "local_standard"


def test_default_origins_are_restricted_to_creator_and_local_dev():
    assert "https://creator.silvadigitaltech.com" in companion.DEFAULT_ORIGINS
    assert all(origin.startswith(("https://creator.silvadigitaltech.com", "http://localhost", "http://127.0.0.1")) for origin in companion.DEFAULT_ORIGINS)
