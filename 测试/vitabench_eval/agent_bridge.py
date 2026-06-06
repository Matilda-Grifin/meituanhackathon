"""OpenClaw agent bridge (one user turn -> one agent run with internal tools)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_OPENCLAW_CFG = Path.home() / ".openclaw" / "openclaw.json"


def find_openclaw() -> str | None:
    return shutil.which("openclaw") or shutil.which("openclaw.cmd")


def _subprocess_env(*, harness_session_key: str | None = None) -> dict[str, str]:
    from vitabench_eval.llm_client import load_repo_env

    load_repo_env()
    env = {k: v for k, v in os.environ.items() if isinstance(v, str)}
    if harness_session_key:
        env["LIFECARE_HARNESS_SESSION_KEY"] = harness_session_key.strip()
    if _OPENCLAW_CFG.is_file():
        try:
            cfg = json.loads(_OPENCLAW_CFG.read_text(encoding="utf-8"))
            token = ((cfg.get("gateway") or {}).get("auth") or {}).get("token")
            if token:
                env["OPENCLAW_GATEWAY_TOKEN"] = str(token)
        except (json.JSONDecodeError, OSError):
            pass
    return env


def _agent_cli_flags() -> list[str]:
    flags: list[str] = []
    thinking = os.environ.get("V63_EVAL_THINKING", "").strip()
    if thinking:
        flags.extend(["--thinking", thinking])
    if os.environ.get("V63_AGENT_LOCAL", "0").strip().lower() in ("1", "true", "yes", "on"):
        flags.append("--local")
    return flags


def format_environment_block(env: dict) -> str:
    locs = env.get("location") or []
    home = next((x for x in locs if x.get("label") == "home"), locs[0] if locs else {})
    beh = env.get("user_historical_behaviors") or {}
    lines = [
        "[仿真环境-只读，Agent 可见]",
        f"当前时间: {env.get('time', '')} ({env.get('timezone', 'Asia/Shanghai')})",
        f"用户ID: {env.get('user_id', '')}",
        f"出发点(home): {home.get('address', '')} (lng={home.get('longitude')}, lat={home.get('latitude')})",
        f"饮食禁忌: {beh.get('饮食禁忌', '无')}",
        f"口味偏好: {', '.join(beh.get('口味偏好') or [])}",
        f"常消费价格带: {beh.get('常消费餐饮价格带', '')}",
        f"出行半径偏好: {beh.get('出行半径偏好_km', '')} km",
        f"历史摘要: {beh.get('历史出行摘要', '')}",
        "[/仿真环境]",
    ]
    orders = (env.get("orders") or {}).get("local_life_recent") or []
    if orders:
        lines.insert(-1, f"近期订单数: {len(orders)}（摘要见环境库）")
    return "\n".join(lines)


def run_agent_turn(
    message: str,
    *,
    session_id: str,
    timeout_s: int = 180,
    inject_env: str | None = None,
) -> dict:
    exe = find_openclaw()
    if not exe:
        return {"error": "openclaw not found"}
    user_msg = message
    if inject_env:
        user_msg = f"{inject_env}\n\n{message}"
    cmd = [
        exe,
        "agent",
        "--agent",
        "main",
        "-m",
        user_msg,
        "--json",
        "--session-id",
        session_id,
        "--timeout",
        str(max(timeout_s, 120)),
        *_agent_cli_flags(),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            cwd=str(_ROOT),
            env=_subprocess_env(harness_session_key=session_id),
        )
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "message": message}
    if proc.returncode != 0 and not proc.stdout.strip():
        return {"error": proc.stderr.strip() or f"exit {proc.returncode}"}
    raw = proc.stdout.strip()
    if not raw:
        err = proc.stderr.strip()
        return {"error": err or "empty stdout", "stderr": proc.stderr[:800]}
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0:
        return {"error": "no json", "raw_head": raw[:400]}
    try:
        doc = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as e:
        return {"error": f"json: {e}", "raw_head": raw[:400]}
    result = doc.get("result") if isinstance(doc.get("result"), dict) else doc
    meta = result.get("meta") or doc.get("meta") or {}
    if doc.get("status") not in (None, "ok") and not meta.get("finalAssistantVisibleText"):
        err = meta.get("error") or doc.get("summary") or doc.get("status")
        if err and str(err).lower() not in ("ok", "completed"):
            return {"error": str(err), "raw_meta": meta}
    text = (
        meta.get("finalAssistantVisibleText")
        or meta.get("finalAssistantRawText")
        or ""
    )
    payloads = result.get("payloads") or doc.get("payloads") or []
    if not text and payloads:
        parts = [
            str(p.get("text") or "")
            for p in payloads
            if isinstance(p, dict) and p.get("text")
        ]
        text = "\n\n".join(parts).strip()
    if not text:
        for key in ("assistantMessage", "message", "content"):
            v = meta.get(key)
            if isinstance(v, str) and v.strip():
                text = v.strip()
                break
            if isinstance(v, dict) and v.get("content"):
                text = str(v["content"]).strip()
                break
    tool_calls = []
    for src in (meta.get("toolCalls"), meta.get("tool_calls"), meta.get("toolsDetail")):
        if isinstance(src, list):
            for item in src:
                if isinstance(item, dict):
                    tool_calls.append(
                        {
                            "name": item.get("name") or item.get("tool"),
                            "arguments": item.get("arguments") or item.get("args"),
                            "ok": item.get("ok"),
                            "error": item.get("error"),
                        }
                    )
    tools = [c["name"] for c in tool_calls if c.get("name")]
    ts = meta.get("toolSummary") or {}
    if isinstance(ts.get("tools"), list) and ts["tools"]:
        tools = list(ts["tools"])
    if not text and tool_calls:
        names = [c["name"] for c in tool_calls if c.get("name")]
        if names:
            text = f"[tools invoked: {', '.join(names)}]"
    if not text and tools:
        text = f"[tools invoked: {', '.join(tools)}]"
    return {
        "assistant_text": text,
        "tools": tools,
        "tool_calls": tool_calls,
        "time_to_first_assistant_text_ms": meta.get("timeToFirstAssistantTextMs"),
        "time_to_first_progress_ms": meta.get("timeToFirstProgressMs"),
        "duration_ms": meta.get("durationMs"),
        "usage": meta.get("usage") or meta.get("tokenUsage"),
        "raw_meta": meta,
    }
