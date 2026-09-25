from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute


def _closure_values(fn) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for name, cell in zip(getattr(fn.__code__, "co_freevars", ()), getattr(fn, "__closure__", None) or ()):
        try:
            values[name] = cell.cell_contents
        except ValueError:
            pass
    return values


def install_free_channel_dashboard(app: FastAPI) -> None:
    if getattr(app.state, "free_channel_dashboard_installed", False):
        return
    status_route = next(r for r in app.router.routes if isinstance(r, APIRoute) and r.path == "/api/dashboard/status")
    service_for = _closure_values(status_route.endpoint).get("service_for")
    if service_for is None:
        raise RuntimeError("Não foi possível resolver o serviço do dashboard para otimização do canal.")
    readable = status_route.dependant.dependencies[0].call

    @app.get("/api/dashboard/free/channel/optimization")
    async def free_channel_optimization(period_days: int = 28, tenant: Any = Depends(readable)) -> dict[str, Any]:
        return service_for(tenant.tenant_id).free_channel_optimization_plan(period_days=max(7, min(90, period_days)))

    app.state.free_channel_dashboard_installed = True
