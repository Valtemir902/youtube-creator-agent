from intelligence.free_playlist_optimizer import FreePlaylistOptimizer


def _videos():
    return [
        {"video_id": "1", "title": "Plantio de milho na roça", "description": "preparo da terra e plantio"},
        {"video_id": "2", "title": "Como plantar milho", "description": "plantio rural e agricultura"},
        {"video_id": "3", "title": "Colheita do milho", "description": "milho na roça e colheita"},
        {"video_id": "4", "title": "Plantio de milho passo a passo", "description": "agricultura na roça"},
    ]


def test_playlist_optimizer_builds_grounded_description_and_preserves_title_privacy():
    result = FreePlaylistOptimizer().build(
        {"playlist_id": "p1", "title": "Milho na Roça", "description": "curta", "privacy_status": "public"},
        member_videos=_videos(),
        keyword_results=[{"keyword": "plantio de milho", "opportunity_score": 80, "confidence": 90}],
    )
    assert result["optimization_ready"] is True
    assert result["proposed"]["title"] == "Milho na Roça"
    assert result["proposed"]["privacy_status"] == "public"
    assert "plantio de milho" in result["proposed"]["description"]
    assert result["uses_external_ai"] is False
    assert result["writes_performed"] == 0


def test_playlist_optimizer_detects_unrelated_outlier():
    videos = _videos() + [{"video_id": "x", "title": "Curso de Excel financeiro", "description": "planilhas"}]
    result = FreePlaylistOptimizer().build(
        {"playlist_id": "p1", "title": "Milho", "description": "", "privacy_status": "private"},
        member_videos=videos,
        keyword_results=[],
    )
    assert any(row["video_id"] == "x" for row in result["outlier_videos"])


def test_playlist_optimizer_blocks_tiny_playlist():
    result = FreePlaylistOptimizer().build(
        {"playlist_id": "p1", "title": "Teste", "description": "", "privacy_status": "private"},
        member_videos=[{"video_id": "1", "title": "um vídeo", "description": ""}],
        keyword_results=[],
    )
    assert result["optimization_ready"] is False
    assert result["blocked_reason"]
    assert result["proposed"] == result["current"]


def test_playlist_optimizer_is_deterministic():
    current = {"playlist_id": "p1", "title": "Milho", "description": "", "privacy_status": "unlisted"}
    rows = [{"keyword": "plantio milho", "opportunity_score": 70, "confidence": 80}]
    assert FreePlaylistOptimizer().build(current, member_videos=_videos(), keyword_results=rows) == FreePlaylistOptimizer().build(current, member_videos=_videos(), keyword_results=rows)
