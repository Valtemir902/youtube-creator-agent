from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .capability import CapabilityProfile


MANIFEST_VERSION: Final[str] = "2026.09.1"


@dataclass(frozen=True)
class LocalAIModel:
    profile: CapabilityProfile
    ollama_model: str
    display_name: str
    min_vram_mb: int
    min_ram_mb: int
    context_tokens: int
    purpose: str
    license_name: str
    estimated_download_mb: int
    recommended_free_disk_mb: int


DEFAULT_MANIFEST: Final[dict[CapabilityProfile, LocalAIModel]] = {
    CapabilityProfile.LOCAL_LITE: LocalAIModel(
        profile=CapabilityProfile.LOCAL_LITE,
        ollama_model="qwen2.5:0.5b",
        display_name="Qwen 2.5 0.5B Local Lite",
        min_vram_mb=2048,
        min_ram_mb=6144,
        context_tokens=4096,
        purpose="reescrita curta, resumo e classificação",
        license_name="Apache-2.0",
        estimated_download_mb=400,
        recommended_free_disk_mb=1200,
    ),
    CapabilityProfile.LOCAL_STANDARD: LocalAIModel(
        profile=CapabilityProfile.LOCAL_STANDARD,
        ollama_model="qwen2.5:1.5b",
        display_name="Qwen 2.5 1.5B Local Standard",
        min_vram_mb=4096,
        min_ram_mb=8192,
        context_tokens=8192,
        purpose="SEO assistido, títulos, descrições e interpretação de evidências",
        license_name="Apache-2.0",
        estimated_download_mb=1000,
        recommended_free_disk_mb=2500,
    ),
    CapabilityProfile.LOCAL_PRO: LocalAIModel(
        profile=CapabilityProfile.LOCAL_PRO,
        ollama_model="qwen2.5:7b",
        display_name="Qwen 2.5 7B Local Pro",
        min_vram_mb=8192,
        min_ram_mb=16384,
        context_tokens=8192,
        purpose="análises locais mais profundas com contexto ampliado",
        license_name="Apache-2.0",
        estimated_download_mb=4700,
        recommended_free_disk_mb=7500,
    ),
}


def model_for_profile(profile: CapabilityProfile) -> LocalAIModel | None:
    return DEFAULT_MANIFEST.get(profile)
