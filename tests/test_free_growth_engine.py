from __future__ import annotations

from intelligence.free_growth_engine import FreeGrowthEngine


def test_channel_report_is_grounded_and_llm_free():
    engine = FreeGrowthEngine()
    report = engine.channel_report(
        {
            "period_days": 28,
            "subscribers": 82,
            "video_count": 25,
            "total_analytics_views": 1000,
            "search_views": 10,
            "search_share": 0.01,
            "top_search_terms": [{"term": "vida na roça", "views": 8}],
            "topic_terms": ["roça", "fazenda"],
            "top_videos": [{"video_id": "v1", "engagement_rate_28d": 0.02, "velocity_28d": 30}],
            "weak_videos": [{"video_id": "v2", "title": "Fraco"}],
        },
        {},
    )
    assert report["engine"] == "free-growth-v1"
    assert report["uses_external_ai"] is False
    assert report["grounded"] is True
    assert report["writes_performed"] == 0
    assert 0 <= report["overall_score"] <= 100
    codes = {item["code"] for item in report["recommendations"]}
    assert "low_search_share" in codes
    assert "weak_video_cluster" in codes
    assert report["recommendations"][0]["evidence"]


def test_video_report_requires_transcript_before_confident_seo_changes():
    engine = FreeGrowthEngine()
    report = engine.video_report(
        {"title": "Meu vídeo", "description": "curta", "tags": ["teste"]},
        transcript="",
        keyword_results=[],
    )
    assert report["uses_external_ai"] is False
    assert report["content_evidence"]["transcript_available"] is False
    assert report["confidence"] < 80
    codes = {item["code"] for item in report["recommendations"]}
    assert "missing_transcript" in codes


def test_video_report_uses_transcript_and_measured_keyword_evidence():
    engine = FreeGrowthEngine()
    transcript = (
        "plantação café colheita café roça produtividade café adubação plantação "
        "colheita manual fazenda café qualidade grão"
    )
    report = engine.video_report(
        {
            "title": "Colheita de café na roça",
            "description": "Mostramos a colheita de café, a plantação e o trabalho na fazenda.",
            "tags": ["colheita de café", "plantação de café", "roça"],
        },
        transcript=transcript,
        keyword_results=[
            {
                "keyword": "colheita de café",
                "opportunity_score": 82,
                "demand_index": 75,
                "competition_label": "média",
                "fresh_7d_rate": 0.5,
            },
            {
                "keyword": "plantação de café",
                "opportunity_score": 68,
                "demand_index": 60,
                "competition_label": "baixa",
                "fresh_7d_rate": 0.4,
            },
        ],
    )
    assert report["confidence"] == 95
    assert report["scores"]["measured_keyword_opportunity"] == 75
    assert report["keyword_evidence"][0]["keyword"] == "colheita de café"
    assert all("evidence" in item for item in report["recommendations"])


def test_scores_are_deterministic_for_same_input():
    engine = FreeGrowthEngine()
    current = {"title": "Como plantar café", "description": "Guia para plantar café na roça.", "tags": ["café"]}
    transcript = "plantar café roça muda café solo adubo café plantação"
    first = engine.video_report(current, transcript=transcript)
    second = engine.video_report(current, transcript=transcript)
    assert first == second
