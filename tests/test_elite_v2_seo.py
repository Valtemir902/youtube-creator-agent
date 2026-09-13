from __future__ import annotations

from elite_v2_seo import analyze_metadata_facts, build_seo_context


def test_seo_diagnostics_only_claim_observable_metadata_facts() -> None:
    result = analyze_metadata_facts(
        {
            "title": "Como usar pulverizador costal na roça",
            "description": "Uma descrição útil " * 8,
            "tags": ["pulverizador", "roça"],
        }
    )
    assert result["source"] == "youtube_data_api_metadata"
    assert result["estimated"] is False
    assert result["title_length"] > 0
    assert result["description_length"] > 80
    assert result["tag_count"] == 2
    assert all("state" in signal and "evidence" in signal for signal in result["signals"])


def test_seo_context_separates_facts_from_recommendations_and_missing_metrics() -> None:
    context = build_seo_context({"title": "A", "description": "", "tags": []})
    assert context["facts"]
    assert context["recommendations_are_facts"] is False
    assert context["search_volume_available"] is False
    assert context["official_ctr_available"] is False
    assert any("Não inferir volume de busca" in item for item in context["limitations"])
    assert any("Write Gateway" in item for item in context["limitations"])


def test_official_analytics_can_be_attached_with_source_provenance() -> None:
    context = build_seo_context(
        {"title": "Título válido", "description": "Descrição longa " * 10, "tags": []},
        {"available": True, "source": "youtube_analytics_api", "rows": [{"views": 10}]},
    )
    assert len(context["facts"]) == 2
    assert context["facts"][1]["source"] == "youtube_analytics_api"
