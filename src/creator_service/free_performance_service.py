from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from intelligence.free_catalog_opportunities import FreeCatalogOpportunityDetector
from intelligence.free_category_classifier import FreeCategoryClassifier
from intelligence.free_plan_policy import FreePremiumPolicy
from intelligence.free_reach_reporting import YouTubeReachReporting
from intelligence.free_retention_intelligence import FreeRetentionIntelligence


def install_free_performance_service() -> None:
    from .service import CreatorService

    if getattr(CreatorService, "_yca_free_performance_installed", False):
        return

    original_status = CreatorService.status

    def status(self) -> dict[str, Any]:
        result = dict(original_status(self))
        free = dict(result.get("free_intelligence") or {})
        free.update({
            "retention_intelligence_version": FreeRetentionIntelligence.VERSION,
            "reach_reporting_version": YouTubeReachReporting.VERSION,
            "category_classifier_version": FreeCategoryClassifier.VERSION,
            "catalog_opportunity_version": FreeCatalogOpportunityDetector.VERSION,
            "plan_policy_version": FreePremiumPolicy.VERSION,
            "thumbnail_ctr_source": "youtube_reporting_api",
            "thumbnail_ctr_estimated": False,
        })
        result["free_intelligence"] = free
        return result

    def free_video_retention(self, video_id: str, *, period_days: int = 28) -> dict[str, Any]:
        self.context.validate_youtube()
        self._owned_video_item(video_id, part="id")
        _, analytics = self._clients()
        if analytics is None:
            return {"engine": FreeRetentionIntelligence.VERSION, "data_available": False, "blocked_reason": "YouTube Analytics client unavailable.", "writes_performed": 0}
        days = max(7, min(90, int(period_days)))
        now = datetime.now(timezone.utc)
        response = analytics.reports().query(
            ids="channel==MINE",
            startDate=(now - timedelta(days=days)).strftime("%Y-%m-%d"),
            endDate=now.strftime("%Y-%m-%d"),
            metrics="audienceWatchRatio,relativeRetentionPerformance",
            dimensions="elapsedVideoTimeRatio",
            filters=f"video=={video_id}",
            sort="elapsedVideoTimeRatio",
        ).execute()
        headers = [str(item.get("name") or "") for item in (response.get("columnHeaders") or [])]
        rows = []
        for raw in response.get("rows") or []:
            rows.append({headers[index]: value for index, value in enumerate(raw) if index < len(headers)})
        report = FreeRetentionIntelligence().analyze(rows)
        report.update({"video_id": str(video_id), "period_days": days})
        return report

    def free_video_reach(self, video_id: str) -> dict[str, Any]:
        self.context.validate_youtube()
        self._owned_video_item(video_id, part="id")
        return YouTubeReachReporting(str(self.context.token_file)).fetch_latest(video_id=str(video_id))

    def free_video_performance(self, video_id: str, *, period_days: int = 28) -> dict[str, Any]:
        errors = []
        try:
            retention = free_video_retention(self, video_id, period_days=period_days)
        except Exception as exc:
            retention = {"engine": FreeRetentionIntelligence.VERSION, "data_available": False, "writes_performed": 0}
            errors.append({"source": "retention", "error": str(exc)[:500]})
        try:
            reach = free_video_reach(self, video_id)
        except Exception as exc:
            reach = {"engine": YouTubeReachReporting.VERSION, "data_available": False, "writes_performed": 0}
            errors.append({"source": "reach", "error": str(exc)[:500]})
        ctr = reach.get("ctr") if reach.get("data_available") else None
        impressions = reach.get("impressions") if reach.get("data_available") else None
        packaging_status = "unknown"
        if ctr is not None and impressions is not None and int(impressions) >= 100:
            if float(ctr) < 0.025:
                packaging_status = "weak_observed_ctr"
            elif float(ctr) >= 0.06:
                packaging_status = "strong_observed_ctr"
            else:
                packaging_status = "normal_observed_ctr"
        return {
            "engine": "free-video-performance-v1",
            "video_id": str(video_id),
            "retention": retention,
            "reach": reach,
            "packaging_status": packaging_status,
            "thumbnail_recommendation": (
                "Revisar thumbnail e promessa visual; CTR oficial observado está baixo para este período." if packaging_status == "weak_observed_ctr" else
                "Preservar a thumbnail por enquanto; não há evidência oficial suficiente para recomendar troca." if packaging_status == "unknown" else
                "Acompanhar CTR e retenção antes de alterar thumbnail."
            ),
            "errors": errors,
            "uses_external_ai": False,
            "writes_performed": 0,
            "requires_explicit_user_confirmation_for_writes": True,
        }

    def free_category_suggestion(self, video_id: str, *, max_peers: int = 30) -> dict[str, Any]:
        self.context.validate_youtube()
        item = self._owned_video_item(video_id, part="snippet")
        snippet = item.get("snippet", {}) or {}
        transcript = ""
        try:
            from .dashboard_ai import youtube_transcript
            transcript = str(youtube_transcript(self._youtube(), video_id).get("text") or "")
        except Exception:
            pass
        response = self._youtube().search().list(part="id", channelId=self._authorized_channel_id(), type="video", order="date", maxResults=max(10, min(50, int(max_peers)))).execute()
        peer_ids = [str(row.get("id", {}).get("videoId") or "") for row in response.get("items") or []]
        peer_ids = [value for value in peer_ids if value and value != video_id][:max_peers]
        peers = []
        if peer_ids:
            videos = self._youtube().videos().list(part="snippet", id=",".join(peer_ids), maxResults=len(peer_ids)).execute()
            for peer in videos.get("items") or []:
                ps = peer.get("snippet", {}) or {}
                peers.append({"id": peer.get("id"), "title": ps.get("title"), "description": ps.get("description"), "categoryId": ps.get("categoryId")})
        return FreeCategoryClassifier().classify(current_category_id=str(snippet.get("categoryId") or ""), transcript=transcript, peer_videos=peers)

    def free_catalog_opportunities(self, *, period_days: int = 28, max_videos: int = 5) -> dict[str, Any]:
        profile = self.channel_profile(period_days=max(7, min(90, int(period_days))))
        candidates = [str(row.get("video_id") or "") for row in (profile.get("weak_videos") or []) if isinstance(row, dict)]
        reports = []
        errors = []
        for video_id in candidates[:max(1, min(8, int(max_videos)))]:
            if not video_id:
                continue
            try:
                report = self.free_video_intelligence(video_id, period_days=period_days, max_results=10, candidate_limit=5)
                try:
                    item = self._owned_video_item(video_id, part="snippet")
                    report.setdefault("current", {})["publishedAt"] = (item.get("snippet", {}) or {}).get("publishedAt")
                except Exception:
                    pass
                reports.append(report)
            except Exception as exc:
                errors.append({"video_id": video_id, "error": str(exc)[:500]})
        result = FreeCatalogOpportunityDetector().detect(reports)
        result.update({"period_days": period_days, "videos_considered": candidates[:max_videos], "errors": errors})
        return result

    def free_plan_route(self, action: str, *, plan: str = "free", credits: int = 0, ai_opt_in: bool = False) -> dict[str, Any]:
        return FreePremiumPolicy().decide(action=action, plan=plan, credits=credits, ai_opt_in=ai_opt_in)

    CreatorService.status = status
    CreatorService.free_video_retention = free_video_retention
    CreatorService.free_video_reach = free_video_reach
    CreatorService.free_video_performance = free_video_performance
    CreatorService.free_category_suggestion = free_category_suggestion
    CreatorService.free_catalog_opportunities = free_catalog_opportunities
    CreatorService.free_plan_route = free_plan_route
    CreatorService._yca_free_performance_installed = True
