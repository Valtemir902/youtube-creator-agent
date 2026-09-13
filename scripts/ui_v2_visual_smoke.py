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
from elite_v2_content_hub import CONTENT_HUB_CSS, CONTENT_HUB_JS
from elite_v2_ui import V2_CSS, V2_JS, elite_v2_webengine_source


def pump(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.02)


def _tab_script(tab: str | None) -> list[tuple[str, str]]:
    if not tab:
        return []
    source = (
        "window.addEventListener('DOMContentLoaded',()=>setTimeout(()=>{"
        f"document.querySelector('.nav button[data-tab=\"{tab}\"]')?.click();"
        "},900),{once:true});"
    )
    return [(f"yca-v2-visual-tab-{tab}", source)]


def capture(app: QApplication, out: Path, *, name: str, size: tuple[int, int], tab: str | None = None) -> Path:
    window = DesktopWindow(extra_document_ready_scripts=_tab_script(tab))
    window.setMinimumSize(0, 0)
    window.resize(*size)
    loaded = {"done": False, "ok": False}
    window.web.loadFinished.connect(lambda ok: loaded.update(done=True, ok=bool(ok)))
    window.show()

    deadline = time.monotonic() + 18
    while not loaded["done"] and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.02)
    if not loaded["done"] or not loaded["ok"]:
        window.close()
        raise RuntimeError(f"Dashboard V2 não carregou para {name}: {loaded}")

    pump(2.5)
    path = out / name
    if not window.grab().save(str(path)):
        window.close()
        raise RuntimeError(f"Falha ao salvar screenshot {name}")
    window.close()
    pump(0.3)
    app.processEvents()
    if not path.is_file() or path.stat().st_size < 20_000:
        raise RuntimeError(f"Screenshot inválido ou vazio: {path} ({path.stat().st_size if path.exists() else 0} bytes)")
    return path


def main() -> int:
    out = ROOT / "artifacts" / "ui-v2"
    out.mkdir(parents=True, exist_ok=True)

    required_tokens = [
        "--v2-bg", "--v2-surface", "--v2-border", "--v2-radius", "--v2-shadow",
        ".v2-command-grid", ".v2-command-card", ".video-item", ".playlist-item",
        ".v2-growth-deck", ".v2-ai-workspace",
    ]
    missing = [token for token in required_tokens if token not in V2_CSS]
    if missing:
        raise RuntimeError(f"Design system incompleto: {missing}")
    for contract in [
        "data-v2-target", "elite-v2", "Local-first protegido", "Centro de comando",
        "data-v2-growth-deck", "data-v2-ai-workspace", "Não é previsão de crescimento",
    ]:
        if contract not in V2_JS and contract not in elite_v2_webengine_source():
            raise RuntimeError(f"Contrato visual V2 ausente: {contract}")
    for contract in ["data-v2-content-tools", "data-v2-video-search", "data-v2-video-privacy"]:
        if contract not in CONTENT_HUB_JS:
            raise RuntimeError(f"Contrato do Content Hub ausente: {contract}")
    if ".v2-content-tools" not in CONTENT_HUB_CSS:
        raise RuntimeError("Design do Content Hub ausente")

    app = QApplication.instance() or QApplication([])
    captures = [
        capture(app, out, name="elite-v2-overview-desktop.png", size=(1440, 900)),
        capture(app, out, name="elite-v2-overview-mobile.png", size=(430, 900)),
        capture(app, out, name="elite-v2-content-hub-desktop.png", size=(1440, 900), tab="videos"),
        capture(app, out, name="elite-v2-ai-workspace-desktop.png", size=(1440, 900), tab="settings"),
    ]

    payload = {
        "ok": True,
        "ui_version": "elite-v2",
        "screenshots": [
            {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size}
            for path in captures
        ],
        "stable_dashboard_replaced": False,
        "youtube_write_actions_executed": False,
    }
    print(json.dumps(payload, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
