from __future__ import annotations

from intelligence.free_action_planner import FreeActionPlanner
from intelligence.free_playlist_matcher import FreePlaylistMatcher


def test_playlist_matcher_requires_real_content_overlap():
    matcher = FreePlaylistMatcher()
    result = matcher.match(
        title="Pescaria de tucunaré no rio",
        transcript=("pescaria tucunaré rio barco isca peixe " * 30),
        playlists=[
            {"id": "p1", "title": "Pescaria e Tucunaré", "description": "Vídeos de pesca no rio", "count": 5, "privacy_status": "public"},
            {"id": "p2", "title": "Receitas de bolo", "description": "Cozinha e sobremesas", "count": 8, "privacy_status": "public"},
        ],
    )
    assert result["recommendation_ready"] is True
    assert result["recommended_playlist"]["playlist_id"] == "p1"
    assert all(row["playlist_id"] != "p2" for row in result["candidates"])
    assert result["writes_performed"] == 0


def test_playlist_matcher_refuses_weak_match():
    result = FreePlaylistMatcher().match(
        title="Pescaria no rio",
        transcript=("pescaria peixe barco rio " * 20),
        playlists=[{"id": "p1", "title": "Tecnologia e celulares", "description": "Android e aplicativos"}],
    )
    assert result["recommended_playlist"] is None
    assert result["recommendation_ready"] is False


def test_action_planner_prioritizes_ready_low_score_video():
    channel = {
        "recommendations": [
            {
                "code": "low_search_share",
                "priority": "alta",
                "title": "Aumentar busca",
                "action": "Revisar metadata",
                "why": "Busca baixa",
                "evidence": {"search_share": 0.02},
                "confidence": 90,
                "estimated_impact": "alto",
            }
        ]
    }
    videos = [
        {
            "video_id": "v1",
            "overall_score": 32,
            "confidence": 90,
            "optimization": {
                "optimization_ready": True,
                "projected_score": 61,
                "projected_score_delta": 29,
                "confidence": 92,
                "target_keywords": ["pescaria tucunaré"],
            },
        },
        {
            "video_id": "v2",
            "overall_score": 85,
            "confidence": 80,
            "optimization": {
                "optimization_ready": False,
                "projected_score": 85,
                "projected_score_delta": 0,
                "confidence": 80,
                "target_keywords": [],
                "blocked_reason": "Sem melhoria segura.",
            },
        },
    ]
    result = FreeActionPlanner().build(channel_report=channel, video_reports=videos)
    assert result["actions"][0]["video_id"] == "v1"
    assert result["actions"][0]["optimization_ready"] is True
    assert result["actions"][0]["priority"] == "alta"
    assert result["writes_performed"] == 0


def test_action_planner_is_deterministic():
    channel = {"recommendations": []}
    videos = [{"video_id": "a", "overall_score": 50, "optimization": {"optimization_ready": False, "confidence": 70}}]
    planner = FreeActionPlanner()
    assert planner.build(channel_report=channel, video_reports=videos) == planner.build(channel_report=channel, video_reports=videos)
