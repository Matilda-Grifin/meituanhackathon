#!/usr/bin/env python3
"""
Switch OpenClaw on this host to Volcengine Ark (豆包 OpenAI-compatible).

Reads credentials from environment (no secrets in repo):
  ARK_API_KEY       required
  ARK_BASE_URL      optional, default https://ark.cn-beijing.volces.com/api/v3
  ARK_MODEL_NAME    optional, default doubao-seed-2-0-mini-260428

Edits:
  ~/.openclaw/openclaw.json  — models.providers.volcark, agents.defaults, env.ARK_API_KEY
  ~/.openclaw/agents/main/sessions/sessions.json — per-session model + clear openrouter auth override

Restart gateway yourself, or pass --restart-gateway to kill/start the node process on :18789.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

CFG = Path("/root/.openclaw/openclaw.json")
SESS = Path("/root/.openclaw/agents/main/sessions/sessions.json")
PROVIDER_ID = "volcark"


def _backup(p: Path) -> Path:
    ts = int(time.time() * 1000)
    bak = p.with_suffix(p.suffix + f".bak-ark-{ts}")
    shutil.copy2(p, bak)
    return bak


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--restart-gateway",
        action="store_true",
        help="kill existing openclaw gateway on --port 18789 and start in background",
    )
    args = ap.parse_args()

    key = os.environ.get("ARK_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set ARK_API_KEY in the environment")

    base = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").strip().rstrip("/")
    model_id = os.environ.get("ARK_MODEL_NAME", "doubao-seed-2-0-mini-260428").strip()

    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    _backup(CFG)

    env = cfg.setdefault("env", {})
    env["ARK_API_KEY"] = key

    models_root = cfg.setdefault("models", {})
    models_root["mode"] = models_root.get("mode") or "merge"
    providers = models_root.setdefault("providers", {})
    providers[PROVIDER_ID] = {
        "baseUrl": base,
        "apiKey": "${ARK_API_KEY}",
        "api": "openai-completions",
        "models": [
            {
                "id": model_id,
                "name": f"Volcengine Ark {model_id}",
                "reasoning": False,
                "input": ["text"],
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                "contextWindow": 256000,
                "contextTokens": 128000,
                "maxTokens": 8192,
                # Only keys supported by this OpenClaw release (see gateway config-tools docs).
                "compat": {"requiresStringContent": True},
            },
        ],
    }

    ad = cfg.setdefault("agents", {}).setdefault("defaults", {})
    mp = ad.setdefault("model", {})
    primary = f"{PROVIDER_ID}/{model_id}"
    mp["primary"] = primary

    am = ad.setdefault("models", {})
    # Drop known-broken OpenRouter slugs; keep other entries for Feishu etc. if present.
    drop_substrings = ("trinity-large-preview", "autostepfun/step-3.5-flash")
    for k in list(am.keys()):
        if any(s in k for s in drop_substrings):
            del am[k]
    am[primary] = {"alias": "豆包 (Ark)"}
    am[f"{PROVIDER_ID}/*"] = {}

    CFG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {CFG}: primary={primary!r}, provider baseUrl={base!r}")

    if SESS.exists():
        _backup(SESS)
        store = json.loads(SESS.read_text(encoding="utf-8"))
        for sk, row in store.items():
            if not isinstance(row, dict):
                continue
            row["model"] = model_id
            row["modelProvider"] = PROVIDER_ID
            if row.get("authProfileOverride") == "openrouter:default":
                row.pop("authProfileOverride", None)
                row.pop("authProfileOverrideSource", None)
                row.pop("authProfileOverrideCompactionCount", None)
        SESS.write_text(json.dumps(store, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {SESS}: all sessions -> {PROVIDER_ID}/{model_id}, cleared openrouter auth override")

    if args.restart_gateway:
        subprocess.run(["pkill", "-f", "openclaw/dist/index.js gateway"], check=False)
        time.sleep(1)
        subprocess.Popen(
            [
                "/usr/bin/node",
                "/usr/lib/node_modules/openclaw/dist/index.js",
                "gateway",
                "--port",
                "18789",
            ],
            start_new_session=True,
            stdout=open("/root/openclaw-gateway.log", "a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )
        print("gateway restart: Popen node ... gateway --port 18789 (log /root/openclaw-gateway.log)")


if __name__ == "__main__":
    main()
