#!/usr/bin/env python3
"""
Switch OpenClaw default model among 11 Coding Plan test models.
Called by gateway_context_api /api/switch-model endpoint.

Usage:
  python3 ecs_switch_model_v2.py "doubao-seed-2.0-code"
  python3 ecs_switch_model_v2.py "deepseek-v4-flash"
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

CFG = Path("/root/.openclaw/openclaw.json")
SESS = Path("/root/.openclaw/agents/main/sessions/sessions.json")
GATEWAY_LOG = Path("/root/openclaw-gateway.log")

# Coding Plan API settings
CODING_PLAN_BASE_URL = "https://ark.cn-beijing.volces.com/api/coding/v3"
# Read from environment to avoid committing secrets. Export on the host, e.g.:
#   export CODINGPLAN_API_KEY="<your-ark-key>"
CODING_PLAN_API_KEY = os.environ.get("CODINGPLAN_API_KEY", "")

# All 11 test models available via Coding Plan
TEST_MODELS = {
    "doubao-seed-2.0-code":   {"name": "豆包 Seed 2.0 Code", "reasoning": True, "contextWindow": 256000, "maxTokens": 8192},
    "doubao-seed-2.0-pro":    {"name": "豆包 Seed 2.0 Pro",  "reasoning": True, "contextWindow": 256000, "maxTokens": 8192},
    "doubao-seed-2.0-lite":   {"name": "豆包 Seed 2.0 Lite", "reasoning": True, "contextWindow": 256000, "maxTokens": 8192},
    "doubao-seed-code":       {"name": "豆包 Seed Code",      "reasoning": True, "contextWindow": 256000, "maxTokens": 8192},
    "minimax-m2.7":           {"name": "MiniMax M2.7",        "reasoning": True, "contextWindow": 256000, "maxTokens": 8192},
    "minimax-m3":             {"name": "MiniMax M3",          "reasoning": True, "contextWindow": 256000, "maxTokens": 8192},
    "glm-4.7":                {"name": "GLM 4.7",             "reasoning": True, "contextWindow": 200000, "maxTokens": 8192},
    "deepseek-v4-flash":      {"name": "DeepSeek V4 Flash",   "reasoning": True, "contextWindow": 256000, "maxTokens": 8192},
    "deepseek-v4-pro":        {"name": "DeepSeek V4 Pro",     "reasoning": True, "contextWindow": 256000, "maxTokens": 8192},
    "kimi-k2.6":              {"name": "Kimi K2.6",           "reasoning": True, "contextWindow": 256000, "maxTokens": 8192},
    "kimi-k2.7-code":         {"name": "Kimi K2.7 Code",      "reasoning": True, "contextWindow": 256000, "maxTokens": 8192},
}


def backup(p: Path) -> Path:
    ts = int(time.time() * 1000)
    bak = p.with_suffix(p.suffix + f".bak-model-{ts}")
    shutil.copy2(p, bak)
    return bak


def switch_model(model_id: str) -> dict:
    if model_id not in TEST_MODELS:
        return {"ok": False, "error": f"Unknown model: {model_id}", "available": list(TEST_MODELS.keys())}

    if not CODING_PLAN_API_KEY:
        return {"ok": False, "error": "CODINGPLAN_API_KEY env var is not set on the host"}

    model_info = TEST_MODELS[model_id]
    provider_id = "codingplan"
    primary = f"codingplan/{model_id}"

    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    backup(CFG)

    # Set env
    cfg.setdefault("env", {})["CODINGPLAN_API_KEY"] = CODING_PLAN_API_KEY

    # Configure provider
    models_root = cfg.setdefault("models", {})
    models_root["mode"] = models_root.get("mode") or "merge"
    providers = models_root.setdefault("providers", {})

    providers[provider_id] = {
        "baseUrl": CODING_PLAN_BASE_URL,
        "apiKey": "${CODINGPLAN_API_KEY}",
        "api": "openai-completions",
        "models": [
            {
                "id": model_id,
                "name": f"CodingPlan {model_info['name']}",
                "reasoning": model_info["reasoning"],
                "input": ["text"],
                "contextWindow": model_info["contextWindow"],
                "maxTokens": model_info["maxTokens"],
            }
        ],
    }

    # Set as primary model
    ad = cfg.setdefault("agents", {}).setdefault("defaults", {})
    mp = ad.setdefault("model", {})
    mp["primary"] = primary

    # Model alias
    entry = ad.setdefault("models", {}).setdefault(primary, {})
    if not isinstance(entry, dict):
        entry = {}
        ad["models"][primary] = entry
    entry["alias"] = model_info["name"]

    # Disable thinking for non-reasoning models
    ad["thinkingDefault"] = "medium"

    CFG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {CFG}: primary={primary!r}")

    # Update sessions
    if SESS.exists():
        backup(SESS)
        store = json.loads(SESS.read_text(encoding="utf-8"))
        for row in store.values():
            if isinstance(row, dict):
                row["model"] = model_id
                row["modelProvider"] = provider_id
                row.pop("authProfileOverride", None)
                row.pop("authProfileOverrideSource", None)
                row.pop("authProfileOverrideCompactionCount", None)
        SESS.write_text(json.dumps(store, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {SESS}: sessions -> {provider_id}/{model_id}")

    # Restart gateway
    subprocess.run(["pkill", "-f", "openclaw/dist/index.js gateway"], check=False)
    time.sleep(2)
    subprocess.Popen(
        ["/usr/bin/node", "/usr/lib/node_modules/openclaw/dist/index.js", "gateway", "--port", "18789"],
        start_new_session=True,
        stdout=open(GATEWAY_LOG, "a", encoding="utf-8"),
        stderr=subprocess.STDOUT,
    )
    print("gateway restarted")

    return {"ok": True, "model": model_id, "name": model_info["name"], "primary": primary}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python3 {sys.argv[0]} <model_id>")
        print(f"Available models: {', '.join(TEST_MODELS.keys())}")
        sys.exit(1)

    result = switch_model(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result.get("ok") else 1)
