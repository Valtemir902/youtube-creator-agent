from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOBILE = ROOT / "mobile"
DIST = ROOT / "dist"
OUT = DIST / "YouTube-Creator-Agent-Elite.apk"


def run(*args: str, cwd: Path = MOBILE) -> None:
    print(">", " ".join(args))
    subprocess.run(args, cwd=cwd, check=True)


def require(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise SystemExit(f"Dependência ausente: {name}")
    return path


def main() -> int:
    require("node")
    require("npm")
    if not os.environ.get("ANDROID_HOME") and not os.environ.get("ANDROID_SDK_ROOT"):
        raise SystemExit("ANDROID_HOME ou ANDROID_SDK_ROOT precisa apontar para o Android SDK.")
    if not (MOBILE / "node_modules").exists():
        run("npm", "install")
    run("npx", "cap", "sync", "android")
    gradlew = MOBILE / "android" / ("gradlew.bat" if os.name == "nt" else "gradlew")
    if not gradlew.exists():
        raise SystemExit("Projeto Android ainda não inicializado. Execute: cd mobile && npx cap add android")
    run(str(gradlew), "assembleDebug", cwd=gradlew.parent)
    apks = list((MOBILE / "android" / "app" / "build" / "outputs" / "apk").rglob("*.apk"))
    if not apks:
        raise SystemExit("Nenhum APK foi gerado.")
    source = max(apks, key=lambda p: p.stat().st_mtime)
    DIST.mkdir(exist_ok=True)
    shutil.copy2(source, OUT)
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    OUT.with_suffix(OUT.suffix + ".sha256").write_text(f"{digest}  {OUT.name}\n", encoding="utf-8")
    print(f"OK: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
