from __future__ import annotations

from creator_service.dashboard_overview_compat import fix_professional_overview_html


def test_professional_overview_targets_real_dashboard_section():
    source = "<section id='overview'></section><script>const home=document.getElementById('home');</script>"
    fixed = fix_professional_overview_html(source)

    assert "document.getElementById('overview')" in fixed
    assert "document.getElementById('home')" not in fixed


def test_overview_compat_is_idempotent_when_already_correct():
    source = "<script>const home=document.getElementById('overview');</script>"
    assert fix_professional_overview_html(source) == source
