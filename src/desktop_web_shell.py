from __future__ import annotations

import json
import sys
from collections.abc import Iterable

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView

from creator_service.local_ai_dashboard import _CSS, _SCRIPT
from desktop_local_server import app_data_dir
from elite_v2_activity_ui import activity_ui_webengine_source
from elite_v2_ai_workspace import ai_workspace_webengine_source
from elite_v2_content_hub import content_hub_webengine_source
from elite_v2_growth import growth_webengine_source
from elite_v2_management_ui import management_ui_webengine_source
from elite_v2_reach_ui import reach_ui_webengine_source
from elite_v2_seo_ui import seo_ui_webengine_source
from elite_v2_server import start_elite_v2_product_server
from elite_v2_ui import elite_v2_webengine_source
from elite_v2_write_ui import write_ui_webengine_source

# Preserve the stable localhost boot contract name while routing to the additive
# V2 product server. The dashboard remains local and no production URL is used.
start_local_app_server = start_elite_v2_product_server


def _inner_tag_text(source: str, closing_tag: str) -> str:
    start = source.find(">")
    end = source.rfind(closing_tag)
    if start < 0 or end < 0 or end <= start:
        raise RuntimeError(f"Local AI asset inválido: {closing_tag}")
    return source[start + 1 : end]


def local_ai_webengine_source() -> str:
    """Build the Local AI UI bootstrap injected only into the local desktop page."""

    css = _inner_tag_text(_CSS, "</style>")
    script = _inner_tag_text(_SCRIPT, "</script>")
    css_json = json.dumps(css, ensure_ascii=False)
    return (
        "(()=>{"
        "if(!document.querySelector('style[data-yca-local-ai-desktop]')){"
        "const s=document.createElement('style');"
        "s.dataset.ycaLocalAiDesktop='1';"
        f"s.textContent={css_json};"
        "(document.head||document.documentElement).appendChild(s);"
        "}"
        "})();\n"
        + script
    )


def _install_document_ready_script(web: QWebEngineView, name: str, source: str) -> None:
    script = QWebEngineScript()
    script.setName(name)
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
    script.setRunsOnSubFrames(False)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setSourceCode(source)
    web.page().scripts().insert(script)


def install_local_ai_webengine_script(web: QWebEngineView) -> None:
    _install_document_ready_script(web, "yca-local-ai-desktop", local_ai_webengine_source())


def install_elite_v2_webengine_script(web: QWebEngineView) -> None:
    """Layer independently-tested V2 modules over the stable dashboard DOM."""

    _install_document_ready_script(web, "yca-elite-v2-ui", elite_v2_webengine_source())
    _install_document_ready_script(web, "yca-elite-v2-content-hub", content_hub_webengine_source())
    _install_document_ready_script(web, "yca-elite-v2-growth", growth_webengine_source())
    _install_document_ready_script(web, "yca-elite-v2-reach", reach_ui_webengine_source())
    _install_document_ready_script(web, "yca-elite-v2-seo", seo_ui_webengine_source())
    _install_document_ready_script(web, "yca-elite-v2-ai-workspace", ai_workspace_webengine_source())
    _install_document_ready_script(web, "yca-elite-v2-write-ui", write_ui_webengine_source())
    _install_document_ready_script(web, "yca-elite-v2-management-ui", management_ui_webengine_source())
    _install_document_ready_script(web, "yca-elite-v2-activity", activity_ui_webengine_source())


class DesktopWindow(QMainWindow):
    """Windows shell for the fully local Creator Agent control plane."""

    def __init__(self, extra_document_ready_scripts: Iterable[tuple[str, str]] | None = None) -> None:
        super().__init__()
        self.setWindowTitle("YouTube Creator Agent Elite")
        self.resize(1440, 900)
        self.setMinimumSize(1080, 700)

        profile_root = app_data_dir() / "web-profile"
        profile_root.mkdir(parents=True, exist_ok=True)
        profile = QWebEngineProfile.defaultProfile()
        profile.setPersistentStoragePath(str(profile_root / "storage"))
        profile.setCachePath(str(profile_root / "cache"))

        self.local_server, self.local_thread, self.local_base = start_local_app_server()
        self.web = QWebEngineView(self)
        install_local_ai_webengine_script(self.web)
        install_elite_v2_webengine_script(self.web)
        for name, source in extra_document_ready_scripts or ():
            _install_document_ready_script(self.web, name, source)
        self.setCentralWidget(self.web)
        self.web.setUrl(QUrl(self.local_base + "/dashboard"))

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self.local_server.shutdown()
            self.local_server.server_close()
            self.local_thread.join(timeout=3)
        finally:
            super().closeEvent(event)


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("YouTube Creator Agent Elite")
    app.setOrganizationName("Silva Digital Tech")
    window = DesktopWindow()
    window.show()
    return int(app.exec())
