from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CreatorContext:
    tenant_id: str
    token_file: Path
    ai_settings_file: Path
    data_dir: Path

    def validate_readiness(self) -> None:
        if not self.token_file.exists():
            raise RuntimeError("Canal do YouTube não conectado para este cliente.")
        if not self.ai_settings_file.exists():
            raise RuntimeError("Configuração de IA ainda não criada para este cliente.")


class LocalTenantResolver:
    """Development/single-user context resolver.

    Production will replace this resolver with an authenticated account lookup.
    The service layer deliberately does not know where tokens are physically
    stored beyond the context it receives.
    """

    def __init__(self, root: str | Path | None = None):
        if root is None:
            root = os.environ.get("YCA_ROOT")
        if root is None:
            root = Path(__file__).resolve().parents[2]
        self.root = Path(root).resolve()

    def resolve(self, tenant_id: str = "local") -> CreatorContext:
        tenant_id = (tenant_id or "local").strip()
        if tenant_id != "local":
            raise RuntimeError(
                "Esta build usa o resolver local. Multiusuário exige o backend autenticado."
            )
        config = self.root / "config"
        data = self.root / "data"
        data.mkdir(parents=True, exist_ok=True)
        return CreatorContext(
            tenant_id="local",
            token_file=config / "token.json",
            ai_settings_file=config / "ai_settings.json",
            data_dir=data,
        )
