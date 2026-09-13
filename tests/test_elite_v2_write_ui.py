from __future__ import annotations

from elite_v2_write_ui import WRITE_UI_CSS, WRITE_UI_JS, write_ui_webengine_source


def test_write_ui_defaults_to_explicit_session_gate() -> None:
    source = write_ui_webengine_source()
    for token in (
        "data-v2-write-control",
        "Write Gateway",
        "Bloqueado",
        "Ativar gerenciamento",
        "Readback obrigatório",
        "Exclusões separadas",
        "/api/v2/write-mode",
    ):
        assert token in source
    assert "ATIVAR GERENCIAMENTO" in WRITE_UI_JS
    assert "/youtube/v3" not in WRITE_UI_JS
    assert "youtube.googleapis.com" not in WRITE_UI_JS
    assert ".v2-write-control" in WRITE_UI_CSS


def test_enabling_write_mode_is_local_policy_not_a_youtube_write() -> None:
    assert "enabled:true" in WRITE_UI_JS
    assert "Nenhuma escrita no YouTube foi executada por este controle" in WRITE_UI_JS
    assert "Cada alteração ainda exige preview" in WRITE_UI_JS
