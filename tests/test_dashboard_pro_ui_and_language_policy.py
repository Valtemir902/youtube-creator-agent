from __future__ import annotations

from creator_service.ai_language_policy import preserve_channel_language
from creator_service.dashboard_pro_ui import enhance_dashboard_html


def test_ai_plan_preserves_explicit_channel_language():
    plan = {"title": "New title", "language": "pt-BR", "description": "x"}
    channel = {"default_language": "en"}

    safe = preserve_channel_language(plan, channel)

    assert safe["language"] == "en"
    assert safe["language_policy"] == "preserve_channel_language"
    assert safe["title"] == "New title"
    assert plan["language"] == "pt-BR"


def test_ai_plan_with_unknown_channel_language_does_not_trust_model_guess():
    safe = preserve_channel_language({"language": "de", "title": "x"}, {"default_language": None})

    assert safe["language"] == ""
    assert safe["language_policy"] == "preserve_channel_language"


def test_professional_dashboard_enhancement_is_additive_and_idempotent():
    source = """<!doctype html><html><head><title>Dashboard</title></head><body>
    <section id="home"><div class="grid"><article id="channelProfileCard"><div class="notice"><b>Descrição do canal</b><div id="channelDescription">Existing description</div></div></article></div></section>
    <section id="strategy"><div class="grid"><div id="researchResult" class="code hidden"></div><div id="strategyResult" class="code hidden"></div><div id="keywordResult" class="code hidden"></div><div id="evidenceRaw" class="code hidden"></div></div></section>
    <section id="audit"><div class="grid"><div id="auditRaw" class="code hidden"></div></div></section>
    <section id="videos"><div class="grid"></div></section><section id="publish"><div class="grid"></div></section>
    </body></html>"""

    enhanced = enhance_dashboard_html(source)

    assert 'data-yca-pro-dashboard' in enhanced
    assert 'id="channelProfileCard"' in enhanced
    assert 'id="researchResult"' in enhanced
    assert 'Desempenho real do canal' in enhanced
    assert 'Ver dados técnicos' in enhanced
    assert 'Toque para expandir' in enhanced
    assert '/api/dashboard/videos?limit=12' in enhanced
    assert '/api/dashboard/channel?period_days=28' in enhanced
    assert 'O idioma original é preservado pelo servidor.' in enhanced
    assert enhance_dashboard_html(enhanced) == enhanced


def test_professional_dashboard_keeps_raw_json_only_inside_collapsible_technical_view():
    source = '<html><head></head><body><div id="researchResult" class="code"></div></body></html>'
    enhanced = enhance_dashboard_html(source)

    assert 'class="tech-details"' in enhanced
    assert '<summary>Ver dados técnicos</summary>' in enhanced
    assert 'renderStructured' in enhanced
