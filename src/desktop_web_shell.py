from __future__ import annotations

import json
import sys

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView

from creator_service.local_ai_dashboard import _CSS, _SCRIPT
from desktop_local_server import app_data_dir, start_local_app_server


def _inner_tag_text(source: str, closing_tag: str) -> str:
    start = source.find(">")
    end = source.rfind(closing_tag)
    if start < 0 or end < 0 or end <= start:
        raise RuntimeError(f"Local AI asset inválido: {closing_tag}")
    return source[start + 1 : end]


def local_ai_webengine_source() -> str:
    """Build the Local AI UI bootstrap injected only into the local desktop page.

    The dashboard HTML remains the same local-first asset used by the desktop
    server. Qt injects the Local AI presentation/bridge in the main JS world so
    the page can pair with the loopback companion without any cloud shell.
    """

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


def install_local_ai_webengine_script(web: QWebEngineView) -> None:
    script = QWebEngineScript()
    script.setName("yca-local-ai-desktop")
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
    script.setRunsOnSubFrames(False)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setSourceCode(local_ai_webengine_source())
    web.page().scripts().insert(script)


class DesktopWindow(QMainWindow):
    """Windows shell for the fully local Creator Agent control plane."""

    def __init__(self) -> None:
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
