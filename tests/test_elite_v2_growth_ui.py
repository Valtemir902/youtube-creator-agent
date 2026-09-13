from __future__ import annotations

from elite_v2_growth import GROWTH_CSS, GROWTH_JS, growth_webengine_source


def test_growth_workspace_uses_read_only_official_analytics_route() -> None:
    source = growth_webengine_source()
    for token in (
        "data-v2-growth-workspace",
        "Growth & Analytics",
        "YouTube Analytics",
        "/api/v2/analytics/timeseries",
        "Fonte oficial, sem estimativas",
        "Analytics indisponível agora",
    ):
        assert token in source
    assert "dimensions" not in GROWTH_JS  # API shape remains server-owned.
    assert "method:" not in GROWTH_JS.lower()
    assert "POST" not in GROWTH_JS
    assert "PUT" not in GROWTH_JS
    assert "DELETE" not in GROWTH_JS
    assert ".v2-timeseries-line" in GROWTH_CSS


def test_growth_chart_loads_on_demand_instead_of_dashboard_boot() -> None:
    assert "data-tab=\"strategy\"" in GROWTH_JS
    assert "if(!loaded)setTimeout(()=>load(false)" in GROWTH_JS
    assert "Carregar Analytics" in GROWTH_JS
