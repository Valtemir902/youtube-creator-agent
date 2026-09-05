from src.ui_theme import THEMES, UISettings, UISettingsStore, build_stylesheet


def test_theme_store_roundtrip(tmp_path):
    path = tmp_path / "ui_settings.json"
    store = UISettingsStore(path)
    settings = UISettings(theme="Cyber Purple", compact_mode=False, animations=False)
    store.save(settings)
    loaded = store.load()
    assert loaded.theme == "Cyber Purple"
    assert loaded.animations is False


def test_unknown_theme_falls_back(tmp_path):
    path = tmp_path / "ui_settings.json"
    path.write_text('{"theme":"tema inexistente"}', encoding="utf-8")
    loaded = UISettingsStore(path).load()
    assert loaded.theme == "Neon Cyan"


def test_all_themes_generate_stylesheet():
    for name in THEMES:
        css = build_stylesheet(name)
        assert "QMainWindow" in css
        assert THEMES[name].accent in css
