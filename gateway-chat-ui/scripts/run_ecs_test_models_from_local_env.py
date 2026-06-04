#!/usr/bin/env python3
"""Run model connectivity test on ECS with env from local .env + Webshare proxy."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENV = ROOT / ".env"
HOST = "root@121.41.81.58"
REMOTE = "/tmp/_ecs_test_models_inline.py"
SCRIPT = Path(__file__).resolve().parent / "_ecs_test_models_inline.py"

KEYS = [
    "ARK_API_KEY",
    "ARK_BASE_URL",
    "ARK_MODEL_NAME",
    "OPENROUTER_API_KEY",
    "deepseek_model",
    "openrouter_model2",
    "openrouter_model3",
    "openrouter_model4",
    "qwen_model",
    "qwen_api_key",
    "OVERSEAS_PROXY_HTTPS",
]


def _get(raw: str, key: str) -> str:
    m = re.search(rf"^{re.escape(key)}=(.*)$", raw, re.M)
    return (m.group(1).strip() if m else "").strip()


def main() -> None:
    raw = ENV.read_text(encoding="utf-8")
    fastapi = Path(r"D:\projects\fastapi_pdf_demo\fastapi_pdf_demo\.env")
    if fastapi.is_file() and not _get(raw, "WEBSHARE_API_KEY"):
        for line in fastapi.read_text(encoding="utf-8").splitlines():
            if line.startswith("WEBSHARE_API_KEY="):
                raw = raw.rstrip() + "\n" + line + "\n"

    import os

    sys.path.insert(0, str(ROOT / "meituan-lifecare-agent" / "overseas-proxy"))
    for line in raw.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    from proxy_helpers import pick_primary_proxy_url

    proxy = pick_primary_proxy_url()
    if proxy and not _get(raw, "OVERSEAS_PROXY_HTTPS"):
        raw = raw.rstrip() + f"\nOVERSEAS_PROXY_HTTPS={proxy}\n"

    exports = []
    for k in KEYS:
        v = _get(raw, k)
        if v:
            exports.append(f"{k}={v!r}")

    subprocess.check_call(["scp", "-o", "BatchMode=yes", str(SCRIPT), f"{HOST}:{REMOTE}"])
    cmd = " ".join(exports) + f" python3 {REMOTE}"
    subprocess.check_call(["ssh", "-o", "BatchMode=yes", HOST, cmd])


if __name__ == "__main__":
    main()
