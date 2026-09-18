"""Adaptive local-AI runtime for YouTube Creator Agent.

The local model is an optional language/reasoning layer. Deterministic native
intelligence remains the source of factual YouTube/Analytics evidence.
"""

from .capability import CapabilityProfile, HardwareSnapshot, classify_hardware, probe_hardware
from .manifest import DEFAULT_MANIFEST, LocalAIModel, model_for_profile

__all__ = [
    "CapabilityProfile",
    "HardwareSnapshot",
    "LocalAIModel",
    "DEFAULT_MANIFEST",
    "classify_hardware",
    "model_for_profile",
    "probe_hardware",
]
