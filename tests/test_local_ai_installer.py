from pathlib import Path

from scripts import yca_local_ai_setup as setup
from src.local_ai.capability import CapabilityProfile
from src.local_ai.manifest import MANIFEST_VERSION, model_for_profile


def test_model_manifest_exposes_version_and_realistic_download_sizes():
    assert MANIFEST_VERSION
    lite = model_for_profile(CapabilityProfile.LOCAL_LITE)
    standard = model_for_profile(CapabilityProfile.LOCAL_STANDARD)
    pro = model_for_profile(CapabilityProfile.LOCAL_PRO)
    assert lite and standard and pro
    assert 100 <= lite.estimated_download_mb < standard.estimated_download_mb < pro.estimated_download_mb
    assert standard.ollama_model == "qwen2.5:1.5b"
    assert standard.recommended_free_disk_mb > standard.estimated_download_mb


def test_percent_handles_unknown_and_bounds():
    assert setup._percent(1, None) is None
    assert setup._percent(1, 0) is None
    assert setup._percent(50, 100) == 50
    assert setup._percent(150, 100) == 100


def test_install_state_is_written_atomically(monkeypatch, tmp_path: Path):
    state = tmp_path / "install-state.json"
    monkeypatch.setattr(setup, "install_state_path", lambda: state)
    setup.write_install_state(
        stage="model_download",
        status="running",
        percent=37,
        detail="baixando",
        model="qwen2.5:1.5b",
        estimated_download_mb=1000,
    )
    payload = state.read_text(encoding="utf-8")
    assert '"stage": "model_download"' in payload
    assert '"percent": 37' in payload
    assert '"estimated_download_mb": 1000' in payload
    assert not state.with_suffix(".tmp").exists()


def test_windows_release_workflow_requires_signed_tag_and_does_not_publish_on_branch_push():
    workflow = Path(".github/workflows/local-ai-companion.yml").read_text(encoding="utf-8")
    assert "WINDOWS_CODESIGN_PFX_BASE64" in workflow
    assert "Get-AuthenticodeSignature" in workflow
    assert "Stable local-AI tag publication requires a trusted Authenticode signing identity." in workflow
    publish_line = next(line for line in workflow.splitlines() if "steps.signing.outputs.signed == 'true'" in line)
    assert "github.ref_type == 'tag'" in publish_line
    assert "refs/heads/feat/web-dashboard-v1" not in publish_line
