from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from intelligence.youtube_research import YouTubeResearchEngine

from .dashboard_ai import _clean_candidates, _json_object, channel_identity


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fact_catalog(channel: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    catalog: dict[str, Any] = {
        "channel.subscribers": int(_number(channel.get("subscribers"))),
        "channel.total_views": int(_number(channel.get("total_views"))),
        "channel.video_count": int(_number(channel.get("video_count"))),
        "analytics.period_views": int(_number(channel.get("total_analytics_views"))),
        "analytics.search_views": int(_number(channel.get("search_views"))),
        "analytics.search_share": round(_number(channel.get("search_share")), 6),
    }
    top_terms = channel.get("top_search_terms") or []
    if isinstance(top_terms, list):
        for index, row in enumerate(top_terms[:8], start=1):
            if isinstance(row, dict):
                catalog[f"search.term.{index}"] = {
                    "term": str(row.get("term") or ""),
                    "views": int(_number(row.get("views"))),
                    "share_of_search_views": _number(row.get("share_of_search_views")),
                }
    if isinstance(evidence, dict):
        for key in ("inventory_scope", "public_video_count", "non_public_returned_count"):
            if key in evidence and not isinstance(evidence[key], (dict, list)):
                catalog[f"evidence.{key}"] = evidence[key]
        market = evidence.get("market_research") or {}
        rows = market.get("opportunities") if isinstance(market, dict) else []
        if isinstance(rows, list):
            for index, row in enumerate(rows[:8], start=1):
                if isinstance(row, dict):
                    catalog[f"market.keyword.{index}"] = {
                        "keyword": row.get("keyword"),
                        "opportunity_score": row.get("opportunity_score"),
                        "demand_index": row.get("demand_index"),
                        "competition_label": row.get("competition_label"),
                        "fresh_7d_rate": row.get("fresh_7d_rate"),
                        "fresh_30d_rate": row.get("fresh_30d_rate"),
                    }
    return catalog


def _clean_text(value: Any, limit: int = 1200) -> str:
    return " ".join(str(value or "").split())[:limit]


def _clean_actions(value: Any, allowed_keys: set[str], limit: int = 8) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    output: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        title = _clean_text(raw.get("title"), 180)
        action = _clean_text(raw.get("action"), 900)
        why = _clean_text(raw.get("why"), 700)
        keys = []
        for item in raw.get("evidence_keys") or []:
            key = str(item or "").strip()
            if key in allowed_keys and key not in keys:
                keys.append(key)
        if not title or not action:
            continue
        output.append({"title": title, "why": why, "action": action, "evidence_keys": keys})
        if len(output) >= limit:
            break
    return output


def grounded_topic_research(service, seed: str, *, candidate_limit: int = 8, max_age_days: int = 30) -> dict[str, Any]:
    """Generate candidate queries with AI, then score them only with real YouTube results."""
    seed = _clean_text(seed, 1000)
    if len(seed) < 2:
        raise ValueError("Informe um tema real para pesquisar.")
    limit = max(3, min(12, int(candidate_limit)))
    age = max(7, min(90, int(max_age_days)))
    channel = channel_identity(service._youtube())
    prompt = f"""Gere somente consultas de busca do YouTube coerentes com o tema e com o canal abaixo.
Não invente tendências, volumes ou números. Você só está propondo candidatos que serão medidos depois pela aplicação.
Preserve o idioma do canal ({channel.get('default_language') or 'idioma existente'}).
Retorne JSON puro {{"keyword_candidates":[...]}} com no máximo {limit} consultas naturais e específicas.
CANAL: {json.dumps(channel, ensure_ascii=False)}
TEMA: {seed}
"""
    generated = service.ai_runtime.generate(
        [{"role": "user", "content": prompt}], temperature=0.08, max_output_tokens=700, response_format="json"
    )
    candidates = _clean_candidates(_json_object(generated.text).get("keyword_candidates"))[:limit]
    if not candidates:
        raise RuntimeError("A IA não produziu candidatos de busca válidos para medir.")
    engine = YouTubeResearchEngine(str(service.context.token_file), youtube_client=service._youtube())
    rows: list[dict[str, Any]] = []
    for keyword in candidates:
        measured = engine.research(keyword, max_results=20, max_age_days=age)
        rows.append({
            "keyword": keyword,
            "opportunity_score": int(measured.opportunity.score),
            "competition_score": int(measured.opportunity.competition_score),
            "competition_label": measured.competition_label,
            "demand_index": int(measured.estimated_daily_demand_index),
            "demand_label": measured.demand_label,
            "result_count": int(measured.result_count),
            "fresh_7d_rate": measured.fresh_7d_rate,
            "fresh_30d_rate": measured.fresh_30d_rate,
            "fresh_90d_rate": measured.fresh_90d_rate,
            "median_views_per_day": measured.median_views_per_day,
            "small_channel_breakout_rate": measured.small_channel_breakout_rate,
            "evidence": [asdict(item) for item in measured.evidence[:5]],
        })
    rows.sort(key=lambda row: (row["opportunity_score"], row["demand_index"], row["median_views_per_day"]), reverse=True)
    return {
        "seed": seed,
        "measured_at_window_days": age,
        "grounded": True,
        "candidate_source": "external_ai",
        "metrics_source": "youtube_search_results",
        "opportunities": rows,
        "provider": generated.provider,
        "model": generated.model,
        "writes_performed": 0,
    }


def grounded_channel_advice(service, *, factual: dict[str, Any], purpose: str = "audit") -> dict[str, Any]:
    """Use external AI only to interpret verified facts, never to manufacture metrics."""
    channel = dict(factual.get("channel") or {})
    evidence = dict(factual.get("evidence") or {})
    catalog = _fact_catalog(channel, evidence)
    settings = service.ai_runtime.load_settings()
    if not settings.model:
        raise RuntimeError("Nenhum modelo de IA está selecionado em Ajustes.")
    channel_language = str(channel.get("default_language") or "").strip()
    prompt = f"""Você é um estrategista sênior de YouTube, mas NÃO é uma fonte de métricas.
Sua única fonte factual é o JSON FATO abaixo. Não invente números, CTR, retenção, impressões, receita, palavras-chave ou tendências ausentes.
Quando recomendar uma ação, cite apenas evidence_keys existentes na lista CHAVES_VALIDAS. Nunca escreva um valor numérico observado por conta própria; a aplicação anexará o valor real depois.
Analise SEO, descoberta por busca, desempenho do período, coerência editorial e próximos testes. Se um dado necessário não existir, diga que precisa ser medido em vez de estimá-lo.
Não recomende trocar o idioma do canal. Idioma do conteúdo: {channel_language or 'preservar o idioma existente'}.
Escreva as explicações da interface em português claro.
Retorne JSON puro com exatamente estes campos:
executive_summary (string), health ("bom"|"atenção"|"crítico"|"dados_insuficientes"),
priorities (lista de objetos title, why, action, evidence_keys),
seo_actions (mesmo formato), analytics_actions (mesmo formato), content_actions (mesmo formato),
next_7_days (lista de strings), next_30_days (lista de strings), missing_measurements (lista de strings).
PROPÓSITO: {purpose}
CHAVES_VALIDAS: {json.dumps(sorted(catalog), ensure_ascii=False)}
FATO: {json.dumps(factual, ensure_ascii=False)[:40000]}
"""
    response = service.ai_runtime.generate(
        [{"role": "user", "content": prompt}],
        temperature=0.08,
        max_output_tokens=2200,
        response_format="json",
    )
    raw = _json_object(response.text)
    allowed = set(catalog)
    health = str(raw.get("health") or "dados_insuficientes").strip().lower()
    if health not in {"bom", "atenção", "crítico", "dados_insuficientes"}:
        health = "dados_insuficientes"
    advice = {
        "status": "ready",
        "grounded": True,
        "metrics_source": "youtube_and_youtube_analytics",
        "no_invented_metrics": True,
        "executive_summary": _clean_text(raw.get("executive_summary"), 1400),
        "health": health,
        "priorities": _clean_actions(raw.get("priorities"), allowed, 6),
        "seo_actions": _clean_actions(raw.get("seo_actions"), allowed, 8),
        "analytics_actions": _clean_actions(raw.get("analytics_actions"), allowed, 8),
        "content_actions": _clean_actions(raw.get("content_actions"), allowed, 8),
        "next_7_days": [_clean_text(item, 500) for item in (raw.get("next_7_days") or []) if _clean_text(item, 500)][:8],
        "next_30_days": [_clean_text(item, 500) for item in (raw.get("next_30_days") or []) if _clean_text(item, 500)][:8],
        "missing_measurements": [_clean_text(item, 500) for item in (raw.get("missing_measurements") or []) if _clean_text(item, 500)][:8],
        "evidence_catalog": catalog,
        "provider": response.provider,
        "model": response.model,
        "channel_language": channel_language,
        "language_policy": "preserve_channel_language",
    }
    for group in ("priorities", "seo_actions", "analytics_actions", "content_actions"):
        for item in advice[group]:
            item["evidence"] = {key: catalog[key] for key in item["evidence_keys"]}
    return advice


def grounded_channel_strategy(service, *, period_days: int = 28) -> dict[str, Any]:
    days = max(7, min(90, int(period_days)))
    channel = service.channel_profile(period_days=days)
    evidence = service.strategy_evidence(period_days=days)
    identity = channel_identity(service._youtube())
    seed = " | ".join(filter(None, [str(identity.get("title") or ""), str(identity.get("description") or "")[:1200]]))
    market_error = ""
    try:
        evidence = dict(evidence or {})
        evidence["market_research"] = grounded_topic_research(service, seed or str(channel.get("channel_title") or "canal"), candidate_limit=6, max_age_days=min(30, days))
    except Exception as exc:
        market_error = _clean_text(exc, 700)
    factual = {"period_days": days, "channel": channel, "evidence": evidence}
    advice = grounded_channel_advice(service, factual=factual, purpose="channel_strategy")
    return {
        "period_days": days,
        "grounded": True,
        "facts": factual,
        "strategy": advice,
        "market_research_error": market_error,
        "requires_review": True,
        "writes_performed": 0,
    }


def install_grounded_strategy_service() -> None:
    from .service import CreatorService

    if getattr(CreatorService, "_yca_grounded_strategy_installed", False):
        return

    def build_channel_strategy(self):
        return grounded_channel_strategy(self, period_days=28)

    def research_topic(self, seed: str, candidate_limit: int = 8):
        self.context.validate_youtube()
        return grounded_topic_research(self, seed, candidate_limit=candidate_limit, max_age_days=30)

    CreatorService.build_channel_strategy = build_channel_strategy
    CreatorService.research_topic = research_topic
    CreatorService._yca_grounded_strategy_installed = True
