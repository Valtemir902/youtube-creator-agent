from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from urllib.parse import urlparse


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _is_https_url(value: str) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


@dataclass(frozen=True)
class PublicationMetadata:
    name: str
    short_description: str
    public_url: str
    mcp_url: str
    onboarding_url: str
    privacy_url: str
    terms_url: str
    support_url: str
    version: str = "13.0.0"

    def public_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ReadinessReport:
    ready: bool
    checks: dict[str, bool]
    missing: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "ready": self.ready,
            "checks": dict(self.checks),
            "missing": list(self.missing),
        }


def publication_metadata_from_env() -> PublicationMetadata:
    return PublicationMetadata(
        name=_env("YCA_APP_NAME", "YouTube Creator Agent"),
        short_description=_env(
            "YCA_APP_DESCRIPTION",
            "Analisa dados reais do YouTube, valida oportunidades e aplica alterações aprovadas no canal.",
        ),
        public_url=_env("YCA_APP_PUBLIC_URL"),
        mcp_url=_env("YCA_MCP_PUBLIC_URL"),
        onboarding_url=_env("YCA_ONBOARDING_PUBLIC_URL"),
        privacy_url=_env("YCA_PRIVACY_URL"),
        terms_url=_env("YCA_TERMS_URL"),
        support_url=_env("YCA_SUPPORT_URL"),
    )


def publication_readiness(metadata: PublicationMetadata | None = None) -> ReadinessReport:
    metadata = metadata or publication_metadata_from_env()
    checks = {
        "app_public_url_https": _is_https_url(metadata.public_url),
        "mcp_public_url_https": _is_https_url(metadata.mcp_url),
        "onboarding_public_url_https": _is_https_url(metadata.onboarding_url),
        "privacy_url_https": _is_https_url(metadata.privacy_url),
        "terms_url_https": _is_https_url(metadata.terms_url),
        "support_url_https": _is_https_url(metadata.support_url),
        "approval_secret_configured": len(_env("YCA_APPROVAL_SECRET")) >= 24,
        "data_encryption_key_configured": bool(_env("YCA_DATA_ENCRYPTION_KEY")),
        "auth_issuer_configured": _is_https_url(_env("YCA_AUTH_ISSUER_URL")),
        "auth_introspection_configured": _is_https_url(_env("YCA_AUTH_INTROSPECTION_URL")),
        "google_oauth_client_configured": bool(
            _env("GOOGLE_OAUTH_CLIENT_ID")
            and _env("GOOGLE_OAUTH_CLIENT_SECRET")
            and _is_https_url(_env("GOOGLE_OAUTH_REDIRECT_URI"))
        ),
    }
    missing = tuple(name for name, ok in checks.items() if not ok)
    return ReadinessReport(ready=not missing, checks=checks, missing=missing)
