from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Callable
from urllib import request as urlrequest
import webbrowser


OLLAMA_INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"
DASHBOARD_URL = "https://creator.silvadigitaltech.com/dashboard"


def app_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".youtube-creator-agent")
    return Path(root) / "YouTubeCreatorAgent" / "LocalAI"


def install_state_path() -> Path:
    return app_dir() / "install-state.json"


def write_install_state(
    *,
    stage: str,
    status: str,
    percent: int | None = None,
    detail: str | None = None,
    model: str | None = None,
    estimated_download_mb: int | None = None,
) -> None:
    path = install_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stage": stage,
        "status": status,
        "percent": max(0, min(int(percent), 100)) if percent is not None else None,
        "detail": detail,
        "model": model,
        "estimated_download_mb": estimated_download_mb,
        "updated_at": int(time.time()),
    }
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def repo_src_root() -> Path:
    return Path(__file__).resolve().parents[1]


def import_runtime():
    src = repo_src_root() / "src"
    if src.exists() and str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from local_ai.capability import CapabilityProfile, classify_hardware, probe_hardware
    from local_ai.companion import ensure_config, save_config
    from local_ai.manifest import MANIFEST_VERSION, model_for_profile

    return (
        CapabilityProfile,
        classify_hardware,
        probe_hardware,
        ensure_config,
        save_config,
        model_for_profile,
        MANIFEST_VERSION,
    )


def find_ollama() -> Path | None:
    found = shutil.which("ollama")
    if found:
        return Path(found)
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Ollama" / "ollama.exe",
    ]
    return next((path for path in candidates if path.exists()), None)


def _percent(done: int, total: int | None) -> int | None:
    if not total or total <= 0:
        return None
    return max(0, min(int(done * 100 / total), 100))


def download(
    url: str,
    destination: Path,
    *,
    on_progress: Callable[[int, int | None], None] | None = None,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    existing = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": "YouTubeCreatorAgent-LocalAI/1.1"}
    if existing:
        headers["Range"] = f"bytes={existing}-"
    req = urlrequest.Request(url, headers=headers)
    mode = "ab" if existing else "wb"
    with urlrequest.urlopen(req, timeout=60) as response, partial.open(mode) as stream:
        if existing and getattr(response, "status", 200) != 206:
            stream.close()
            partial.unlink(missing_ok=True)
            return download(url, destination, on_progress=on_progress)
        content_length = int(response.headers.get("Content-Length") or 0)
        total = existing + content_length if content_length else None
        done = existing
        if on_progress:
            on_progress(done, total)
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            stream.write(chunk)
            done += len(chunk)
            if on_progress:
                on_progress(done, total)
    partial.replace(destination)


def verify_ollama_signature(installer: Path) -> None:
    if os.name != "nt":
        raise RuntimeError("O instalador automático da IA Local está disponível apenas no Windows nesta versão.")
    escaped = str(installer).replace("'", "''")
    command = (
        "$s=Get-AuthenticodeSignature -LiteralPath '"
        + escaped
        + "'; if($s.Status -ne 'Valid'){exit 2}; "
        + "$n=$s.SignerCertificate.Subject; if($n -notmatch 'Ollama'){exit 3}; Write-Output $n"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def install_ollama() -> Path:
    current = find_ollama()
    if current:
        return current
    with tempfile.TemporaryDirectory(prefix="yca-local-ai-") as temp:
        installer = Path(temp) / "OllamaSetup.exe"
        print("[1/5] Baixando runtime local oficial do Ollama...")

        def runtime_progress(done: int, total: int | None) -> None:
            pct = _percent(done, total)
            write_install_state(
                stage="runtime_download",
                status="running",
                percent=pct,
                detail="Baixando o runtime oficial do Ollama",
            )
            if pct is not None:
                print(f"Runtime Ollama: {pct}%", end="\r", flush=True)

        download(OLLAMA_INSTALLER_URL, installer, on_progress=runtime_progress)
        print()
        print("[2/5] Validando assinatura digital do instalador...")
        write_install_state(stage="runtime_verify", status="running", detail="Validando Authenticode do Ollama")
        verify_ollama_signature(installer)
        print("[3/5] Instalando runtime local...")
        write_install_state(stage="runtime_install", status="running", detail="Instalando o Ollama oficial")
        subprocess.run(
            [
                str(installer),
                "/VERYSILENT",
                "/NORESTART",
                "/SUPPRESSMSGBOXES",
            ],
            check=True,
            timeout=240,
        )
    deadline = time.time() + 45
    while time.time() < deadline:
        current = find_ollama()
        if current:
            return current
        time.sleep(1)
    raise RuntimeError("Ollama foi instalado, mas o executável não foi localizado.")


def ensure_ollama_running(ollama: Path) -> None:
    try:
        subprocess.run([str(ollama), "list"], check=True, capture_output=True, timeout=8)
        return
    except Exception:
        pass
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [str(ollama), "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            subprocess.run([str(ollama), "list"], check=True, capture_output=True, timeout=5)
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError("O runtime do Ollama foi iniciado, mas não ficou pronto a tempo.")


def pull_model(ollama: Path, model: str, *, estimated_download_mb: int | None = None) -> None:
    del ollama  # The local Ollama HTTP API provides structured progress more reliably than CLI text.
    print(f"[4/5] Preparando modelo {model}. O download é feito uma única vez...")
    body = json.dumps({"name": model, "stream": True}).encode("utf-8")
    req = urlrequest.Request(
        "http://127.0.0.1:11434/api/pull",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    last_pct = -1
    with urlrequest.urlopen(req, timeout=1800) as response:
        for raw in response:
            if not raw.strip():
                continue
            event = json.loads(raw.decode("utf-8"))
            if event.get("error"):
                raise RuntimeError(str(event["error"]))
            total = int(event.get("total") or 0)
            completed = int(event.get("completed") or 0)
            pct = _percent(completed, total)
            detail = str(event.get("status") or "Baixando modelo local")
            write_install_state(
                stage="model_download",
                status="running",
                percent=pct,
                detail=detail,
                model=model,
                estimated_download_mb=estimated_download_mb,
            )
            if pct is not None and pct != last_pct:
                last_pct = pct
                print(f"Modelo {model}: {pct}% - {detail}", end="\r", flush=True)
    print()


def installed_executable() -> Path:
    destination = app_dir() / "YCA-Local-AI.exe"
    source = Path(sys.executable if getattr(sys, "frozen", False) else __file__)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)
    return destination


def create_startup(executable: Path) -> None:
    startup = (
        Path(os.environ.get("APPDATA", str(Path.home())))
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
    )
    startup.mkdir(parents=True, exist_ok=True)
    launcher = startup / "YouTubeCreatorAgent-LocalAI.cmd"
    launcher.write_text(
        f'@echo off\r\nstart "" /min "{executable}" --serve\r\n',
        encoding="utf-8",
    )


def launch_companion(executable: Path) -> None:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [str(executable), "--serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def setup() -> int:
    if os.name != "nt":
        print("Esta versão automática da IA Local é destinada ao Windows.")
        return 2

    (
        CapabilityProfile,
        classify_hardware,
        probe_hardware,
        ensure_config,
        save_config,
        model_for_profile,
        manifest_version,
    ) = import_runtime()
    write_install_state(stage="hardware_probe", status="running", percent=0, detail="Detectando hardware local")
    snapshot = probe_hardware()
    profile = classify_hardware(snapshot)
    model = model_for_profile(profile)
    print(f"Hardware detectado: {snapshot.gpu_name or 'sem GPU NVIDIA compatível'}")
    print(f"Perfil selecionado: {profile.value}")

    if profile == CapabilityProfile.NATIVE_ONLY or model is None:
        write_install_state(
            stage="complete",
            status="native_only",
            percent=100,
            detail="Hardware mantido na Inteligência Nativa",
        )
        print("Este dispositivo continuará usando a Inteligência Nativa. A IA Local não será instalada.")
        return 0

    print(
        f"Modelo selecionado: {model.display_name} "
        f"(download estimado: {model.estimated_download_mb} MB; licença {model.license_name})."
    )
    write_install_state(
        stage="runtime_check",
        status="running",
        percent=2,
        detail="Verificando runtime local",
        model=model.ollama_model,
        estimated_download_mb=model.estimated_download_mb,
    )
    ollama = install_ollama()
    ensure_ollama_running(ollama)
    pull_model(ollama, model.ollama_model, estimated_download_mb=model.estimated_download_mb)

    config = ensure_config()
    config.update(
        {
            "profile": profile.value,
            "model": model.ollama_model,
            "hardware": snapshot.to_dict(),
            "manifest_version": manifest_version,
            "model_estimated_download_mb": model.estimated_download_mb,
            "installed_at": int(time.time()),
        }
    )
    save_config(config)

    executable = installed_executable()
    create_startup(executable)
    launch_companion(executable)
    token = str(config.get("token") or "")
    callback = f"{DASHBOARD_URL}#local-ai-token={token}"
    write_install_state(
        stage="complete",
        status="ready",
        percent=100,
        detail="IA Local instalada e pronta",
        model=model.ollama_model,
        estimated_download_mb=model.estimated_download_mb,
    )
    print("[5/5] IA Local pronta. Abrindo o Creator Agent...")
    webbrowser.open(callback)
    return 0


def self_test() -> int:
    (
        CapabilityProfile,
        classify_hardware,
        probe_hardware,
        _,
        _,
        model_for_profile,
        manifest_version,
    ) = import_runtime()
    snapshot = probe_hardware()
    profile = classify_hardware(snapshot)
    model = model_for_profile(profile)
    payload = {
        "ok": True,
        "manifest_version": manifest_version,
        "profile": profile.value,
        "model": model.ollama_model if model else None,
        "model_estimated_download_mb": model.estimated_download_mb if model else None,
        "hardware_probe": snapshot.to_dict(),
        "native_only_valid": CapabilityProfile.NATIVE_ONLY.value == "native_only",
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube Creator Agent Local AI")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        raise SystemExit(self_test())
    if args.serve:
        import_runtime()
        from local_ai.companion import serve

        serve()
        return
    try:
        raise SystemExit(setup())
    except SystemExit:
        raise
    except Exception as exc:
        write_install_state(stage="failed", status="error", detail=str(exc)[:500])
        print(f"Falha na instalação da IA Local: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
