#!/usr/bin/env python3
"""SCP ecs_switch_model.py to ECS and run with credentials from repo-root .env."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENV = ROOT / ".env"
SCRIPT = Path(__file__).resolve().parent / "ecs_switch_model.py"
HOST = "root@121.41.81.58"
REMOTE = "/tmp/ecs_switch_model.py"

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
    "deepseek_api_key",
    "user_llm_model",
    "judge_llm_model",
    "WEBSHARE_API_KEY",
    "WEBSHARE_PROXY_USERNAME",
    "WEBSHARE_PROXY_PASSWORD",
    "OVERSEAS_PROXY_HTTPS",
    "OVERSEAS_PROXY_HTTP",
    "V63_EVAL_TEMPERATURE",
    "V63_EVAL_THINKING",
]


def _get(raw: str, key: str) -> str:
    m = re.search(rf"^{re.escape(key)}=(.*)$", raw, re.M)
    return (m.group(1).strip() if m else "").strip()


def _load_fastapi_webshare(raw: str) -> str:
    if _get(raw, "WEBSHARE_API_KEY"):
        return raw
    fastapi_env = Path(r"D:\projects\fastapi_pdf_demo\fastapi_pdf_demo\.env")
    if not fastapi_env.is_file():
        return raw
    ws = ""
    for line in fastapi_env.read_text(encoding="utf-8").splitlines():
        if line.startswith("WEBSHARE_API_KEY="):
            ws = line.split("=", 1)[1].strip()
            break
    if ws:
        raw = raw.rstrip() + f"\nWEBSHARE_API_KEY={ws}\n"
    return raw


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: run_ecs_switch_model_from_local_env.py <doubao|deepseek|qwen|gemini|claude|gpt> [--restart-gateway]")
        sys.exit(1)

    if not ENV.is_file():
        print(f"missing {ENV}", file=sys.stderr)
        sys.exit(1)

    raw = _load_fastapi_webshare(ENV.read_text(encoding="utf-8"))

    # Resolve proxy URL locally (China VPS cannot call Webshare API reliably)
    proxy_dir = ROOT / "meituan-lifecare-agent" / "overseas-proxy"
    sys.path.insert(0, str(proxy_dir))
    import os

    for k in KEYS:
        v = _get(raw, k) or os.environ.get(k, "").strip()
        if v:
            os.environ[k] = v
    try:
        from proxy_helpers import pick_primary_proxy_url

        if not _get(raw, "OVERSEAS_PROXY_HTTPS") and not _get(raw, "OVERSEAS_PROXY_HTTP"):
            proxy = pick_primary_proxy_url()
            if proxy:
                raw = raw.rstrip() + f"\nOVERSEAS_PROXY_HTTPS={proxy}\n"
    except Exception as exc:
        print(f"warn: could not resolve proxy locally: {exc}", file=sys.stderr)

    env_exports = []
    for k in KEYS:
        v = _get(raw, k) or os.environ.get(k, "").strip()
        if v:
            env_exports.append(f"{k}={v!r}")

    subprocess.check_call(["scp", "-o", "BatchMode=yes", str(SCRIPT), f"{HOST}:{REMOTE}"])
    remote_cmd = " ".join(env_exports) + f" python3 {REMOTE} {sys.argv[1]} "
    if "--restart-gateway" in sys.argv[2:]:
        remote_cmd += "--restart-gateway"
    subprocess.check_call(["ssh", "-o", "BatchMode=yes", HOST, remote_cmd])


if __name__ == "__main__":
    main()
