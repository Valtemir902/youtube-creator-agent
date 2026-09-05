from __future__ import annotations

from dataclasses import dataclass


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class OpportunityInput:
    """Normalized evidence used by the scoring engine.

    Every field must come from measured/derived data. None should be produced
    directly by an LLM. Values are expected on a 0..1 scale.
    """

    trend_strength: float
    recent_view_velocity: float
    small_channel_breakout: float
    freshness: float
    channel_fit: float
    intent_strength: float
    competition_pressure: float
    dominant_channel_concentration: float
    evidence_coverage: float


@dataclass(frozen=True)
class OpportunityResult:
    score: int
    confidence: int
    demand_score: int
    competition_score: int
    channel_fit_score: int
    reasons: tuple[str, ...]


WEIGHTS = {
    "trend_strength": 0.22,
    "recent_view_velocity": 0.22,
    "small_channel_breakout": 0.16,
    "freshness": 0.10,
    "channel_fit": 0.16,
    "intent_strength": 0.14,
}


def calculate_opportunity_score(data: OpportunityInput) -> OpportunityResult:
    positives = {
        "trend_strength": _clamp(data.trend_strength),
        "recent_view_velocity": _clamp(data.recent_view_velocity),
        "small_channel_breakout": _clamp(data.small_channel_breakout),
        "freshness": _clamp(data.freshness),
        "channel_fit": _clamp(data.channel_fit),
        "intent_strength": _clamp(data.intent_strength),
    }
    competition_pressure = _clamp(data.competition_pressure)
    channel_concentration = _clamp(data.dominant_channel_concentration)
    evidence_coverage = _clamp(data.evidence_coverage)

    positive_score = sum(positives[key] * weight for key, weight in WEIGHTS.items())

    # Competition is a penalty. It combines how hard the result set is to beat
    # with how concentrated ranking positions are in dominant channels.
    competition_penalty = (competition_pressure * 0.65) + (channel_concentration * 0.35)

    # Competition can reduce an opportunity substantially, but never erase
    # all evidence of demand. This keeps the score stable and interpretable.
    raw_score = positive_score * (1.0 - 0.55 * competition_penalty)

    # Low evidence coverage prevents a deceptively precise high score.
    confidence_multiplier = 0.55 + (0.45 * evidence_coverage)
    final_score = round(_clamp(raw_score * confidence_multiplier) * 100)

    demand = round(
        _clamp(
            positives["trend_strength"] * 0.38
            + positives["recent_view_velocity"] * 0.42
            + positives["intent_strength"] * 0.20
        )
        * 100
    )
    competition = round((1.0 - competition_penalty) * 100)
    fit = round(positives["channel_fit"] * 100)
    confidence = round(evidence_coverage * 100)

    reasons: list[str] = []
    if positives["trend_strength"] >= 0.7:
        reasons.append("tendência recente forte")
    if positives["recent_view_velocity"] >= 0.7:
        reasons.append("alta velocidade recente de visualizações")
    if positives["small_channel_breakout"] >= 0.6:
        reasons.append("canais menores estão conseguindo romper o ranking")
    if positives["freshness"] >= 0.65:
        reasons.append("resultados recentes estão ganhando espaço")
    if positives["channel_fit"] >= 0.7:
        reasons.append("forte aderência ao histórico do canal")
    if competition_penalty <= 0.35:
        reasons.append("pressão competitiva abaixo da média")
    elif competition_penalty >= 0.75:
        reasons.append("ranking fortemente dominado por concorrentes")
    if evidence_coverage < 0.6:
        reasons.append("confiança reduzida por cobertura de dados insuficiente")

    return OpportunityResult(
        score=final_score,
        confidence=confidence,
        demand_score=demand,
        competition_score=competition,
        channel_fit_score=fit,
        reasons=tuple(reasons),
    )
