from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class CreatorContext:
    tenant_id: str
    token_file: Path
    ai_settings_file: Path
    data_dir: Path
    credential_store: Any | None = None
    google_client_factory: Callable[[], tuple[Any, Any]] | None = None
    youtube_connected_override: bool | None = None

    @property
    def youtube_connected(self) -> bool:
        if self.youtube_connected_override is not None:
            return bool(self.youtube_connected_override)
        return self.token_file.exists()

    def validate_readiness(self) -> None:
        if not self.youtube_connected:
            raise RuntimeError("Canal do YouTube não conectado para este cliente.")
        if not self.ai_settings_file.exists():
            raise RuntimeError("Configuração de IA ainda não criada para este cliente.")

    def google_clients(self):
        if self.google_client_factory is None:
            return None, None
        return self.google_client_factory()


class LocalTenantResolver:
    """Desktop/development resolver preserving the current local behavior."""

    def __init__(self, root: str | Path | None = None):
        if root is None:
            root = os.environ.get("YCA_ROOT")
        if root is None:
            root = Path(__file__).resolve().parents[2]
        self.root = Path(root).resolve()

    def resolve(self, tenant_id: str = "local") -> CreatorContext:
        tenant_id = (tenant_id or "local").strip()
        if tenant_id != "local":
            raise RuntimeError("O resolvedor local aceita apenas o tenant 'local'.")
        config = self.root / "config"
        data = self.root / "data"
        data.mkdir(parents=True, exist_ok=True)
        return CreatorContext(
            tenant_id="local",
            token_file=config / "token.json",
            ai_settings_file=config / "ai_settings.json",
            data_dir=data,
        )
