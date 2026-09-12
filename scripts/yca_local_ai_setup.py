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
from urllib import request as urlrequest
import webbrowser


OLLAMA_INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"
DASHBOARD_URL = "https://creator.silvadigitaltech.com/dashboard"


def app_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".youtube-creator-agent")
    return Path(root) / "YouTubeCreatorAgent" / "LocalAI"


def repo_src_root() -> Path:
    return Path(__file__).resolve().parents[1]


def import_runtime():
    src = repo_src_root() / "src"
    if src.exists() and str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from local_ai.capability import CapabilityProfile, classify_hardware, probe_hardware
    from local_ai.companion import ensure_config, save_config
    from local_ai.manifest import model_for_profile

    return CapabilityProfile, classify_hardware, probe_hardware, ensure_config, save_config, model_for_profile


def find_ollama() -> Path | None:
    found = shutil.which("ollama")
    if found:
        return Path(found)
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Ollama" / "ollama.exe",
    ]
    return next((path for path in candidates if path.exists()), None)


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    existing = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": "YouTubeCreatorAgent-LocalAI/1.0"}
    if existing:
        headers["Range"] = f"bytes={existing}-"
    req = urlrequest.Request(url, headers=headers)
    mode = "ab" if existing else "wb"
    with urlrequest.urlopen(req, timeout=60) as response, partial.open(mode) as stream:
        # Some servers ignore Range and return the entire file. Restart instead
        # of corrupting the installer by appending duplicate bytes.
        if existing and getattr(response, "status", 200) != 206:
            stream.close()
            partial.unlink(missing_ok=True)
            return download(url, destination)
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            stream.write(chunk)
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
        download(OLLAMA_INSTALLER_URL, installer)
        print("[2/5] Validando assinatura digital do instalador...")
        verify_ollama_signature(installer)
        print("[3/5] Instalando runtime local...")
        subprocess.run([str(installer), "/S"], check=True, timeout=180)
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
    time.sleep(3)


def pull_model(ollama: Path, model: str) -> None:
    print(f"[4/5] Preparando modelo {model}. O download é feito uma única vez...")
    subprocess.run([str(ollama), "pull", model], check=True)


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

    CapabilityProfile, classify_hardware, probe_hardware, ensure_config, save_config, model_for_profile = import_runtime()
    snapshot = probe_hardware()
    profile = classify_hardware(snapshot)
    model = model_for_profile(profile)
    print(f"Hardware detectado: {snapshot.gpu_name or 'sem GPU NVIDIA compatível'}")
    print(f"Perfil selecionado: {profile.value}")

    if profile == CapabilityProfile.NATIVE_ONLY or model is None:
        print("Este dispositivo continuará usando a Inteligência Nativa. A IA Local não será instalada.")
        return 0

    ollama = install_ollama()
    ensure_ollama_running(ollama)
    pull_model(ollama, model.ollama_model)

    config = ensure_config()
    config.update(
        {
            "profile": profile.value,
            "model": model.ollama_model,
            "hardware": snapshot.to_dict(),
            "installed_at": int(time.time()),
        }
    )
    save_config(config)

    executable = installed_executable()
    create_startup(executable)
    launch_companion(executable)
    token = str(config.get("token") or "")
    callback = f"{DASHBOARD_URL}#local-ai-token={token}"
    print("[5/5] IA Local pronta. Abrindo o Creator Agent...")
    webbrowser.open(callback)
    return 0


def self_test() -> int:
    CapabilityProfile, classify_hardware, probe_hardware, _, _, model_for_profile = import_runtime()
    snapshot = probe_hardware()
    profile = classify_hardware(snapshot)
    model = model_for_profile(profile)
    payload = {
        "ok": True,
        "profile": profile.value,
        "model": model.ollama_model if model else None,
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
    raise SystemExit(setup())


if __name__ == "__main__":
    main()
