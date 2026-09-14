from intelligence.free_channel_optimizer import FreeChannelOptimizer


def test_channel_optimizer_blocks_when_evidence_is_too_thin():
    result = FreeChannelOptimizer().build(
        {"title": "Canal X", "description": "Curta", "keywords": "", "country": "BR", "default_language": "pt-BR"},
        {"topic_terms": ["roça"], "top_search_terms": [], "video_count": 3},
    )
    assert result["optimization_ready"] is False
    assert result["blocked_reason"]
    assert result["writes_performed"] == 0
    assert result["proposed"] == result["current"]


def test_channel_optimizer_uses_only_observed_terms_and_preserves_locale():
    result = FreeChannelOptimizer().build(
        {"title": "Vida na Roça", "description": "Canal sobre rotina.", "keywords": "", "country": "BR", "default_language": "pt-BR"},
        {
            "topic_terms": ["roça", "plantio", "colheita", "agricultura"],
            "top_search_terms": [
                {"term": "vida na roça"},
                {"term": "plantio de milho"},
            ],
            "video_count": 50,
        },
    )
    assert result["optimization_ready"] is True
    assert "roça" in result["proposed"]["keywords"]
    assert "plantio de milho" in result["proposed"]["keywords"]
    assert result["proposed"]["country"] == "BR"
    assert result["proposed"]["default_language"] == "pt-BR"
    assert result["uses_external_ai"] is False


def test_channel_optimizer_is_deterministic():
    current = {"title": "Canal", "description": "x", "keywords": "", "country": "BR", "default_language": "pt-BR"}
    profile = {"topic_terms": ["trilha", "gps", "offline"], "top_search_terms": [{"term": "gps offline"}], "video_count": 8}
    a = FreeChannelOptimizer().build(current, profile)
    b = FreeChannelOptimizer().build(current, profile)
    assert a == b
