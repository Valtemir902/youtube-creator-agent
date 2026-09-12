from intelligence.free_keyword_intelligence import FreeKeywordIntelligence


def row(keyword, demand=70, competition=40, opportunity=75, confidence=90, **extra):
    return {
        "keyword": keyword,
        "demand_index": demand,
        "competition_score": competition,
        "opportunity_score": opportunity,
        "confidence": confidence,
        "fresh_7d_rate": extra.get("fresh_7d_rate", 0.5),
        "fresh_30d_rate": extra.get("fresh_30d_rate", 0.8),
        "fresh_90d_rate": extra.get("fresh_90d_rate", 0.95),
        "median_views_per_day": extra.get("median_views_per_day", 1200),
        "small_channel_breakout_rate": extra.get("small_channel_breakout_rate", 0.3),
        "evidence": [{"video_id": "abc"}],
    }


def test_classifies_tail_and_positive_keywords_from_measured_rows():
    engine = FreeKeywordIntelligence()
    report = engine.analyze(
        [
            row("café"),
            row("café especial"),
            row("como fazer café especial"),
        ],
        source_text="Hoje vou mostrar como fazer café especial em casa. Café especial exige moagem correta.",
    )
    assert report["uses_external_ai"] is False
    assert report["exact_search_volume_available"] is False
    assert report["tail_distribution"]["short_tail"] >= 1
    assert report["tail_distribution"]["mid_tail"] >= 1
    assert report["tail_distribution"]["long_tail"] >= 1
    assert all(item["classification"] == "positive" for item in report["positive_keywords"])


def test_rejects_unrelated_or_bad_competition_keyword():
    report = FreeKeywordIntelligence().analyze(
        [
            row("bitcoin investimento", demand=95, competition=30, opportunity=90),
            row("café", demand=30, competition=92, opportunity=30),
        ],
        source_text="Receita de café coado, moagem do café e temperatura da água.",
    )
    by_keyword = {item["keyword"]: item for item in report["negative_keywords"]}
    assert "bitcoin investimento" in by_keyword
    assert "low_content_fit" in by_keyword["bitcoin investimento"]["risk_flags"]
    assert "café" in by_keyword
    assert "high_competition_low_demand" in by_keyword["café"]["risk_flags"]


def test_chart_payload_is_traceable_and_not_fake_volume():
    report = FreeKeywordIntelligence().analyze(
        [row("trilha gps", demand=61, competition=47, opportunity=72)],
        source_text="Aplicativo de trilha com gps offline para navegação em trilhas.",
    )
    chart = report["charts"]["demand_vs_competition"][0]
    assert chart["keyword"] == "trilha gps"
    assert chart["demand"] == 61
    assert chart["competition"] == 47
    assert report["demand_metric"] == "normalized_observed_search_index"
    assert "exact monthly search volume" in report["methodology"]


def test_keyword_intent_is_deterministic():
    report = FreeKeywordIntelligence().analyze(
        [row("como fazer café especial")],
        source_text="como fazer café especial em casa passo a passo",
    )
    assert report["positive_keywords"][0]["intent"] == "how_to"
