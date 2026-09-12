from __future__ import annotations

import sys

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView

from desktop_local_server import app_data_dir, start_local_app_server


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
