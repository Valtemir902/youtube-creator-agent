from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field


class AISelectionRequest(BaseModel):
    provider: str = Field(min_length=2, max_length=40)
    key_ids: list[str] = Field(min_length=1, max_length=50)
    rotation: bool = False


def _ai_write_dependency(app: FastAPI):
    for route in app.router.routes:
        if isinstance(route, APIRoute) and route.path == "/api/ai/rotation":
            dependencies = list(getattr(route.dependant, "dependencies", []) or [])
            if dependencies and callable(dependencies[0].call):
                return dependencies[0].call
    raise RuntimeError("Dependência autenticada de escrita de IA não encontrada.")


def install_ai_selection_api(app: FastAPI) -> None:
    if any(isinstance(route, APIRoute) and route.path == "/api/ai/selection" for route in app.router.routes):
        return
    from .cloud_runtime import CloudTenantResolver
    from .onboarding_service import OnboardingService

    ai_write = _ai_write_dependency(app)
    onboarding = OnboardingService(CloudTenantResolver())

    @app.put("/api/ai/selection")
    async def ai_selection(payload: AISelectionRequest, tenant: Any = Depends(ai_write)):
        try:
            runtime = onboarding._runtime(tenant.tenant_id)
            result = runtime.select_api_keys(payload.provider, payload.key_ids, rotate=payload.rotation)
            return {
                **result,
                "mode": "rotation" if payload.rotation else "single_or_manual",
                "message": (
                    f"{len(result['selected_key_ids'])} chave(s) participando da rotação."
                    if payload.rotation
                    else "Somente as chaves selecionadas ficaram habilitadas; a primeira é a chave ativa."
                ),
            }
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
