from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class AIModel:
    id: str
    name: str
    provider: str
    capabilities: tuple[str, ...] = ()
    context_window: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AIProviderConfig:
    provider: str
    api_key: str | None = None
    base_url: str | None = None
    timeout_seconds: float = 60.0
    extra_headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AIResponse:
    text: str
    model: str
    provider: str
    usage: Mapping[str, Any] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)


Message = Mapping[str, str]
Messages = Sequence[Message]
