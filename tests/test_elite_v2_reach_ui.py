from __future__ import annotations

from elite_v2_reach_ui import REACH_UI_JS, reach_ui_webengine_source


def test_reporting_ui_is_explicit_on_demand_only() -> None:
    source = reach_ui_webengine_source()
    assert "data-v2-reach-card" in source
    assert "Carregar métricas oficiais" in source
    assert "/api/v2/reporting/reach" in source
    assert "write_required" in source
    assert "nenhuma chamada" in source.lower()

    # The only Reporting fetch must live inside the explicit click handler.
    click_pos = REACH_UI_JS.index("button.addEventListener('click'")
    fetch_pos = REACH_UI_JS.index("fetch('/api/v2/reporting/reach")
    assert fetch_pos > click_pos

    # The UI never exposes the administrative Reporting jobs.create operation.
    assert "create_reach_job" not in REACH_UI_JS
    assert "jobs.create" not in REACH_UI_JS
    assert "estimated" not in REACH_UI_JS.lower() or "estimad" in REACH_UI_JS.lower()
