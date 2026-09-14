from __future__ import annotations

import sqlite3

from creator_service.ai_runtime_policy import install_ai_runtime_policy
from creator_service.cloud_runtime import CloudTenantResolver
from creator_service.onboarding_service import OnboardingService


def _configured_tenant_ids(resolver: CloudTenantResolver) -> list[str]:
    with sqlite3.connect(resolver.db.path) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT t.tenant_id
            FROM tenants t
            JOIN tenant_secrets s ON s.tenant_id = t.tenant_id
            WHERE t.enabled = 1
              AND (s.secret_name LIKE 'ai:%:api_key' OR s.secret_name LIKE 'ai:%:api_key:%')
            ORDER BY t.tenant_id
            """
        ).fetchall()
    return [str(row[0]) for row in rows]


def main() -> None:
    install_ai_runtime_policy()
    resolver = CloudTenantResolver()
    service = OnboardingService(resolver)
    candidates = _configured_tenant_ids(resolver)
    if not candidates:
        raise SystemExit("production_ai_smoke=no_configured_tenant")

    failures: list[str] = []
    for tenant_id in candidates:
        runtime = service._runtime(tenant_id)
        settings = runtime.load_settings()
        provider = settings.provider.strip().lower()
        model = settings.model.strip()
        if not model:
            continue
        enabled = [item for item in runtime.key_pool.list(provider) if item.enabled]
        if provider != "ollama" and not enabled and not runtime.credentials.get_key(provider):
            continue
        try:
            response = runtime.generate(
                [{"role": "user", "content": "Responda somente OK."}],
                settings=settings,
                temperature=0.0,
                max_output_tokens=8,
            )
            text = (response.text or "").strip()
            if not text:
                raise RuntimeError("resposta vazia")
            print(
                "production_ai_smoke=ok "
                f"tenant={tenant_id} provider={response.provider} model={response.model} "
                f"enabled_keys={len(enabled)} rotation={bool(runtime.key_pool.auto_rotate(provider))}"
            )
            return
        except Exception as exc:
            failures.append(f"{tenant_id}:{provider}:{model}:{type(exc).__name__}:{str(exc)[:300]}")

    if failures:
        raise SystemExit("production_ai_smoke=failed " + " | ".join(failures))
    raise SystemExit("production_ai_smoke=no_usable_configured_tenant")


if __name__ == "__main__":
    main()
