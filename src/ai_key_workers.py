from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ai.key_test import inspect_key_and_model


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
            result = inspect_key_and_model(
                self.runtime,
                self.provider,
                self.key_id,
                model=self.model,
                base_url=self.base_url,
            )
            # Always publish the discovery result first. Even if the currently
            # selected model is overloaded/invalid, the UI can immediately show
            # every other model exposed to this key.
            self.success.emit(result)
            if result.get("model_test_ok") is False:
                self.error.emit(str(result.get("model_test_error") or "Falha ao testar o modelo selecionado."))
        except Exception as exc:
            # If model discovery itself fails there is no trustworthy list to show.
            self.error.emit(str(exc))
