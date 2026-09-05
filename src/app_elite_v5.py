from __future__ import annotations

from PySide6.QtWidgets import QApplication

from app_elite import JanelaElite
from channel_command_mixin import ChannelCommandCenterMixin


class YouTubeCreatorAgentElite(ChannelCommandCenterMixin, JanelaElite):
    """Current commercial desktop shell.

    The mixin overrides the legacy audit page while preserving the validated
    multi-AI, research and publishing features from JanelaElite.
    """

    def _rename_brand(self):
        super()._rename_brand()
        self.setWindowTitle("YouTube Creator Agent Elite v5")
        for label in self.sidebar.findChildren(type(self.lbl_status_api)):
            text = label.text()
            if text.startswith("v4.0"):
                label.setText("v5.0 Channel Intelligence\n© 2026 Creator Intelligence")


def run():
    import sys

    app = QApplication(sys.argv)
    window = YouTubeCreatorAgentElite()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
