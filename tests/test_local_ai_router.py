from src.local_ai.capability import HardwareSnapshot
from src.local_ai.router import IntelligenceMode, decide_route


def snapshot(vram: int | None, *, nvidia: bool = True) -> HardwareSnapshot:
    return HardwareSnapshot(
        os_name="Windows",
        architecture="AMD64",
        cpu_count=8,
        ram_mb=16384,
        gpu_name="NVIDIA RTX" if nvidia else None,
        vram_mb=vram,
        nvidia_available=nvidia,
        ollama_available=True,
    )


def test_auto_uses_local_only_when_runtime_is_ready():
    pending = decide_route(snapshot(6144), IntelligenceMode.AUTO, local_runtime_ready=False)
    assert pending.effective_mode == IntelligenceMode.NATIVE
    assert pending.fallback_reason == "local_runtime_not_ready"

    ready = decide_route(snapshot(6144), IntelligenceMode.AUTO, local_runtime_ready=True)
    assert ready.effective_mode == IntelligenceMode.LOCAL
    assert ready.model is not None
    assert ready.model.ollama_model == "qwen2.5:3b"


def test_unsupported_hardware_never_forces_local():
    decision = decide_route(snapshot(None, nvidia=False), IntelligenceMode.LOCAL, local_runtime_ready=True)
    assert decision.effective_mode == IntelligenceMode.NATIVE
    assert decision.fallback_reason == "hardware_not_supported"


def test_auto_never_uses_external_ai_implicitly():
    decision = decide_route(
        snapshot(None, nvidia=False),
        IntelligenceMode.AUTO,
        local_runtime_ready=False,
        external_available=True,
    )
    assert decision.effective_mode == IntelligenceMode.NATIVE


def test_external_mode_falls_back_safely_when_unavailable():
    decision = decide_route(snapshot(6144), IntelligenceMode.EXTERNAL, external_available=False)
    assert decision.effective_mode == IntelligenceMode.NATIVE
    assert decision.fallback_reason == "external_ai_unavailable"
