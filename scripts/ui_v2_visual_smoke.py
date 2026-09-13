from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from desktop_web_shell import DesktopWindow
from elite_v2_ui import V2_CSS, V2_JS, elite_v2_webengine_source


def pump(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.02)


def main() -> int:
    out = ROOT / "artifacts" / "ui-v2"
    out.mkdir(parents=True, exist_ok=True)

    required_tokens = [
        "--v2-bg", "--v2-surface", "--v2-border", "--v2-radius", "--v2-shadow",
        ".v2-command-grid", ".v2-command-card", ".video-item", ".playlist-item",
    ]
    missing = [token for token in required_tokens if token not in V2_CSS]
    if missing:
        raise RuntimeError(f"Design system incompleto: {missing}")
    for contract in ["data-v2-target", "elite-v2", "Local-first protegido", "Centro de comando"]:
        if contract not in V2_JS and contract not in elite_v2_webengine_source():
            raise RuntimeError(f"Contrato visual V2 ausente: {contract}")

    app = QApplication.instance() or QApplication([])
    window = DesktopWindow()
    window.setMinimumSize(0, 0)
    loaded = {"done": False, "ok": False}
    window.web.loadFinished.connect(lambda ok: loaded.update(done=True, ok=bool(ok)))
    window.show()

    deadline = time.monotonic() + 18
    while not loaded["done"] and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.02)
    if not loaded["done"] or not loaded["ok"]:
        raise RuntimeError(f"Dashboard V2 não carregou: {loaded}")

    pump(2.0)
    window.resize(1440, 900)
    pump(0.8)
    desktop_path = out / "elite-v2-desktop.png"
    if not window.grab().save(str(desktop_path)):
        raise RuntimeError("Falha ao salvar screenshot desktop")

    window.resize(430, 900)
    pump(1.0)
    mobile_path = out / "elite-v2-mobile.png"
    if not window.grab().save(str(mobile_path)):
        raise RuntimeError("Falha ao salvar screenshot mobile")

    for path in (desktop_path, mobile_path):
        if not path.is_file() or path.stat().st_size < 20_000:
            raise RuntimeError(f"Screenshot inválido ou vazio: {path} ({path.stat().st_size if path.exists() else 0} bytes)")

    payload = {
        "ok": True,
        "ui_version": "elite-v2",
        "desktop_screenshot": str(desktop_path.relative_to(ROOT)),
        "desktop_bytes": desktop_path.stat().st_size,
        "mobile_screenshot": str(mobile_path.relative_to(ROOT)),
        "mobile_bytes": mobile_path.stat().st_size,
        "stable_dashboard_replaced": False,
        "youtube_write_actions_executed": False,
    }
    print(json.dumps(payload, ensure_ascii=False), flush=True)
    window.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
