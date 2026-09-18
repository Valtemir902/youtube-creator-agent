from __future__ import annotations

from typing import Any, Callable


def preserve_channel_language(plan: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
    """Return an AI plan that can never override the channel language.

    An empty channel language is intentional: downstream video update paths then
    preserve the video's existing defaultLanguage instead of trusting a model guess.
    """
    safe = dict(plan or {})
    safe["language"] = str(channel.get("default_language") or "").strip()
    safe["language_policy"] = "preserve_channel_language"
    return safe


def install_ai_language_policy() -> None:
    """Wrap dashboard SEO generation without changing its public API contract."""
    from . import dashboard_routes

    current: Callable[..., dict[str, Any]] = dashboard_routes.grounded_seo_plan
    if getattr(current, "_yca_language_guard", False):
        return

    def guarded(service, **kwargs):
        plan = current(service, **kwargs)
        from .dashboard_ai import channel_identity

        channel = channel_identity(service._youtube())
        return preserve_channel_language(plan, channel)

    guarded._yca_language_guard = True  # type: ignore[attr-defined]
    dashboard_routes.grounded_seo_plan = guarded
