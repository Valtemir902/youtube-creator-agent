from intelligence.free_catalog_opportunities import FreeCatalogOpportunityDetector
from intelligence.free_category_classifier import FreeCategoryClassifier
from intelligence.free_plan_policy import FreePremiumPolicy
from intelligence.free_reach_reporting import YouTubeReachReporting
from intelligence.free_retention_intelligence import FreeRetentionIntelligence


def test_reach_csv_and_weighted_ctr_are_official_only():
    csv_text = (
        "date,channel_id,video_id,video_thumbnail_impressions,video_thumbnail_impressions_ctr\n"
        "2026-09-01,c1,v1,1000,0.05\n"
        "2026-09-02,c1,v1,500,0.10\n"
        "2026-09-02,c1,v2,900,0.01\n"
    )
    rows = YouTubeReachReporting.parse_csv(csv_text)
    report = YouTubeReachReporting.summarize(rows, video_id="v1")
    assert report["source"] == "youtube_reporting_api"
    assert report["impressions"] == 1500
    assert round(report["ctr"], 4) == 0.0667
    assert round(report["ctr_percent"], 2) == 6.67
    assert report["channel_ctr_baseline"] is not None
    assert report["data_available"] is True
    assert report["writes_performed"] == 0


def test_reach_normalizes_percentage_form_without_guessing_invalid_values():
    csv_text = (
        "date,video_id,video_thumbnail_impressions,video_thumbnail_impressions_ctr\n"
        "2026-09-01,v1,1000,5\n"
        "2026-09-01,v2,1000,250\n"
    )
    rows = YouTubeReachReporting.parse_csv(csv_text)
    assert rows[0].ctr == 0.05
    assert rows[1].ctr is None
    report = YouTubeReachReporting.summarize(rows, video_id="v2")
    assert report["data_available"] is False
    assert report["ctr"] is None


def test_reach_missing_rows_are_not_estimated():
    report = YouTubeReachReporting.summarize([], video_id="v1")
    assert report["data_available"] is False
    assert report["ctr"] is None
    assert report["impressions"] == 0
    assert "never estimated" in report["methodology"]


def test_retention_detects_early_sharp_and_abandonment_drop():
    rows = [
        {"elapsedVideoTimeRatio": 0.0, "audienceWatchRatio": 1.0, "relativeRetentionPerformance": 0.5, "stoppedWatching": 10, "totalSegmentImpressions": 1000},
        {"elapsedVideoTimeRatio": 0.1, "audienceWatchRatio": 0.62, "relativeRetentionPerformance": 0.4, "stoppedWatching": 100, "totalSegmentImpressions": 900},
        {"elapsedVideoTimeRatio": 0.25, "audienceWatchRatio": 0.54, "relativeRetentionPerformance": 0.4, "stoppedWatching": 10, "totalSegmentImpressions": 800},
        {"elapsedVideoTimeRatio": 0.5, "audienceWatchRatio": 0.39, "relativeRetentionPerformance": 0.3, "stoppedWatching": 15, "totalSegmentImpressions": 700},
        {"elapsedVideoTimeRatio": 0.75, "audienceWatchRatio": 0.31, "relativeRetentionPerformance": 0.3, "stoppedWatching": 10, "totalSegmentImpressions": 600},
        {"elapsedVideoTimeRatio": 1.0, "audienceWatchRatio": 0.20, "relativeRetentionPerformance": 0.2, "stoppedWatching": 5, "totalSegmentImpressions": 500},
    ]
    report = FreeRetentionIntelligence().analyze(rows)
    codes = {item["code"] for item in report["recommendations"]}
    assert report["data_available"] is True
    assert "weak_opening_retention" in codes
    assert "sharp_retention_drop" in codes
    assert "abandonment_hotspot" in codes
    assert report["writes_performed"] == 0


def test_retention_preserves_rewatch_ratio_above_one_but_caps_score_only():
    rows = [
        {"elapsedVideoTimeRatio": 0.1, "audienceWatchRatio": 1.25, "relativeRetentionPerformance": 0.8},
        {"elapsedVideoTimeRatio": 0.25, "audienceWatchRatio": 1.05, "relativeRetentionPerformance": 0.7},
        {"elapsedVideoTimeRatio": 0.5, "audienceWatchRatio": 0.80, "relativeRetentionPerformance": 0.6},
        {"elapsedVideoTimeRatio": 0.75, "audienceWatchRatio": 0.60, "relativeRetentionPerformance": 0.5},
    ]
    report = FreeRetentionIntelligence().analyze(rows)
    assert report["checkpoints"]["10pct"]["audience_watch_ratio"] == 1.25
    assert report["retention_score"] <= 100


def test_category_classifier_requires_strong_semantic_consensus():
    transcript = "plantio milho colheita roça agricultura plantio milho colheita roça agricultura"
    peers = [{"id": f"v{i}", "title": "plantio milho roça", "description": "agricultura colheita", "categoryId": "26"} for i in range(6)]
    result = FreeCategoryClassifier().classify(current_category_id="22", transcript=transcript, peer_videos=peers)
    assert result["suggestion_ready"] is True
    assert result["suggested_category_id"] == "26"
    assert result["confidence"] >= 72
    assert result["writes_performed"] == 0


def test_category_classifier_blocks_weak_or_mixed_consensus():
    transcript = "trilha gps offline navegação aventura montanha"
    peers = [
        {"id": "a", "title": "trilha gps", "description": "aventura", "categoryId": "19"},
        {"id": "b", "title": "trilha gps", "description": "aventura", "categoryId": "22"},
        {"id": "c", "title": "trilha gps", "description": "aventura", "categoryId": "28"},
    ]
    result = FreeCategoryClassifier().classify(current_category_id="22", transcript=transcript, peer_videos=peers)
    assert result["suggestion_ready"] is False
    assert result["suggested_category_id"] == "22"


def test_free_plan_policy_falls_back_without_credits_and_unlocks_with_credits():
    policy = FreePremiumPolicy()
    free = policy.decide(action="premium_ai_rewrite", plan="free", credits=0, ai_opt_in=True)
    paid = policy.decide(action="premium_ai_rewrite", plan="free", credits=5, ai_opt_in=True)
    included = policy.decide(action="premium_ai_rewrite", plan="premium", credits=0, ai_opt_in=True)
    assert free["route"] == "deterministic_free"
    assert free["ai_allowed"] is False
    assert paid["route"] == "premium_ai_with_credits"
    assert paid["credits_required"] == 5
    assert included["route"] == "premium_ai"


def test_catalog_detector_prioritizes_measurable_gain():
    reports = [
        {"video_id": "weak", "overall_score": 40, "published_at": "2025-01-01T00:00:00Z", "current": {"title": "Antigo", "publishedAt": "2025-01-01T00:00:00Z"}, "optimization": {"optimization_ready": True, "projected_score_delta": 18}, "keyword_intelligence": {"positive_keywords": [{"decision_score": 82}]}},
        {"video_id": "strong", "overall_score": 88, "published_at": "2026-08-01T00:00:00Z", "current": {"title": "Bom", "publishedAt": "2026-08-01T00:00:00Z"}, "optimization": {"optimization_ready": False, "projected_score_delta": 0}, "keyword_intelligence": {"positive_keywords": [{"decision_score": 20}]}},
    ]
    result = FreeCatalogOpportunityDetector().detect(reports)
    assert result["opportunities"][0]["video_id"] == "weak"
    assert result["writes_performed"] == 0
