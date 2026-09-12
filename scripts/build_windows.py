from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
OUT = DIST / "YouTube-Creator-Agent-Elite.exe"


def run(*args: str) -> None:
    print(">", " ".join(args))
    subprocess.run(args, cwd=ROOT, check=True)


def main() -> int:
    if sys.platform != "win32":
        raise SystemExit("Este build deve ser executado no Windows.")
    run(sys.executable, "-m", "compileall", "-q", "src")
    run(sys.executable, "-m", "pytest", "-q")
    if shutil.which("pyinstaller") is None:
        run(sys.executable, "-m", "pip", "install", "pyinstaller")
    run("pyinstaller", "--noconfirm", "app_gui.spec")
    DIST.mkdir(exist_ok=True)
    candidates = list((ROOT / "dist").glob("*.exe"))
    if not candidates:
        raise SystemExit("Nenhum EXE foi gerado.")
    source = max(candidates, key=lambda p: p.stat().st_mtime)
    if source.resolve() != OUT.resolve():
        shutil.copy2(source, OUT)
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    OUT.with_suffix(OUT.suffix + ".sha256").write_text(f"{digest}  {OUT.name}\n", encoding="utf-8")
    print(f"OK: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
