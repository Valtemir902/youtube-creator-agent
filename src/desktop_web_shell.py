from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView

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


class DesktopWindow(QMainWindow):
    """Thin native Windows shell for the current production dashboard UI."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("YouTube Creator Agent Elite")
        self.resize(1440, 900)
        self.setMinimumSize(1080, 700)

        configure_profile()
        self.web = QWebEngineView(self)
        self.setCentralWidget(self.web)
        self.web.setUrl(QUrl(dashboard_url()))


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("YouTube Creator Agent Elite")
    app.setOrganizationName("Silva Digital Tech")
    window = DesktopWindow()
    window.show()
    return int(app.exec())
