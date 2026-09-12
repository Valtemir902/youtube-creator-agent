from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .capability import CapabilityProfile


@dataclass(frozen=True)
class LocalAIModel:
    profile: CapabilityProfile
    ollama_model: str
    display_name: str
    min_vram_mb: int
    min_ram_mb: int
    context_tokens: int
    purpose: str


DEFAULT_MANIFEST: Final[dict[CapabilityProfile, LocalAIModel]] = {
    CapabilityProfile.LOCAL_LITE: LocalAIModel(
        profile=CapabilityProfile.LOCAL_LITE,
        ollama_model="qwen2.5:0.5b",
        display_name="Qwen 2.5 0.5B Local Lite",
        min_vram_mb=2048,
        min_ram_mb=6144,
        context_tokens=4096,
        purpose="reescrita curta, resumo e classificação",
    ),
    CapabilityProfile.LOCAL_STANDARD: LocalAIModel(
        profile=CapabilityProfile.LOCAL_STANDARD,
        ollama_model="qwen2.5:3b",
        display_name="Qwen 2.5 3B Local Standard",
        min_vram_mb=4096,
        min_ram_mb=8192,
        context_tokens=8192,
        purpose="SEO assistido, títulos, descrições e interpretação de evidências",
    ),
    CapabilityProfile.LOCAL_PRO: LocalAIModel(
        profile=CapabilityProfile.LOCAL_PRO,
        ollama_model="qwen2.5:7b",
        display_name="Qwen 2.5 7B Local Pro",
        min_vram_mb=8192,
        min_ram_mb=16384,
        context_tokens=8192,
        purpose="análises locais mais profundas com contexto ampliado",
    ),
}


def model_for_profile(profile: CapabilityProfile) -> LocalAIModel | None:
    return DEFAULT_MANIFEST.get(profile)
