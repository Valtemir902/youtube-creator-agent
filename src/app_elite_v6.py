from __future__ import annotations

from PySide6.QtWidgets import QApplication, QLabel

from app_elite_v5 import YouTubeCreatorAgentElite as YouTubeCreatorAgentEliteV5
from continuous_strategy_mixin import ContinuousStrategyMixin


class YouTubeCreatorAgentElite(ContinuousStrategyMixin, YouTubeCreatorAgentEliteV5):
    """v6 desktop shell with continuous strategic learning."""

    def _rename_brand(self):
        super()._rename_brand()
        self.setWindowTitle("YouTube Creator Agent Elite v6")
        for label in self.sidebar.findChildren(QLabel):
            text = label.text()
            if text.startswith("v5.0"):
                label.setText("v6.0 Continuous Strategy\n© 2026 Creator Intelligence")


def run():
    import sys

    app = QApplication(sys.argv)
    window = YouTubeCreatorAgentElite()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
