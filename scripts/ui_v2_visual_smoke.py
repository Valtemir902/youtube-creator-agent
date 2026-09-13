from __future__ import annotations

import hashlib
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
from elite_v2_activity_ui import ACTIVITY_CSS, ACTIVITY_JS
from elite_v2_ai_execution_ui import AI_EXEC_CSS, AI_EXEC_JS
from elite_v2_ai_workspace import AI_WORKSPACE_CSS, AI_WORKSPACE_JS
from elite_v2_automation_ui import AUTOMATION_UI_CSS, AUTOMATION_UI_JS
from elite_v2_content_hub import CONTENT_HUB_CSS, CONTENT_HUB_JS
from elite_v2_growth import GROWTH_CSS, GROWTH_JS
from elite_v2_management_ui import MANAGEMENT_UI_CSS, MANAGEMENT_UI_JS
from elite_v2_reach_ui import REACH_UI_CSS, REACH_UI_JS
from elite_v2_seo_ui import SEO_UI_CSS, SEO_UI_JS
from elite_v2_ui import V2_CSS, V2_JS, elite_v2_webengine_source
from elite_v2_write_ui import WRITE_UI_CSS, WRITE_UI_JS


def pump(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.02)


def js_value(window: DesktopWindow, source: str, timeout: float = 4.0):
    result = {"done": False, "value": None}

    def done(value) -> None:
        result["value"] = value
        result["done"] = True

    window.web.page().runJavaScript(source, 0, done)
    deadline = time.monotonic() + timeout
    while not result["done"] and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.02)
    if not result["done"]:
        raise RuntimeError("Timeout ao validar o workspace visual via JavaScript")
    return result["value"]


def _tab_script(tab: str | None) -> list[tuple[str, str]]:
    if not tab:
        return []
    requested_tab = "overview" if tab == "playlists" else tab
    source = (
        "(()=>{let attempts=0;const openTarget=()=>{"
        f"const b=document.querySelector('.nav button[data-tab=\"{requested_tab}\"]');"
        "if(b){b.click();document.documentElement.dataset.v2VisualRequestedTab='"
        + tab
        + "';"
        + (
            "setTimeout(()=>{const p=document.getElementById('playlistManager');if(p){p.scrollIntoView({block:'start'});document.documentElement.dataset.v2VisualTargetReady='playlists';}},900);"
            if tab == "playlists"
            else "document.documentElement.dataset.v2VisualTargetReady='tab';"
        )
        + "return;}if(attempts++<60)setTimeout(openTarget,100);};setTimeout(openTarget,100);})();"
    )
    return [(f"yca-v2-visual-tab-{tab}", source)]


def _validate_visual_target(window: DesktopWindow, tab: str | None) -> dict:
    if not tab:
        source = "(()=>({requested:'overview',active:document.querySelector('.section.active')?.id||'',ready:true}))()"
    elif tab == "playlists":
        source = """(()=>{const p=document.getElementById('playlistManager');const r=p&&p.getBoundingClientRect();return {requested:'playlists',active:document.querySelector('.section.active')?.id||'',exists:!!p,visible:!!(p&&getComputedStyle(p).display!=='none'&&r&&r.bottom>0&&r.top<innerHeight),top:r?Math.round(r.top):null,ready:document.documentElement.dataset.v2VisualTargetReady||''};})()"""
    else:
        source = f"""(()=>({{requested:{json.dumps(tab)},active:document.querySelector('.section.active')?.id||'',ready:document.documentElement.dataset.v2VisualTargetReady||''}}))()"""
    state = js_value(window, source)
    if not isinstance(state, dict):
        raise RuntimeError(f"Estado visual inválido para {tab or 'overview'}: {state!r}")
    if tab == "playlists":
        if state.get("active") != "overview" or not state.get("exists") or not state.get("visible") or state.get("ready") != "playlists":
            raise RuntimeError(f"Workspace de playlists não foi realmente aberto: {state}")
    elif tab and (state.get("active") != tab or state.get("ready") != "tab"):
        raise RuntimeError(f"Aba visual solicitada não está ativa: {state}")
    elif not tab and state.get("active") != "overview":
        raise RuntimeError(f"Visão geral não está ativa: {state}")
    return state


def capture(app: QApplication, out: Path, *, name: str, size: tuple[int, int], tab: str | None = None) -> tuple[Path, dict]:
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

    pump(2.7)
    state = _validate_visual_target(window, tab)
    path = out / name
    if not window.grab().save(str(path)):
        window.close()
        raise RuntimeError(f"Falha ao salvar screenshot {name}")
    window.close()
    pump(0.3)
    app.processEvents()
    if not path.is_file() or path.stat().st_size < 20_000:
        raise RuntimeError(f"Screenshot inválido ou vazio: {path} ({path.stat().st_size if path.exists() else 0} bytes)")
    return path, state


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
    for contract in ["data-v2-growth-workspace", "/api/v2/analytics/timeseries", "Fonte oficial, sem estimativas"]:
        if contract not in GROWTH_JS:
            raise RuntimeError(f"Contrato Growth Analytics ausente: {contract}")
    for contract in ["data-v2-reach-card", "/api/v2/reporting/reach", "Carregar métricas oficiais"]:
        if contract not in REACH_UI_JS:
            raise RuntimeError(f"Contrato Reporting UI ausente: {contract}")
    for contract in ["data-v2-seo-lab", "SEO & Strategy Lab", "/api/v2/seo/video/"]:
        if contract not in SEO_UI_JS:
            raise RuntimeError(f"Contrato SEO Lab ausente: {contract}")
    for contract in ["data-v2-ai-controls", "Motor preferido", "Supervisionado", "Write Gateway"]:
        if contract not in AI_WORKSPACE_JS:
            raise RuntimeError(f"Contrato AI Workspace ausente: {contract}")
    for contract in ["data-v2-ai-exec", "/api/v2/ai/propose", "requires_explicit_approval"]:
        if contract not in AI_EXEC_JS:
            raise RuntimeError(f"Contrato AI execution ausente: {contract}")
    for contract in ["data-v2-write-control", "Ativar gerenciamento", "/api/v2/write-mode", "Readback obrigatório"]:
        if contract not in WRITE_UI_JS:
            raise RuntimeError(f"Contrato Write Gateway UI ausente: {contract}")
    for contract in ["data-v2-management", "/api/v2/manage/preview", "readback_verified", "thumbnail_replace"]:
        if contract not in MANAGEMENT_UI_JS:
            raise RuntimeError(f"Contrato Management UI ausente: {contract}")
    for contract in ["data-v2-activity", "/api/v2/activity", "Activity & Audit"]:
        if contract not in ACTIVITY_JS:
            raise RuntimeError(f"Contrato Activity UI ausente: {contract}")
    for contract in ["data-v2-automation", "/api/v2/automation/approve/", "Write Gateway"]:
        if contract not in AUTOMATION_UI_JS:
            raise RuntimeError(f"Contrato Automation UI ausente: {contract}")
    if any(
        token not in css
        for css, token in (
            (CONTENT_HUB_CSS, ".v2-content-tools"),
            (GROWTH_CSS, ".v2-timeseries-line"),
            (REACH_UI_CSS, ".v2-reach-card"),
            (SEO_UI_CSS, ".v2-seo-lab"),
            (AI_WORKSPACE_CSS, ".v2-ai-controls"),
            (AI_EXEC_CSS, ".v2-ai-exec-actions"),
            (WRITE_UI_CSS, ".v2-write-control"),
            (MANAGEMENT_UI_CSS, ".v2-manage"),
            (ACTIVITY_CSS, ".v2-activity"),
            (AUTOMATION_UI_CSS, ".v2-automation"),
        )
    ):
        raise RuntimeError("Design modular V2 incompleto")

    app = QApplication.instance() or QApplication([])
    specs = [
        ("elite-v2-overview-desktop.png", (1440, 900), None),
        ("elite-v2-overview-mobile.png", (430, 900), None),
        ("elite-v2-content-hub-videos.png", (1440, 900), "videos"),
        ("elite-v2-content-hub-playlists.png", (1440, 900), "playlists"),
        ("elite-v2-growth-seo-reporting.png", (1440, 900), "strategy"),
        ("elite-v2-ai-management.png", (1440, 900), "settings"),
        ("elite-v2-activity-automation.png", (1440, 900), "audit"),
    ]
    results = [capture(app, out, name=name, size=size, tab=tab) for name, size, tab in specs]
    captures = [item[0] for item in results]
    visual_states = [item[1] for item in results]
    hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in captures]
    workspace_hashes = hashes[2:]
    if len(set(workspace_hashes)) != len(workspace_hashes):
        raise RuntimeError(
            "Prova visual inválida: duas áreas funcionais produziram screenshots idênticos; "
            "o teste provavelmente não abriu o workspace solicitado."
        )

    payload = {
        "ok": True,
        "ui_version": "elite-v2",
        "screenshots": [
            {
                "path": str(path.relative_to(ROOT)),
                "bytes": path.stat().st_size,
                "sha256": digest,
                "visual_state": state,
            }
            for path, digest, state in zip(captures, hashes, visual_states, strict=True)
        ],
        "distinct_workspace_screenshots": len(set(workspace_hashes)),
        "semantic_workspace_validation": True,
        "stable_dashboard_replaced": False,
        "reporting_called_at_boot": False,
        "external_ai_called_at_boot": False,
        "youtube_write_actions_executed": False,
    }
    print(json.dumps(payload, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
