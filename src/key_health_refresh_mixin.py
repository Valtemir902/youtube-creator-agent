from __future__ import annotations


class KeyHealthRefreshMixin:
    def _refresh_key_health_safely(self):
        try:
            self._refresh_ai_key_table()
        except Exception:
            pass

    def _strategy_error(self, error: str):
        self._refresh_key_health_safely()
        return super()._strategy_error(error)

    def _command_center_error(self, error: str):
        self._refresh_key_health_safely()
        return super()._command_center_error(error)
