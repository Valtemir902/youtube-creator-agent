from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True, frozen=True)
class SeoSignal:
    key: str
    label: str
    state: str
    evidence: str
    recommendation: str | None = None


def analyze_metadata_facts(video: dict[str, Any]) -> dict[str, Any]:
    """Explain metadata hygiene using only observable fields, never search-volume fiction."""

    title = str(video.get("title") or "").strip()
    description = str(video.get("description") or "").strip()
    tags = [str(tag).strip() for tag in (video.get("tags") or []) if str(tag).strip()]
    signals: list[SeoSignal] = []

    title_len = len(title)
    if not title:
        signals.append(SeoSignal("title", "Título", "critical", "Título vazio.", "Defina um título antes de publicar."))
    elif title_len > 100:
        signals.append(SeoSignal("title", "Título", "critical", f"{title_len} caracteres; o limite da API é 100.", "Reduza o título."))
    elif title_len < 25:
        signals.append(SeoSignal("title", "Título", "attention", f"{title_len} caracteres.", "Verifique se o título comunica assunto e benefício com clareza."))
    else:
        signals.append(SeoSignal("title", "Título", "ok", f"{title_len} caracteres dentro do limite."))

    desc_len = len(description)
    if not description:
        signals.append(SeoSignal("description", "Descrição", "attention", "Descrição vazia.", "Adicione contexto útil, links e informações relevantes quando fizer sentido."))
    elif desc_len < 80:
        signals.append(SeoSignal("description", "Descrição", "attention", f"Descrição curta: {desc_len} caracteres.", "Confira se ela explica o conteúdo sem repetir o título."))
    else:
        signals.append(SeoSignal("description", "Descrição", "ok", f"{desc_len} caracteres de descrição observados."))

    if len(tags) > 30:
        signals.append(SeoSignal("tags", "Tags", "attention", f"{len(tags)} tags observadas.", "Revise redundâncias; volume de tags não substitui relevância."))
    elif tags:
        signals.append(SeoSignal("tags", "Tags", "ok", f"{len(tags)} tags observadas."))
    else:
        signals.append(SeoSignal("tags", "Tags", "neutral", "Nenhuma tag observada.", "Tags são opcionais; use apenas termos realmente relacionados."))

    issues = sum(signal.state in {"critical", "attention"} for signal in signals)
    return {
        "source": "youtube_data_api_metadata",
        "estimated": False,
        "title_length": title_len,
        "description_length": desc_len,
        "tag_count": len(tags),
        "issue_count": issues,
        "signals": [
            {
                "key": signal.key,
                "label": signal.label,
                "state": signal.state,
                "evidence": signal.evidence,
                "recommendation": signal.recommendation,
            }
            for signal in signals
        ],
    }


def build_seo_context(video: dict[str, Any], analytics: dict[str, Any] | None = None) -> dict[str, Any]:
    """Package facts for an AI provider without turning recommendations into facts."""

    metadata = analyze_metadata_facts(video)
    facts: list[dict[str, Any]] = [
        {"source": metadata["source"], "kind": "metadata", "value": metadata},
    ]
    if analytics and analytics.get("available"):
        facts.append(
            {
                "source": analytics.get("source") or "youtube_analytics_api",
                "kind": "analytics",
                "value": analytics,
            }
        )
    return {
        "facts": facts,
        "recommendations_are_facts": False,
        "search_volume_available": False,
        "official_ctr_available": False,
        "limitations": [
            "Não inferir volume de busca sem fonte específica.",
            "Não inferir CTR oficial sem dado oficial de Reporting/Analytics que o exponha.",
            "Toda sugestão de metadados deve passar pelo Write Gateway antes de escrita.",
        ],
    }
