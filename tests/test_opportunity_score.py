from src.intelligence.opportunity_score import OpportunityInput, calculate_opportunity_score


def test_strong_low_competition_opportunity_scores_high():
    result = calculate_opportunity_score(
        OpportunityInput(
            trend_strength=0.92,
            recent_view_velocity=0.94,
            small_channel_breakout=0.80,
            freshness=0.85,
            channel_fit=0.90,
            intent_strength=0.82,
            competition_pressure=0.20,
            dominant_channel_concentration=0.18,
            evidence_coverage=0.95,
        )
    )
    assert result.score >= 75
    assert result.confidence == 95
    assert result.competition_score >= 75
    assert "pressão competitiva abaixo da média" in result.reasons


def test_high_competition_reduces_score():
    common = dict(
        trend_strength=0.90,
        recent_view_velocity=0.90,
        small_channel_breakout=0.70,
        freshness=0.80,
        channel_fit=0.85,
        intent_strength=0.80,
        evidence_coverage=0.95,
    )
    low = calculate_opportunity_score(
        OpportunityInput(
            **common,
            competition_pressure=0.15,
            dominant_channel_concentration=0.20,
        )
    )
    high = calculate_opportunity_score(
        OpportunityInput(
            **common,
            competition_pressure=0.90,
            dominant_channel_concentration=0.90,
        )
    )
    assert high.score < low.score
    assert high.competition_score < low.competition_score


def test_low_evidence_coverage_caps_confidence_and_score():
    full = calculate_opportunity_score(
        OpportunityInput(1, 1, 1, 1, 1, 1, 0, 0, 1)
    )
    weak = calculate_opportunity_score(
        OpportunityInput(1, 1, 1, 1, 1, 1, 0, 0, 0.2)
    )
    assert weak.confidence == 20
    assert weak.score < full.score
    assert "confiança reduzida por cobertura de dados insuficiente" in weak.reasons


def test_values_are_clamped_to_valid_range():
    result = calculate_opportunity_score(
        OpportunityInput(2, 2, 2, 2, 2, 2, -1, -1, 2)
    )
    assert 0 <= result.score <= 100
    assert result.confidence == 100
    assert result.demand_score == 100
