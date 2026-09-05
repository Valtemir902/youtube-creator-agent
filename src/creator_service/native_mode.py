from __future__ import annotations

from dataclasses import asdict
from typing import Any


def _dedupe_keywords(keywords: list[str], limit: int = 20) -> list[str]:
    clean: list[str] = []
    seen: set[str] = set()
    for raw in keywords:
        value = " ".join(str(raw).strip().split())
        if len(value) < 2:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        clean.append(value)
        if len(clean) >= limit:
            break
    if not clean:
        raise ValueError("Informe pelo menos uma palavra-chave válida.")
    return clean


def _recommended_format(shorts_share: float, long_share: float) -> str:
    if shorts_share >= 0.65:
        return "short"
    if long_share >= 0.65:
        return "long"
    return "mixed"


class ChatGPTNativeEvidenceEngine:
    """Evidence-only YouTube intelligence for ChatGPT/App/MCP mode.

    This engine intentionally does not call an LLM. The calling ChatGPT model is
    responsible for ideation, interpretation, titles and strategy. This service
    only returns measured/derived YouTube evidence and deterministic scores.
    """

    def __init__(self, context):
        self.context = context

    def _clients(self):
        self.context.validate_youtube()
        youtube, analytics = self.context.google_clients()
        if youtube is None or analytics is None:
            raise RuntimeError("Clientes autenticados do YouTube/Analytics não estão disponíveis.")
        return youtube, analytics

    def capabilities(self) -> dict[str, Any]:
        return {
            "intelligence_mode": "chatgpt_native",
            "external_ai_required": False,
            "external_ai_optional": True,
            "llm_responsibility": [
                "generate_keyword_candidates",
                "interpret_evidence",
                "draft_titles",
                "draft_descriptions",
                "build_content_strategy",
                "combine_other_authorized_apps_when_available",
            ],
            "backend_responsibility": [
                "youtube_channel_metrics",
                "youtube_analytics_evidence",
                "keyword_result_validation",
                "deterministic_opportunity_metrics",
                "channel_fit_signals",
                "safe_preview_and_write_operations",
            ],
            "guardrails": {
                "exact_search_volume_available": False,
                "daily_demand_is_estimated_index": True,
                "writes_require_signed_preview": True,
                "writes_require_explicit_confirmation": True,
            },
        }

    def strategy_evidence(self, period_days: int = 28) -> dict[str, Any]:
        from intelligence.channel_learning import ChannelLearningEngine

        youtube, analytics = self._clients()
        days = max(7, min(90, int(period_days)))
        profile = ChannelLearningEngine(
            str(self.context.token_file),
            youtube_client=youtube,
            analytics_client=analytics,
        ).collect(period_days=days, max_videos=50)
        return {
            "measured_at": profile.measured_at,
            "period_days": profile.period_days,
            "channel": {
                "id": profile.channel_id,
                "title": profile.channel_title,
                "subscribers": profile.subscribers,
                "total_views": profile.total_views,
                "video_count": profile.video_count,
            },
            "traffic": {
                "search_views": profile.search_views,
                "total_analytics_views": profile.total_analytics_views,
                "search_share": profile.search_share,
            },
            "format": {
                "shorts_share_of_recent_views": profile.shorts_share_of_recent_views,
                "long_share_of_recent_views": profile.long_share_of_recent_views,
                "recommended_default": _recommended_format(
                    profile.shorts_share_of_recent_views,
                    profile.long_share_of_recent_views,
                ),
            },
            "real_search_terms": [asdict(item) for item in profile.top_search_terms],
            "top_videos": [asdict(item) for item in profile.top_videos],
            "weak_videos": [asdict(item) for item in profile.weak_videos],
            "topic_terms": list(profile.topic_terms),
            "methodology": (
                "Measured YouTube Data API + YouTube Analytics evidence. No external LLM was called. "
                "The calling ChatGPT model should interpret these facts and may combine other authorized apps."
            ),
        }

    def validate_keywords(
        self,
        keywords: list[str],
        *,
        period_days: int = 28,
        max_results: int = 25,
    ) -> dict[str, Any]:
        from intelligence.channel_learning import ChannelLearningEngine
        from intelligence.youtube_research import YouTubeResearchEngine

        clean = _dedupe_keywords(keywords)
        youtube, analytics = self._clients()
        days = max(7, min(90, int(period_days)))
        results_per_keyword = max(5, min(50, int(max_results)))

        profile = ChannelLearningEngine(
            str(self.context.token_file),
            youtube_client=youtube,
            analytics_client=analytics,
        ).collect(period_days=days, max_videos=50)
        research = YouTubeResearchEngine(
            str(self.context.token_file),
            youtube_client=youtube,
        )

        rows: list[dict[str, Any]] = []
        for keyword in clean:
            measured = research.research(keyword, max_results=results_per_keyword)
            fit = profile.channel_fit(keyword)
            market_score = int(measured.opportunity.score)
            personalized_score = round(market_score * 0.80 + fit * 100 * 0.20)
            rows.append({
                "keyword": keyword,
                "market_opportunity_score": market_score,
                "personalized_opportunity_score": personalized_score,
                "channel_fit": round(fit * 100),
                "confidence": int(measured.opportunity.confidence),
                "demand_index": measured.estimated_daily_demand_index,
                "demand_label": measured.demand_label,
                "competition_score": int(measured.opportunity.competition_score),
                "competition_label": measured.competition_label,
                "result_count": measured.result_count,
                "median_views": measured.median_views,
                "median_views_per_day": measured.median_views_per_day,
                "p75_views_per_day": measured.p75_views_per_day,
                "median_channel_subscribers": measured.median_channel_subscribers,
                "fresh_7d_rate": measured.fresh_7d_rate,
                "fresh_30d_rate": measured.fresh_30d_rate,
                "fresh_90d_rate": measured.fresh_90d_rate,
                "small_channel_breakout_rate": measured.small_channel_breakout_rate,
                "dominant_channel_rate": measured.dominant_channel_rate,
                "exact_title_match_rate": measured.exact_title_match_rate,
                "recommended_format": _recommended_format(
                    profile.shorts_share_of_recent_views,
                    profile.long_share_of_recent_views,
                ),
                "evidence": [asdict(item) for item in measured.evidence[:10]],
                "methodology": measured.methodology,
            })

        rows.sort(
            key=lambda item: (
                item["personalized_opportunity_score"],
                item["confidence"],
                item["demand_index"],
            ),
            reverse=True,
        )
        return {
            "mode": "chatgpt_native",
            "external_ai_called": False,
            "measured_at": rows[0]["evidence"][0]["published_at"] if rows and rows[0]["evidence"] else None,
            "period_days": days,
            "keywords_evaluated": len(rows),
            "results": rows,
            "important_note": (
                "Demand index is not exact daily search volume. YouTube's public API does not expose exact arbitrary keyword search counts."
            ),
        }
