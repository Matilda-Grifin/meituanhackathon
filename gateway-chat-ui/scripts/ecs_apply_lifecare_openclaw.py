#!/usr/bin/env python3
"""
Run on the OpenClaw host (e.g. ECS) as root after the repo exists at /root/meituan-lifecare-agent.

- Copies meituan-lifecare-agent/workspace/* → ~/.openclaw/workspace/ (赛题 SOUL / skills / mock)
- Merges mcp.servers.lifecare into ~/.openclaw/openclaw.json
- Merges tools.web.search.enabled=false (avoids long stalls when SearXNG is unset but the model keeps calling web_search)
- Sets root tools.profile to "coding" and tools.alsoAllow with all lifecare__lifecare_* MCP ids (OpenClaw 2026.5+ rejects agents.defaults.tools)
- Merges tools.deny web_search + x_search (belt-and-suspenders when profile still includes group:web)
- Merges env keys AMAP_KEY, MOCK_SANDBOX_BASE_URL from optional /tmp/lifecare_inject.json (base64 or plain JSON)
- Restarts the gateway on port 18789

Optional one-shot secrets file (delete after run):
  echo '{"AMAP_KEY":"...","MOCK_SANDBOX_BASE_URL":"http://127.0.0.1:9000"}' > /tmp/lifecare_inject.json
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

REPO = Path("/root/meituan-lifecare-agent")
CFG = Path("/root/.openclaw/openclaw.json")
WS = Path("/root/.openclaw/workspace")
INJECT = Path("/tmp/lifecare_inject.json")


def _load_inject() -> dict[str, str]:
    if not INJECT.is_file():
        return {}
    raw = INJECT.read_text(encoding="utf-8").strip()
    try:
        if raw.startswith("{") or raw.startswith("["):
            data = json.loads(raw)
        else:
            data = json.loads(base64.b64decode(raw).decode("utf-8"))
    except (json.JSONDecodeError, ValueError) as e:
        raise SystemExit(f"invalid {INJECT}: {e}") from e
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for k in ("AMAP_KEY", "MOCK_SANDBOX_BASE_URL"):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()
    return out


def _copy_workspace() -> None:
    src = REPO / "workspace"
    if not src.is_dir():
        raise SystemExit(f"missing {src}; upload the repo first")
    if WS.exists():
        bak = WS.parent / f"workspace.bak-{int(time.time() * 1000)}"
        shutil.move(str(WS), str(bak))
        print(f"workspace backup: {bak}")
    shutil.copytree(src, WS)
    print(f"workspace: {src} -> {WS}")


def _merge_config(inject: dict[str, str]) -> None:
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    env = cfg.setdefault("env", {})
    for k, v in inject.items():
        env[k] = v
    if not env.get("AMAP_KEY"):
        print("WARN: AMAP_KEY still empty in openclaw.json env — set it or pass /tmp/lifecare_inject.json")

    # Stop multi-minute loops: model calls web_search → SearXNG base URL missing → retry.
    tools_root = cfg.setdefault("tools", {})
    web = tools_root.setdefault("web", {})
    search = web.setdefault("search", {})
    search["enabled"] = False

    deny = tools_root.setdefault("deny", [])
    if not isinstance(deny, list):
        deny = []
        tools_root["deny"] = deny
    for name in ("web_search", "x_search"):
        if not any(str(d).lower() == name for d in deny):
            deny.append(name)

    lifecare_ids = [
        "lifecare__lifecare_search_places",
        "lifecare__lifecare_plan_route",
        "lifecare__lifecare_get_weather",
        "lifecare__lifecare_get_venue_queue",
        "lifecare__lifecare_get_attraction_crowd",
        "lifecare__lifecare_sandbox_catalog",
        "lifecare__lifecare_ride_estimate",
        "lifecare__lifecare_submit_mock_order",
        "lifecare__lifecare_inject_sandbox_failure",
    ]

    tools_root["profile"] = "coding"
    prev_allow = tools_root.get("alsoAllow")
    merged: list[str] = ["bundle-mcp"]
    if isinstance(prev_allow, list):
        for x in prev_allow:
            if isinstance(x, str) and x.strip() and x not in merged:
                merged.append(x)
    for tid in lifecare_ids:
        if tid not in merged:
            merged.append(tid)
    tools_root["alsoAllow"] = merged

    # OpenClaw 2026.5+ no longer accepts agents.defaults.tools (breaks gateway start).
    agents = cfg.get("agents")
    if isinstance(agents, dict):
        defaults = agents.get("defaults")
        if isinstance(defaults, dict) and "tools" in defaults:
            del defaults["tools"]
            print("removed agents.defaults.tools (unsupported on gateway 2026.5+)")

    mcp = cfg.setdefault("mcp", {}).setdefault("servers", {})
    mcp["lifecare"] = {
        "command": "python3",
        "args": [str(REPO / "run_mcp.py")],
        "cwd": str(REPO),
        "env": {
            "MOCK_SANDBOX_BASE_URL": env.get("MOCK_SANDBOX_BASE_URL", "http://127.0.0.1:9000"),
            "AMAP_KEY": env.get("AMAP_KEY", ""),
            "LIFECARE_HARNESS_LOG": "1",
            "LIFECARE_HARNESS_STATE_DIR": "/root/.openclaw/harness_state",
        },
    }

    CFG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"wrote {CFG} mcp.servers.lifecare + env merge + tools.web.search.enabled=false "
        "+ tools.deny web_search/x_search + tools.profile=coding "
        f"+ tools.alsoAllow bundle-mcp + {len(lifecare_ids)} lifecare ids"
    )
    print(
        "NOTE: if lifecare__ tools still return 'not found', upgrade global openclaw "
        "(`npm i -g openclaw@latest`) — some gateway builds omitted bundle-mcp tools "
        "from the main agent list (upstream tracker e.g. github.com/openclaw/openclaw/issues/74844)."
    )


def _restart_gateway() -> None:
    subprocess.run(["pkill", "-f", "openclaw/dist/index.js gateway"], check=False)
    time.sleep(2)
    log = Path("/root/openclaw-gateway.log")
    with log.open("a", encoding="utf-8") as lf:
        proc = subprocess.Popen(
            ["openclaw", "gateway", "--port", "18789"],
            stdout=lf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    time.sleep(4)
    if proc.poll() is not None:
        tail = log.read_text(encoding="utf-8", errors="replace")[-2000:]
        raise SystemExit(f"gateway exited early; log tail:\n{tail}")
    print("gateway restart issued (log /root/openclaw-gateway.log)")


def main() -> None:
    if not REPO.is_dir():
        raise SystemExit(f"clone or scp the repo to {REPO} first")
    inject = _load_inject()
    subprocess.run(
        ["python3", "-m", "pip", "install", "-q", "-r", str(REPO / "requirements.txt")],
        check=False,
    )
    _copy_workspace()
    _merge_config(inject)
    if INJECT.is_file():
        INJECT.unlink()
        print(f"removed {INJECT}")
    _restart_gateway()


if __name__ == "__main__":
    main()
