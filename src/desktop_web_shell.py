from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView

from desktop_native_runtime import desktop_fetch_bootstrap, start_native_server

DEFAULT_DASHBOARD_URL = "https://creator.silvadigitaltech.com/dashboard"
APP_DATA_DIR = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "YouTubeCreatorAgent" / "Desktop"


def dashboard_url() -> str:
    value = (os.getenv("YCA_DESKTOP_URL") or DEFAULT_DASHBOARD_URL).strip()
    if not value.lower().startswith("https://"):
        raise ValueError("YCA_DESKTOP_URL deve usar HTTPS.")
    return value


def configure_profile() -> QWebEngineProfile:
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    profile = QWebEngineProfile.defaultProfile()
    profile.setPersistentStoragePath(str(APP_DATA_DIR / "web-storage"))
    profile.setCachePath(str(APP_DATA_DIR / "web-cache"))
    return profile


def install_native_bootstrap(view: QWebEngineView, native_base: str) -> None:
    """Inject the local Python cache before any dashboard JavaScript executes."""
    script = QWebEngineScript()
    script.setName("yca-desktop-native-cache-v1")
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setRunsOnSubFrames(False)
    script.setSourceCode(desktop_fetch_bootstrap(native_base))
    view.page().scripts().insert(script)


class DesktopWindow(QMainWindow):
    """Native Windows shell for the production dashboard with local Python acceleration."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("YouTube Creator Agent Elite")
        self.resize(1440, 900)
        self.setMinimumSize(1080, 700)

        configure_profile()
        self.native_server, self.native_thread, self.native_base = start_native_server(
            APP_DATA_DIR / "native-cache-v1.json"
        )

        self.web = QWebEngineView(self)
        install_native_bootstrap(self.web, self.native_base)
        self.setCentralWidget(self.web)
        self.web.setUrl(QUrl(dashboard_url()))

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self.native_server.shutdown()
            self.native_server.server_close()
        finally:
            super().closeEvent(event)


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("YouTube Creator Agent Elite")
    app.setOrganizationName("Silva Digital Tech")
    window = DesktopWindow()
    window.show()
    return int(app.exec())
