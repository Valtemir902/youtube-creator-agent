from __future__ import annotations

from typing import Any

from .settings import AISettings


def inspect_key_and_model(
    runtime: Any,
    provider: str,
    key_id: str,
    *,
    model: str = "",
    base_url: str = "",
) -> dict[str, Any]:
    """Discover models first and preserve that list even if the model smoke test fails.

    This deliberately separates credential/model discovery from execution health. A
    provider can successfully list many models while one selected model is overloaded
    or temporarily unavailable. The UI must still receive the discovered model list so
    the user can immediately select another model.
    """
    settings = AISettings(provider=provider, model=model, base_url=base_url)
    models = runtime.list_models(settings, key_id=key_id)
    model_ids = [item.id for item in models]
    selected_model = (model or "").strip()

    if not selected_model:
        return {
            "ok": True,
            "models": model_ids,
            "count": len(model_ids),
            "tested_model": "",
            "model_test_ok": None,
            "model_test_error": "",
        }

    try:
        # test_api_key performs the real provider smoke test and updates per-key
        # health metadata. It currently performs its own model availability check;
        # we intentionally preserve the discovery result above if that step fails.
        result = runtime.test_api_key(
            provider,
            key_id,
            model=selected_model,
            base_url=base_url,
        )
        return {
            **result,
            "models": model_ids,
            "count": len(model_ids),
            "model_test_ok": True,
            "model_test_error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "models": model_ids,
            "count": len(model_ids),
            "tested_model": selected_model,
            "model_test_ok": False,
            "model_test_error": str(exc),
        }
