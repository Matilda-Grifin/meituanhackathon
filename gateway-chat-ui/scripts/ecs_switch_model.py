#!/usr/bin/env python3
"""
Switch OpenClaw default model among the 6 evaluation models.

Usage on ECS:
  python3 ecs_switch_model.py doubao --restart-gateway
  python3 ecs_switch_model.py gemini --restart-gateway

Reads credentials from environment (injected by run_ecs_switch_model_from_local_env.py):
  ARK_* / OPENROUTER_API_KEY / qwen_api_key / WEBSHARE_* / OVERSEAS_PROXY_HTTPS
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
PROXY_ENV = Path("/root/.openclaw/gateway.proxy.env")
GATEWAY_LOG = Path("/root/openclaw-gateway.log")

NO_PROXY = (
    "localhost,127.0.0.1,ark.cn-beijing.volces.com,open.feishu.cn,feishu.cn,"
    "larkoffice.com,.volces.com,dashscope.aliyuncs.com,.aliyuncs.com"
)

# 选型批次冻结参数（6.3 可通过环境变量覆盖）
EVAL_TEMPERATURE = float(os.environ.get("V63_EVAL_TEMPERATURE", os.environ.get("EVAL_TEMPERATURE", "0.3")))
EVAL_THINKING_DEFAULT = os.environ.get("V63_EVAL_THINKING", os.environ.get("EVAL_THINKING_DEFAULT", "medium"))


def _backup(p: Path) -> Path:
    ts = int(time.time() * 1000)
    bak = p.with_suffix(p.suffix + f".bak-model-{ts}")
    shutil.copy2(p, bak)
    return bak


def _openrouter_models() -> list[dict]:
    return [
        {
            "id": os.environ.get("deepseek_model", "deepseek/deepseek-v4-flash"),
            "name": "DeepSeek V4 Flash (OR)",
            "reasoning": True,
            "input": ["text"],
            "contextWindow": 1048576,
            "maxTokens": 8192,
        },
        {
            "id": os.environ.get("openrouter_model2", "google/gemini-3-flash-preview"),
            "name": "Gemini 3 Flash Preview",
            "reasoning": True,
            "input": ["text", "image"],
            "contextWindow": 1048576,
            "maxTokens": 8192,
        },
        {
            "id": os.environ.get("openrouter_model3", "anthropic/claude-opus-4.7"),
            "name": "Claude Opus 4.7",
            "reasoning": True,
            "input": ["text"],
            "contextWindow": 200000,
            "maxTokens": 8192,
        },
        {
            "id": os.environ.get("openrouter_model4", "openai/gpt-5.5"),
            "name": "GPT-5.5",
            "reasoning": True,
            "input": ["text"],
            "contextWindow": 256000,
            "maxTokens": 8192,
        },
    ]


def _profiles() -> dict[str, dict]:
    ark_model = os.environ.get("ARK_MODEL_NAME", "doubao-seed-2-0-mini-260428")
    qwen_model = os.environ.get("qwen_model", "qwen3.6-plus")
    or_models = _openrouter_models()
    return {
        "doubao": {
            "primary": f"volcark/{ark_model}",
            "provider": "volcark",
            "model_id": ark_model,
            "needs_proxy": False,
            "alias": "豆包 (Ark)",
        },
        "deepseek": {
            "primary": f"openrouter/{or_models[0]['id']}",
            "provider": "openrouter",
            "model_id": or_models[0]["id"],
            "needs_proxy": True,
            "alias": "DeepSeek V4 Flash",
        },
        "qwen": {
            "primary": f"dashscope/{qwen_model}",
            "provider": "dashscope",
            "model_id": qwen_model,
            "needs_proxy": False,
            "alias": "Qwen 3.6 Plus",
        },
        "gemini": {
            "primary": f"openrouter/{or_models[1]['id']}",
            "provider": "openrouter",
            "model_id": or_models[1]["id"],
            "needs_proxy": True,
            "alias": "Gemini 3 Flash",
        },
        "claude": {
            "primary": f"openrouter/{or_models[2]['id']}",
            "provider": "openrouter",
            "model_id": or_models[2]["id"],
            "needs_proxy": True,
            "alias": "Claude Opus 4.7",
        },
        "gpt": {
            "primary": f"openrouter/{or_models[3]['id']}",
            "provider": "openrouter",
            "model_id": or_models[3]["id"],
            "needs_proxy": True,
            "alias": "GPT-5.5",
        },
    }


def _resolve_proxy_url() -> str | None:
    https = os.environ.get("OVERSEAS_PROXY_HTTPS", "").strip()
    if https:
        return https
    http = os.environ.get("OVERSEAS_PROXY_HTTP", "").strip()
    if http:
        return http
    return None


def _write_proxy_env(needs_proxy: bool) -> None:
    if not needs_proxy:
        if PROXY_ENV.exists():
            PROXY_ENV.unlink()
        print("proxy env cleared (domestic model)")
        return
    proxy = _resolve_proxy_url()
    if not proxy:
        raise SystemExit(
            "Overseas model requires OVERSEAS_PROXY_HTTPS (IPRoyal) or OVERSEAS_PROXY_HTTP in env"
        )
    PROXY_ENV.write_text(
        f"HTTPS_PROXY={proxy}\nHTTP_PROXY={proxy}\nNO_PROXY={NO_PROXY}\n",
        encoding="utf-8",
    )
    masked = proxy.split("@")[-1] if "@" in proxy else proxy
    print(f"wrote {PROXY_ENV} -> ***@{masked}")


def _configure_providers(cfg: dict) -> None:
    env = cfg.setdefault("env", {})
    ark_key = os.environ.get("ARK_API_KEY", "").strip()
    or_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    qwen_key = os.environ.get("qwen_api_key", "").strip()
    if not ark_key:
        raise SystemExit("ARK_API_KEY required")
    env["ARK_API_KEY"] = ark_key
    if or_key:
        env["OPENROUTER_API_KEY"] = or_key
    if qwen_key:
        env["DASHSCOPE_API_KEY"] = qwen_key

    base = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").strip().rstrip("/")
    ark_model = os.environ.get("ARK_MODEL_NAME", "doubao-seed-2-0-mini-260428").strip()
    qwen_model = os.environ.get("qwen_model", "qwen3.6-plus").strip()

    models_root = cfg.setdefault("models", {})
    models_root["mode"] = models_root.get("mode") or "merge"
    providers = models_root.setdefault("providers", {})

    providers["volcark"] = {
        "baseUrl": base,
        "apiKey": "${ARK_API_KEY}",
        "api": "openai-completions",
        "models": [
            {
                "id": ark_model,
                "name": f"Volcengine Ark {ark_model}",
                "reasoning": True,
                "input": ["text"],
                "contextWindow": 256000,
                "maxTokens": 8192,
                "compat": {"requiresStringContent": True},
            }
        ],
    }

    if or_key:
        providers["openrouter"] = {
            "baseUrl": "https://openrouter.ai/api/v1",
            "apiKey": "${OPENROUTER_API_KEY}",
            "api": "openai-completions",
            "models": _openrouter_models(),
        }

    if qwen_key:
        providers["dashscope"] = {
            "baseUrl": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "apiKey": "${DASHSCOPE_API_KEY}",
            "api": "openai-completions",
            "models": [
                {
                    "id": qwen_model,
                    "name": f"DashScope {qwen_model}",
                    "reasoning": True,
                    "input": ["text"],
                    "contextWindow": 1000000,
                    "maxTokens": 66000,
                }
            ],
        }


def _apply_eval_runtime_defaults(cfg: dict, *, primary: str, alias: str) -> None:
    """冻结选型批次：temperature + 全局 thinking（推理）默认。"""
    ad = cfg.setdefault("agents", {}).setdefault("defaults", {})
    ad["thinkingDefault"] = EVAL_THINKING_DEFAULT
    ad.setdefault("params", {})["temperature"] = EVAL_TEMPERATURE
    entry = ad.setdefault("models", {}).setdefault(primary, {})
    if not isinstance(entry, dict):
        entry = {}
        ad["models"][primary] = entry
    entry["alias"] = alias
    params = entry.setdefault("params", {})
    params["temperature"] = EVAL_TEMPERATURE
    # DashScope 兼容 OpenAI 接口：thinking 走顶层 enable_thinking
    if primary.startswith("dashscope/"):
        params["qwenThinkingFormat"] = "top-level"
        thinking_on = str(EVAL_THINKING_DEFAULT).lower() not in ("off", "false", "0", "none")
        if thinking_on:
            params["enable_thinking"] = True
            # medium thinking_budget=32768 时 max_completion_tokens 须更大（DashScope 校验）
            params["maxTokens"] = 66000
            ad.setdefault("params", {})["maxTokens"] = 66000


def _restart_gateway() -> None:
    subprocess.run(["pkill", "-f", "openclaw/dist/index.js gateway"], check=False)
    time.sleep(1)
    env = os.environ.copy()
    if PROXY_ENV.exists():
        for line in PROXY_ENV.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    subprocess.Popen(
        [
            "/usr/bin/node",
            "/usr/lib/node_modules/openclaw/dist/index.js",
            "gateway",
            "--port",
            "18789",
        ],
        start_new_session=True,
        env=env,
        stdout=open(GATEWAY_LOG, "a", encoding="utf-8"),
        stderr=subprocess.STDOUT,
    )
    print("gateway restarted (log /root/openclaw-gateway.log)")


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "model",
        choices=["doubao", "deepseek", "qwen", "gemini", "claude", "gpt"],
        help="evaluation model alias",
    )
    ap.add_argument("--restart-gateway", action="store_true")
    args = ap.parse_args()

    profiles = _profiles()
    profile = profiles[args.model]

    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    _backup(CFG)
    _configure_providers(cfg)
    plugins = cfg.setdefault("plugins", {})
    plugins["bundledDiscovery"] = "allowlist"
    plugins["allow"] = ["lifecare"]
    plugins.pop("deny", None)

    ad = cfg.setdefault("agents", {}).setdefault("defaults", {})
    mp = ad.setdefault("model", {})
    mp["primary"] = profile["primary"]

    _apply_eval_runtime_defaults(cfg, primary=profile["primary"], alias=profile["alias"])

    CFG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"wrote {CFG}: primary={profile['primary']!r} "
        f"temperature={EVAL_TEMPERATURE} thinkingDefault={EVAL_THINKING_DEFAULT!r}"
    )

    if SESS.exists():
        _backup(SESS)
        store = json.loads(SESS.read_text(encoding="utf-8"))
        for row in store.values():
            if not isinstance(row, dict):
                continue
            row["model"] = profile["model_id"]
            row["modelProvider"] = profile["provider"]
            if row.get("authProfileOverride") == "openrouter:default":
                row.pop("authProfileOverride", None)
                row.pop("authProfileOverrideSource", None)
                row.pop("authProfileOverrideCompactionCount", None)
        SESS.write_text(json.dumps(store, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {SESS}: sessions -> {profile['provider']}/{profile['model_id']}")

    _write_proxy_env(profile["needs_proxy"])

    if args.restart_gateway:
        _restart_gateway()


if __name__ == "__main__":
    main()
