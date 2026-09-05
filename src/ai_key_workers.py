from __future__ import annotations

from PySide6.QtCore import QThread, Signal


class APIKeyTestWorker(QThread):
    success = Signal(object)
    error = Signal(str)

    def __init__(self, runtime, provider: str, key_id: str, model: str = "", base_url: str = ""):
        super().__init__()
        self.runtime = runtime
        self.provider = provider
        self.key_id = key_id
        self.model = model
        self.base_url = base_url

    def run(self):
        try:
            result = self.runtime.test_api_key(
                self.provider,
                self.key_id,
                model=self.model,
                base_url=self.base_url,
            )
            self.success.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))
