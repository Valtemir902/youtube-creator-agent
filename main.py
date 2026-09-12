from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _desktop_self_test() -> int:
    """Exercise the exact Qt imports that previously failed in packaged builds."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        import PySide6
        import shiboken6
        from PySide6.QtCore import qVersion
        from PySide6.QtWidgets import QApplication, QWidget

        # Import the real desktop entry module so transitive Qt/module failures are caught.
        import app_elite_v7  # noqa: F401

        app = QApplication.instance() or QApplication([])
        probe = QWidget()
        probe.setWindowTitle("YCA self-test")
        probe.close()
        app.processEvents()
        payload = {
            "ok": True,
            "qt_version": qVersion(),
            "pyside_version": getattr(PySide6, "__version__", "unknown"),
            "shiboken_version": getattr(shiboken6, "__version__", "unknown"),
        }
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 97


def main() -> int:
    if "--self-test" in sys.argv:
        return _desktop_self_test()

    from app_elite_v7 import run

    return int(run())


if __name__ == "__main__":
    raise SystemExit(main())
