from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import venv
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = ROOT / "build" / "windows-release"
ENV_DIR = BUILD_ROOT / ".venv"
PY = ENV_DIR / "Scripts" / "python.exe"
DIST_DIR = BUILD_ROOT / "dist"
WORK_DIR = BUILD_ROOT / "work"
ARTIFACT_DIR = ROOT / "artifacts" / "windows"
ARTIFACT = ARTIFACT_DIR / "YouTube-Creator-Agent-Elite.exe"
HASH_FILE = ARTIFACT.with_suffix(ARTIFACT.suffix + ".sha256")
REPORT_FILE = ARTIFACT_DIR / "build-report.json"
SPEC = ROOT / "desktop_windows.spec"
BUILD_REQ = ROOT / "requirements-build-windows.txt"


def run(args: list[str], *, cwd: Path = ROOT, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    print(">", " ".join(map(str, args)), flush=True)
    return subprocess.run([str(x) for x in args], cwd=cwd, check=True, timeout=timeout, text=True, env=os.environ.copy())


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def select_python() -> list[str]:
    candidates: list[list[str]] = []
    py_launcher = shutil.which("py")
    if py_launcher:
        candidates += [[py_launcher, "-3.11"], [py_launcher, "-3.12"], [py_launcher, "-3.10"]]
    candidates.append([sys.executable])
    for cmd in candidates:
        try:
            cp = subprocess.run(cmd + ["-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"], capture_output=True, text=True, timeout=10)
            if cp.returncode == 0 and cp.stdout.strip() in {"3.10", "3.11", "3.12"}:
                print(f"Python de build: {' '.join(cmd)} ({cp.stdout.strip()})")
                return cmd
        except Exception:
            continue
    raise SystemExit("Build Windows exige Python 3.10, 3.11 ou 3.12. Instale uma dessas versoes antes de gerar o release.")


def create_clean_env() -> None:
    if BUILD_ROOT.exists():
        shutil.rmtree(BUILD_ROOT)
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    base_python = select_python()
    if len(base_python) == 1 and Path(base_python[0]).resolve() == Path(sys.executable).resolve():
        venv.EnvBuilder(with_pip=True, clear=True).create(ENV_DIR)
    else:
        run(base_python + ["-m", "venv", str(ENV_DIR)])
    run([str(PY), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    run([str(PY), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])
    run([str(PY), "-m", "pip", "install", "--upgrade", "--force-reinstall", "-r", str(BUILD_REQ)])


def qt_preflight() -> dict[str, str | bool]:
    code = (
        "import json, PySide6, shiboken6; "
        "from PySide6.QtCore import qVersion; "
        "from PySide6.QtWidgets import QApplication, QWidget; "
        "from PySide6.QtWebEngineWidgets import QWebEngineView; "
        "app=QApplication([]); w=QWidget(); w.close(); "
        "print(json.dumps({'qt':qVersion(),'pyside':PySide6.__version__,'shiboken':shiboken6.__version__,'webengine':True}))"
    )
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    cp = subprocess.run([str(PY), "-c", code], cwd=ROOT, env=env, text=True, capture_output=True, timeout=60)
    if cp.returncode != 0:
        raise SystemExit(f"Qt/WebEngine preflight falhou antes do empacotamento:\n{cp.stdout}\n{cp.stderr}")
    info = json.loads(cp.stdout.strip().splitlines()[-1])
    if not (info["pyside"] == info["shiboken"] == "6.7.3") or not info.get("webengine"):
        raise SystemExit(f"Runtime Qt/WebEngine inconsistente: {info}")
    print("Qt/WebEngine preflight OK:", info)
    return info


def build_exe() -> Path:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    run([
        str(PY), "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", str(DIST_DIR), "--workpath", str(WORK_DIR), str(SPEC),
    ], timeout=3600)
    exe = DIST_DIR / "YouTube-Creator-Agent-Elite.exe"
    if not exe.is_file() or exe.stat().st_size < 1_000_000:
        raise SystemExit(f"EXE final ausente ou invalido: {exe}")
    return exe


def smoke_test(exe: Path) -> tuple[float, dict[str, object]]:
    started = time.perf_counter()
    cp = subprocess.run([str(exe), "--self-test"], cwd=ROOT, text=True, capture_output=True, timeout=120)
    elapsed_ms = (time.perf_counter() - started) * 1000
    if cp.returncode != 0:
        raise SystemExit(
            "EXE foi gerado mas REPROVOU o smoke test. Ele nao sera publicado em artifacts/.\n"
            f"exit={cp.returncode}\nstdout={cp.stdout}\nstderr={cp.stderr}"
        )
    lines = [line.strip() for line in cp.stdout.splitlines() if line.strip()]
    if not lines:
        raise SystemExit("EXE smoke test nao retornou payload de verificacao.")
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Payload do self-test invalido: {lines[-1]}") from exc
    required_true = {
        "desktop_local_first",
        "youtube_oauth_local",
        "qt_webengine",
        "native_python_engine",
        "local_fact_cache",
    }
    if payload.get("desktop_ui") != "professional_local_dashboard":
        raise SystemExit(f"Build nao empacotou o dashboard profissional local: {payload}")
    for field in required_true:
        if payload.get(field) is not True:
            raise SystemExit(f"Self-test local-first falhou em {field}: {payload}")
    if payload.get("cloud_session_required") is not False:
        raise SystemExit(f"EXE ainda depende de sessao cloud: {payload}")
    if payload.get("youtube_api_transport") != "direct_from_pc":
        raise SystemExit(f"YouTube nao esta ligado diretamente ao PC: {payload}")
    if payload.get("local_ai_provider") != "ollama":
        raise SystemExit(f"IA local nao foi validada: {payload}")
    if payload.get("external_ai_called") is not False or payload.get("youtube_write_actions_executed") is not False:
        raise SystemExit(f"Self-test violou politica passiva de seguranca: {payload}")
    print(
        f"EXE smoke test OK em {elapsed_ms:.0f} ms, UI={payload.get('desktop_ui')}, "
        "motor=python_local_first, IA=ollama, cloud_session=false"
    )
    return elapsed_ms, payload


def authenticode_status(path: Path) -> bool:
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        return False
    cp = subprocess.run([ps, "-NoProfile", "-Command", f"(Get-AuthenticodeSignature -LiteralPath '{path}').Status"], capture_output=True, text=True)
    return cp.returncode == 0 and cp.stdout.strip().lower() == "valid"


def main() -> int:
    if os.name != "nt":
        raise SystemExit("Este build deve ser executado no Windows.")
    create_clean_env()
    qt = qt_preflight()
    run([str(PY), "-m", "compileall", "-q", "src", "main.py"])
    exe = build_exe()
    smoke_ms, smoke_payload = smoke_test(exe)

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for old in ARTIFACT_DIR.glob("*"):
        if old.is_file():
            old.unlink()
    shutil.copy2(exe, ARTIFACT)
    digest = sha256(ARTIFACT)
    HASH_FILE.write_text(f"{digest}  {ARTIFACT.name}\n", encoding="utf-8")
    report = {
        "platform": "windows",
        "status": "success",
        "git_sha": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
        "build_time_utc": datetime.now(timezone.utc).isoformat(),
        "artifact": str(ARTIFACT.relative_to(ROOT)),
        "sha256": digest,
        "size_bytes": ARTIFACT.stat().st_size,
        "smoke_test": True,
        "smoke_test_ms": round(smoke_ms, 2),
        "desktop_ui": smoke_payload.get("desktop_ui"),
        "desktop_local_first": smoke_payload.get("desktop_local_first"),
        "cloud_session_required": smoke_payload.get("cloud_session_required"),
        "youtube_oauth_local": smoke_payload.get("youtube_oauth_local"),
        "youtube_api_transport": smoke_payload.get("youtube_api_transport"),
        "native_python_engine": smoke_payload.get("native_python_engine"),
        "local_ai_provider": smoke_payload.get("local_ai_provider"),
        "local_fact_cache": smoke_payload.get("local_fact_cache"),
        "qt": qt,
        "authenticode_signed": authenticode_status(ARTIFACT),
        "external_ai_called": False,
        "youtube_write_actions_executed": False,
    }
    REPORT_FILE.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nARTEFATO OFICIAL: {ARTIFACT}")
    print(f"SHA256: {digest}")
    print("UI OFICIAL: professional_local_dashboard")
    print("MOTOR LOCAL: python_local_first")
    print("IA LOCAL: Ollama")
    print("SESSAO CLOUD: nao utilizada")
    print("Somente este arquivo em artifacts/windows/ deve ser usado para teste.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
