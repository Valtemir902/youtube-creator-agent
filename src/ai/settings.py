from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class AISettings:
    provider: str = "gemini"
    model: str = ""
    base_url: str = ""
    remember_api_key: bool = True


class AISettingsStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> AISettings:
        if not self.path.exists():
            return AISettings()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return AISettings()
        return AISettings(
            provider=str(payload.get("provider") or "gemini"),
            model=str(payload.get("model") or ""),
            base_url=str(payload.get("base_url") or ""),
            remember_api_key=bool(payload.get("remember_api_key", True)),
        )

    def save(self, settings: AISettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(asdict(settings), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
