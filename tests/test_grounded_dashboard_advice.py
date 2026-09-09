from __future__ import annotations

import json
from types import SimpleNamespace

from ai.types import AIResponse
from creator_service.dashboard_ai_route_guard import _safe_ai_error
from creator_service.dashboard_grounded_advice import grounded_channel_advice


class FakeRuntime:
    def load_settings(self):
        return SimpleNamespace(model="model-x")

    def generate(self, messages, **kwargs):
        prompt = messages[0]["content"]
        assert "FATO:" in prompt
        assert "CHAVES_VALIDAS:" in prompt
        payload = {
            "executive_summary": "A busca precisa de atenção.",
            "health": "atenção",
            "priorities": [{
                "title": "Melhorar descoberta",
                "why": "A busca representa pouco do tráfego medido.",
                "action": "Priorize temas e metadados validados com pesquisas recentes.",
                "evidence_keys": ["analytics.search_share", "invented.metric"],
            }],
            "seo_actions": [],
            "analytics_actions": [],
            "content_actions": [],
            "next_7_days": ["Validar candidatos de busca antes de editar metadados."],
            "next_30_days": ["Comparar evolução da descoberta orgânica."],
            "missing_measurements": ["CTR não foi fornecido."],
        }
        return AIResponse(text=json.dumps(payload), model="model-x", provider="gemini")


class FakeService:
    ai_runtime = FakeRuntime()


def test_advice_only_attaches_server_verified_evidence_keys():
    factual = {
        "period_days": 28,
        "channel": {
            "subscribers": 82,
            "total_views": 11723,
            "video_count": 52,
            "total_analytics_views": 59,
            "search_views": 1,
            "search_share": 0.0169,
            "top_search_terms": [{"term": "deadbone", "views": 1, "share_of_search_views": 1.0}],
        },
        "evidence": {},
    }

    advice = grounded_channel_advice(FakeService(), factual=factual)

    assert advice["grounded"] is True
    assert advice["no_invented_metrics"] is True
    assert advice["priorities"][0]["evidence_keys"] == ["analytics.search_share"]
    assert advice["priorities"][0]["evidence"] == {"analytics.search_share": 0.0169}
    assert "invented.metric" not in advice["evidence_catalog"]


def test_provider_failures_are_explained_without_raw_http_500():
    assert "limite" in _safe_ai_error(RuntimeError("429 RESOURCE_EXHAUSTED quota")).lower()
    assert "temporariamente" in _safe_ai_error(RuntimeError("503 UNAVAILABLE")).lower()
    assert "recusada" in _safe_ai_error(RuntimeError("403 invalid api key")).lower()
