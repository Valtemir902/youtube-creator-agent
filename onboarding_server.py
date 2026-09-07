from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import uvicorn


def main() -> None:
    host = os.environ.get("YCA_ONBOARDING_HOST", "127.0.0.1")
    port = int(os.environ.get("YCA_ONBOARDING_PORT", "8080"))
    uvicorn.run(
        "creator_service.extended_onboarding:create_app",
        factory=True,
        host=host,
        port=port,
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("YCA_FORWARDED_ALLOW_IPS", "127.0.0.1"),
    )


if __name__ == "__main__":
    main()
