from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .capability import CapabilityProfile, HardwareSnapshot, classify_hardware
from .manifest import LocalAIModel, model_for_profile


class IntelligenceMode(str, Enum):
    NATIVE = "native"
    LOCAL = "local"
    EXTERNAL = "external"
    AUTO = "auto"


@dataclass(frozen=True)
class RouteDecision:
    requested_mode: IntelligenceMode
    effective_mode: IntelligenceMode
    profile: CapabilityProfile
    model: LocalAIModel | None
    fallback_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_mode": self.requested_mode.value,
            "effective_mode": self.effective_mode.value,
            "profile": self.profile.value,
            "model": None
            if self.model is None
            else {
                "id": self.model.ollama_model,
                "name": self.model.display_name,
                "context_tokens": self.model.context_tokens,
                "purpose": self.model.purpose,
            },
            "fallback_reason": self.fallback_reason,
        }


def decide_route(
    snapshot: HardwareSnapshot,
    requested_mode: IntelligenceMode = IntelligenceMode.AUTO,
    *,
    local_runtime_ready: bool = False,
    external_available: bool = False,
) -> RouteDecision:
    profile = classify_hardware(snapshot)
    model = model_for_profile(profile)

    if requested_mode == IntelligenceMode.NATIVE:
        return RouteDecision(requested_mode, IntelligenceMode.NATIVE, profile, model, None)

    if requested_mode == IntelligenceMode.EXTERNAL:
        if external_available:
            return RouteDecision(requested_mode, IntelligenceMode.EXTERNAL, profile, model, None)
        return RouteDecision(
            requested_mode,
            IntelligenceMode.NATIVE,
            profile,
            model,
            "external_ai_unavailable",
        )

    if requested_mode == IntelligenceMode.LOCAL:
        if profile == CapabilityProfile.NATIVE_ONLY:
            return RouteDecision(
                requested_mode,
                IntelligenceMode.NATIVE,
                profile,
                None,
                "hardware_not_supported",
            )
        if not local_runtime_ready:
            return RouteDecision(
                requested_mode,
                IntelligenceMode.NATIVE,
                profile,
                model,
                "local_runtime_not_ready",
            )
        return RouteDecision(requested_mode, IntelligenceMode.LOCAL, profile, model, None)

    # AUTO never calls a paid/external API behind the user's back. Local is
    # preferred only when the device has been proven capable and provisioned.
    if profile != CapabilityProfile.NATIVE_ONLY and local_runtime_ready:
        return RouteDecision(requested_mode, IntelligenceMode.LOCAL, profile, model, None)
    reason = "hardware_not_supported" if profile == CapabilityProfile.NATIVE_ONLY else "local_runtime_not_ready"
    return RouteDecision(requested_mode, IntelligenceMode.NATIVE, profile, model, reason)
