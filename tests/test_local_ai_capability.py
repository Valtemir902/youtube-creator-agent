from src.local_ai.capability import CapabilityProfile, HardwareSnapshot, classify_hardware
from src.local_ai.manifest import model_for_profile


def hw(*, vram: int | None, ram: int = 16384, cpu: int = 8, nvidia: bool = True) -> HardwareSnapshot:
    return HardwareSnapshot(
        os_name="Windows",
        architecture="AMD64",
        cpu_count=cpu,
        ram_mb=ram,
        gpu_name="NVIDIA Test GPU" if nvidia else None,
        vram_mb=vram,
        nvidia_available=nvidia,
        ollama_available=False,
    )


def test_no_supported_gpu_falls_back_to_native():
    assert classify_hardware(hw(vram=None, nvidia=False)) == CapabilityProfile.NATIVE_ONLY


def test_two_gb_gpu_selects_lite_when_system_ram_is_sufficient():
    assert classify_hardware(hw(vram=2048, ram=8192, cpu=4)) == CapabilityProfile.LOCAL_LITE
    assert model_for_profile(CapabilityProfile.LOCAL_LITE).ollama_model == "qwen2.5:0.5b"


def test_rtx_3050_six_gb_classifies_as_standard():
    profile = classify_hardware(hw(vram=6144, ram=16384, cpu=8))
    assert profile == CapabilityProfile.LOCAL_STANDARD
    assert model_for_profile(profile).ollama_model == "qwen2.5:3b"


def test_eight_gb_gpu_with_good_host_selects_pro():
    assert classify_hardware(hw(vram=8192, ram=32768, cpu=12)) == CapabilityProfile.LOCAL_PRO


def test_vram_alone_does_not_override_low_host_ram():
    assert classify_hardware(hw(vram=8192, ram=4096, cpu=8)) == CapabilityProfile.NATIVE_ONLY
