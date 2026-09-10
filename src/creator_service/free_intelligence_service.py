from __future__ import annotations

from collections import Counter
from typing import Any

from intelligence.free_growth_engine import FreeGrowthEngine, _tokens
from intelligence.free_video_optimizer import FreeVideoOptimizer


def _candidate_keywords(title: str, transcript: str, *, limit: int = 8) -> list[str]:
    title = " ".join(str(title or "").split())
    tokens = _tokens(transcript)
    counts = Counter(tokens)
    top = [token for token, count in counts.most_common(24) if count >= 2]
    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        value = " ".join(str(value or "").split()).strip()
        if len(value) < 3:
            return
        key = value.casefold()
        if key in seen:
            return
        seen.add(key)
        candidates.append(value[:100])

    add(title[:90])
    for size in (3, 2):
        for index in range(max(0, len(tokens) - size + 1)):
            chunk = tokens[index:index + size]
            if not all(token in top for token in chunk):
                continue
            add(" ".join(chunk))
            if len(candidates) >= limit:
                return candidates[:limit]
    for token in top:
        add(token)
        if len(candidates) >= limit:
            break
    return candidates[:limit]


def install_free_intelligence_service() -> None:
    from .dashboard_ai import youtube_transcript
    from .service import CreatorService

    if getattr(CreatorService, "_yca_free_intelligence_installed", False):
        return

    original_status = CreatorService.status

    def status(self) -> dict[str, Any]:
        result = dict(original_status(self))
        result["free_intelligence"] = {
            "available": True,
            "version": FreeGrowthEngine.VERSION,
            "video_optimizer_version": FreeVideoOptimizer.VERSION,
            "external_ai_required": False,
            "automatic_writes": False,
            "evidence_first": True,
            "optimization_requires_transcript_and_measured_search": True,
        }
        return result

    def free_channel_intelligence(self, period_days: int = 28) -> dict[str, Any]:
        days = max(7, min(90, int(period_days)))
        profile = self.channel_profile(period_days=days)
        report = FreeGrowthEngine().channel_report(profile, {})
        report["plan_tier"] = "free"
        report["premium_ai_required"] = False
        return report

    def free_video_intelligence(
        self,
        video_id: str,
        *,
        period_days: int = 28,
        max_results: int = 20,
        candidate_limit: int = 8,
    ) -> dict[str, Any]:
        self.context.validate_youtube()
        current = self._current_video_snippet(video_id)
        transcript_payload = youtube_transcript(self._youtube(), video_id)
        transcript = str(transcript_payload.get("text") or "")
        candidates = _candidate_keywords(current.get("title", ""), transcript, limit=max(3, min(12, candidate_limit)))
        keyword_rows: list[dict[str, Any]] = []
        keyword_error = ""
        if transcript and candidates:
            try:
                validation = self.validate_keyword_candidates(
                    candidates,
                    period_days=max(7, min(90, int(period_days))),
                    max_results=max(5, min(25, int(max_results))),
                )
                for row in validation.get("results") or []:
                    if not isinstance(row, dict):
                        continue
                    keyword_rows.append({
                        "keyword": row.get("keyword"),
                        "opportunity_score": row.get("personalized_opportunity_score", row.get("market_opportunity_score", 0)),
                        "market_opportunity_score": row.get("market_opportunity_score"),
                        "channel_fit": row.get("channel_fit"),
                        "confidence": row.get("confidence"),
                        "demand_index": row.get("demand_index"),
                        "demand_label": row.get("demand_label"),
                        "competition_score": row.get("competition_score"),
                        "competition_label": row.get("competition_label"),
                        "fresh_7d_rate": row.get("fresh_7d_rate"),
                        "fresh_30d_rate": row.get("fresh_30d_rate"),
                        "fresh_90d_rate": row.get("fresh_90d_rate"),
                        "median_views_per_day": row.get("median_views_per_day"),
                        "small_channel_breakout_rate": row.get("small_channel_breakout_rate"),
                        "evidence": list(row.get("evidence") or [])[:5],
                    })
            except Exception as exc:
                keyword_error = str(exc)[:700]
        report = FreeGrowthEngine().video_report(current, transcript=transcript, keyword_results=keyword_rows)
        optimization = FreeVideoOptimizer().build(current, transcript=transcript, keyword_results=keyword_rows)
        report.update({
            "video_id": str(video_id),
            "plan_tier": "free",
            "premium_ai_required": False,
            "candidate_source": "deterministic_transcript_terms" if transcript else "none_without_transcript",
            "keyword_metrics_source": "youtube_search_results" if keyword_rows else "not_measured",
            "candidate_keywords": candidates if transcript else [],
            "keyword_research_error": keyword_error,
            "transcript": {key: value for key, value in transcript_payload.items() if key != "text"},
            "current": current,
            "optimization": optimization,
        })
        return report

    def free_video_optimization_plan(
        self,
        video_id: str,
        *,
        period_days: int = 28,
        max_results: int = 20,
        candidate_limit: int = 8,
    ) -> dict[str, Any]:
        report = free_video_intelligence(
            self,
            video_id,
            period_days=period_days,
            max_results=max_results,
            candidate_limit=candidate_limit,
        )
        plan = dict(report.get("optimization") or {})
        plan["video_id"] = str(video_id)
        plan["plan_tier"] = "free"
        plan["premium_ai_required"] = False
        plan["keyword_research_error"] = report.get("keyword_research_error", "")
        plan["transcript"] = report.get("transcript", {})
        return plan

    def free_channel_strategy(self, period_days: int = 28) -> dict[str, Any]:
        report = free_channel_intelligence(self, period_days=period_days)
        priorities = list(report.get("recommendations") or [])
        return {
            "engine": FreeGrowthEngine.VERSION,
            "mode": "deterministic_free",
            "uses_external_ai": False,
            "writes_performed": 0,
            "period_days": max(7, min(90, int(period_days))),
            "health": {"score": report.get("overall_score"), "grade": report.get("grade"), "confidence": report.get("confidence")},
            "priorities": priorities[:6],
            "next_actions": [item.get("action") for item in priorities[:6] if item.get("action")],
            "facts": report.get("facts"),
            "scores": report.get("scores"),
            "methodology": report.get("methodology"),
            "requires_review": True,
        }

    CreatorService.status = status
    CreatorService.free_channel_intelligence = free_channel_intelligence
    CreatorService.free_video_intelligence = free_video_intelligence
    CreatorService.free_video_optimization_plan = free_video_optimization_plan
    CreatorService.free_channel_strategy = free_channel_strategy
    CreatorService._yca_free_intelligence_installed = True
