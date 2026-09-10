from __future__ import annotations

from intelligence.free_video_optimizer import FreeVideoOptimizer


def _current():
    return {
        "video_id": "abc123",
        "title": "Minha pescaria no rio",
        "description": "Dia de pescaria com a família.",
        "tags": ["pescaria", "rio"],
        "categoryId": "22",
        "defaultLanguage": "pt-BR",
    }


def _transcript():
    sentence = (
        "Hoje fomos pescar tucunaré no rio e mostramos a pescaria completa, "
        "as iscas usadas, o barco e os momentos em que os peixes atacaram. "
    )
    return sentence * 12


def _measured():
    return [
        {
            "keyword": "pescaria de tucunaré",
            "opportunity_score": 78,
            "market_opportunity_score": 74,
            "confidence": 92,
            "demand_index": 71,
            "competition_score": 42,
            "fresh_7d_rate": 0.35,
            "fresh_30d_rate": 0.70,
        },
        {
            "keyword": "isca para tucunaré",
            "opportunity_score": 64,
            "confidence": 86,
            "demand_index": 58,
            "competition_score": 39,
        },
    ]


def test_optimizer_blocks_without_transcript():
    plan = FreeVideoOptimizer().build(_current(), transcript="", keyword_results=_measured())
    assert plan["optimization_ready"] is False
    assert "Transcrição" in plan["blocked_reason"]
    assert plan["proposed"] == plan["current"]
    assert plan["writes_performed"] == 0


def test_optimizer_blocks_keywords_that_do_not_match_content():
    rows = [{"keyword": "curso de excel avançado", "opportunity_score": 99, "confidence": 99}]
    plan = FreeVideoOptimizer().build(_current(), transcript=_transcript(), keyword_results=rows)
    assert plan["optimization_ready"] is False
    assert "aderência semântica" in plan["blocked_reason"]
    assert plan["target_keywords"] == []


def test_optimizer_uses_only_grounded_measured_keywords():
    plan = FreeVideoOptimizer().build(_current(), transcript=_transcript(), keyword_results=_measured())
    assert plan["optimization_ready"] is True
    assert plan["uses_external_ai"] is False
    assert plan["writes_performed"] == 0
    assert "pescaria de tucunaré" in plan["target_keywords"]
    assert all("excel" not in value for value in plan["target_keywords"])
    assert len(plan["proposed"]["title"]) <= 100
    assert len(plan["proposed"]["description"]) <= 5000
    assert len(plan["proposed"]["tags"]) <= 12
    assert sum(len(tag) + 1 for tag in plan["proposed"]["tags"]) <= 480


def test_optimizer_preserves_category_and_language():
    current = _current()
    plan = FreeVideoOptimizer().build(current, transcript=_transcript(), keyword_results=_measured())
    assert plan["proposed"]["categoryId"] == "22"
    assert plan["proposed"]["defaultLanguage"] == "pt-BR"
    assert plan["changed"]["categoryId"] is False
    assert plan["category_policy"] == "preserve_without_high_confidence_classifier"
    assert plan["language_policy"] == "preserve_current_language"


def test_optimizer_is_deterministic():
    first = FreeVideoOptimizer().build(_current(), transcript=_transcript(), keyword_results=_measured())
    second = FreeVideoOptimizer().build(_current(), transcript=_transcript(), keyword_results=_measured())
    assert first == second


def test_optimizer_does_not_claim_ranking_guarantee():
    plan = FreeVideoOptimizer().build(_current(), transcript=_transcript(), keyword_results=_measured())
    methodology = plan["methodology"].casefold()
    assert "not a promise" in methodology
    assert "no llm" in methodology
