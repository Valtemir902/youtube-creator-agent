from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ai.runtime import AIRuntime
from intelligence.channel_command_center import ChannelCommandCenterEngine


class ChannelCommandCenterWorker(QThread):
    progress = Signal(str)
    success = Signal(object)
    error = Signal(str)

    def __init__(self, token_file: str, ai_runtime: AIRuntime):
        super().__init__()
        self.token_file = token_file
        self.ai_runtime = ai_runtime

    def run(self):
        try:
            self.progress.emit("Lendo o perfil real do canal e Analytics dos últimos 28 dias...")
            engine = ChannelCommandCenterEngine(self.token_file, self.ai_runtime)
            self.progress.emit("Cruzando histórico do canal com oportunidades atuais do YouTube...")
            report = engine.build()
            self.progress.emit("Plano editorial e auditoria concluídos.")
            self.success.emit(report)
        except Exception as exc:
            self.error.emit(f"Falha no Command Center: {exc}")
