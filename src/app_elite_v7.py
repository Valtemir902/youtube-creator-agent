from __future__ import annotations

from PySide6.QtWidgets import QApplication, QLabel

from app_elite_v6 import YouTubeCreatorAgentElite as YouTubeCreatorAgentEliteV6
from multikey_config_mixin import MultiKeyConfigMixin


class YouTubeCreatorAgentElite(MultiKeyConfigMixin, YouTubeCreatorAgentEliteV6):
    """v7 desktop shell with multi-key rotation and persistent creator memory."""

    def _rename_brand(self):
        super()._rename_brand()
        self.setWindowTitle("YouTube Creator Agent Elite v7")
        for label in self.sidebar.findChildren(QLabel):
            text = label.text()
            if text.startswith("v6.0"):
                label.setText("v7.0 Key Rotation + Memory\n© 2026 Creator Intelligence")


def run():
    import sys

    app = QApplication(sys.argv)
    window = YouTubeCreatorAgentElite()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
