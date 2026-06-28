"""
gateway-chat-ui 配套：IP / 逆地理 + 行程信息图，供 /api/*。

本地（与 Vite 联调）：
  uvicorn gateway_context_api:app --host 127.0.0.1 --port 8098

ECS：Nginx 将 /api/ 反代到本服务（见 gateway-chat-ui/scripts/nginx-client-context.conf.example）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lifecare.clients.geo_context import locate_by_ip, regeo_location  # noqa: E402
from lifecare.harness.post_output import should_apply_harness_output, validate_and_repair
from lifecare.harness.session_state import load_state, on_user_message
from lifecare.services.itinerary_image import (  # noqa: E402
    JobCancelled,
    cancel_job,
    cleanup_job,
    register_job,
    run_pipeline,
)


def _client_ip(request: Request) -> str:
    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        return xff.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return ""


def _private_ip(ip: str) -> bool:
    if not ip:
        return True
    if ip in ("127.0.0.1", "::1", "localhost"):
        return True
    if ip.startswith("10.") or ip.startswith("192.168.") or ip.startswith("172."):
        return True
    if ip.startswith("::ffff:127.") or ip.startswith("::ffff:10."):
        return True
    return False


app = FastAPI(title="gateway-client-context", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class RegeoIn(BaseModel):
    lng: float = Field(..., ge=-180, le=180)
    lat: float = Field(..., ge=-90, le=90)
    accuracy_m: float | None = Field(default=None, ge=0, le=50_000)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "gateway-client-context"}


@app.get("/api/client-context")
def api_client_context(request: Request) -> dict:
    ip = _client_ip(request)
    payload: dict = {"ok": True, "client_ip": ip, "ip_location": None}
    if not _private_ip(ip):
        loc = locate_by_ip(ip)
        payload["ip_location"] = loc
    else:
        loc = locate_by_ip(None)
        payload["ip_location"] = loc
        payload["ip_note"] = "client appears private; server-side IP lookup may reflect egress, not handset"
    return payload


@app.post("/api/client-context/regeo")
def api_regeo(body: RegeoIn) -> dict:
    try:
        return regeo_location(body.lng, body.lat) | {
            "accuracy_m": body.accuracy_m,
        }
    except Exception as e:
        raise HTTPException(500, str(e)) from e


class ItineraryImageIn(BaseModel):
    plan_markdown: str = Field(..., min_length=200)
    job_id: str = Field(..., min_length=8, max_length=80)


class ItineraryImageCancelIn(BaseModel):
    job_id: str = Field(..., min_length=8, max_length=80)


@app.post("/api/itinerary-image")
async def api_itinerary_image(body: ItineraryImageIn, request: Request) -> dict:
    cancel_ev = register_job(body.job_id)
    try:
        if await request.is_disconnected():
            raise JobCancelled()
        result = await asyncio.to_thread(run_pipeline, body.plan_markdown, cancel_ev)
        return result
    except JobCancelled:
        return {"ok": False, "cancelled": True}
    except Exception as e:
        raise HTTPException(500, str(e)) from e
    finally:
        cleanup_job(body.job_id)


@app.post("/api/itinerary-image/cancel")
def api_itinerary_image_cancel(body: ItineraryImageCancelIn) -> dict:
    return {"ok": True, "cancelled": cancel_job(body.job_id)}


# ---------------------------------------------------------------------------
# Model switch API
# ---------------------------------------------------------------------------
import subprocess as _sp  # noqa: E402

MODEL_SWITCH_SCRIPT = str(ROOT / "gateway-chat-ui" / "scripts" / "ecs_switch_model_v2.py")

AVAILABLE_MODELS = [
    {"id": "doubao-seed-2.0-code",   "label": "豆包 Seed 2.0 Code"},
    {"id": "doubao-seed-2.0-pro",    "label": "豆包 Seed 2.0 Pro"},
    {"id": "doubao-seed-2.0-lite",   "label": "豆包 Seed 2.0 Lite"},
    {"id": "doubao-seed-code",       "label": "豆包 Seed Code"},
    {"id": "minimax-m2.7",           "label": "MiniMax M2.7"},
    {"id": "minimax-m3",             "label": "MiniMax M3"},
    {"id": "glm-4.7",                "label": "GLM 4.7"},
    {"id": "deepseek-v4-flash",      "label": "DeepSeek V4 Flash"},
    {"id": "deepseek-v4-pro",        "label": "DeepSeek V4 Pro"},
    {"id": "kimi-k2.6",              "label": "Kimi K2.6"},
    {"id": "kimi-k2.7-code",         "label": "Kimi K2.7 Code"},
]

# Track current model (in-memory, resets on restart)
_current_model_id: str = "doubao-seed-2.0-code"


class SwitchModelIn(BaseModel):
    model_id: str = Field(..., min_length=1, max_length=80)


@app.get("/api/models")
def api_list_models() -> dict:
    return {"ok": True, "models": AVAILABLE_MODELS, "current": _current_model_id}


@app.post("/api/switch-model")
def api_switch_model(body: SwitchModelIn) -> dict:
    global _current_model_id
    model_id = body.model_id.strip()
    valid_ids = {m["id"] for m in AVAILABLE_MODELS}
    if model_id not in valid_ids:
        raise HTTPException(400, f"Unknown model: {model_id}. Available: {', '.join(sorted(valid_ids))}")

    try:
        result = _sp.run(
            ["python3", MODEL_SWITCH_SCRIPT, model_id],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise HTTPException(500, f"Switch script failed: {result.stderr or result.stdout}")
        _current_model_id = model_id
        return {"ok": True, "model_id": model_id, "output": result.stdout.strip()}
    except _sp.TimeoutExpired:
        raise HTTPException(500, "Model switch timed out")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e)) from e


class HarnessUserMessageIn(BaseModel):
    session_key: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1, max_length=8000)
    intake_skipped: bool = False


class HarnessValidateIn(BaseModel):
    session_key: str = Field(..., min_length=1, max_length=200)
    text: str = Field(..., min_length=1, max_length=120_000)
    apply_repairs: bool = True


@app.post("/api/harness/on-user-message")
def api_harness_on_user_message(body: HarnessUserMessageIn) -> dict:
    state = on_user_message(
        body.session_key.strip(),
        body.message,
        intake_skipped=body.intake_skipped,
    )
    return {
        "ok": True,
        "session_key": state.get("session_key"),
        "stage": state.get("stage"),
        "slots": state.get("slots"),
    }


@app.post("/api/harness/validate-and-repair")
def api_harness_validate_and_repair(body: HarnessValidateIn) -> dict:
    sk = body.session_key.strip()
    text = body.text
    if not should_apply_harness_output(text):
        return {
            "ok": True,
            "text": text,
            "blocked": False,
            "repairs_applied": [],
            "violations": [],
            "skipped": True,
        }
    result = validate_and_repair(sk, text, apply_repairs=body.apply_repairs)
    return result


@app.get("/api/harness/state")
def api_harness_state(session_key: str) -> dict:
    if not session_key.strip():
        raise HTTPException(400, "session_key required")
    st = load_state(session_key.strip())
    return {"ok": True, "state": st}


# ---------------------------------------------------------------------------
# Eval manual test log — 前端人工评测 10 Tasks 结构化日志
# ---------------------------------------------------------------------------
import json as _json  # noqa: E402
from datetime import datetime as _dt, timezone as _tz  # noqa: E402

EVAL_LOG_DIR = ROOT / "测试" / "eval_logs"
EVAL_LOG_DIR.mkdir(parents=True, exist_ok=True)
SESSIONS_DIR = Path.home() / ".openclaw" / "agents" / "main" / "sessions"


class EvalLogIn(BaseModel):
    """兼容旧版 turn 时序格式"""
    sessionKey: str = Field(..., min_length=1, max_length=200)
    user: dict = Field(...)
    assistant: dict = Field(...)
    recordedAt: int = Field(..., ge=0)


class EvalEventIn(BaseModel):
    """统一评测事件（turn / intake / 工具进展 / 生图 / 会话元数据）"""
    event: str = Field(..., min_length=1, max_length=64)
    sessionKey: str = Field(..., min_length=1, max_length=200)
    recordedAt: int = Field(..., ge=0)
    taskId: str | None = Field(default=None, max_length=32)
    threadTitle: str | None = Field(default=None, max_length=200)
    turnIndex: int | None = Field(default=None, ge=0)
    modelId: str | None = Field(default=None, max_length=80)
    deviceId: str | None = Field(default=None, max_length=80)
    testerLabel: str | None = Field(default=None, max_length=64)
    payload: dict = Field(default_factory=dict)


def _eval_log_path(date_str: str | None = None) -> Path:
    ds = date_str or _dt.now(_tz.utc).strftime("%Y-%m-%d")
    return EVAL_LOG_DIR / f"eval_manual_{ds}.jsonl"


def _append_eval_line(entry: dict) -> Path:
    entry.setdefault("serverTime", _dt.now(_tz.utc).isoformat())
    log_file = _eval_log_path()
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(_json.dumps(entry, ensure_ascii=False) + "\n")
    return log_file


@app.post("/api/eval/log")
def api_eval_log(req: EvalLogIn) -> dict:
    """接收前端 turn 时序（兼容旧格式，写入 eval_manual_*.jsonl）"""
    log_entry = {
        "event": "turn_complete",
        "sessionKey": req.sessionKey,
        "user": req.user,
        "assistant": req.assistant,
        "recordedAt": req.recordedAt,
    }
    log_file = _append_eval_line(log_entry)
    return {"ok": True, "file": str(log_file.name)}


@app.post("/api/eval/event")
def api_eval_event(req: EvalEventIn) -> dict:
    """接收结构化评测事件"""
    log_entry = {
        "event": req.event.strip(),
        "sessionKey": req.sessionKey.strip(),
        "recordedAt": req.recordedAt,
        "taskId": (req.taskId or "").strip() or None,
        "threadTitle": (req.threadTitle or "").strip() or None,
        "turnIndex": req.turnIndex,
        "modelId": (req.modelId or "").strip() or None,
        "deviceId": (req.deviceId or "").strip() or None,
        "testerLabel": (req.testerLabel or "").strip() or None,
        "payload": req.payload or {},
    }
    log_file = _append_eval_line(log_entry)
    return {"ok": True, "file": str(log_file.name), "event": log_entry["event"]}


@app.get("/api/eval/logs")
def api_eval_logs(date: str | None = None, limit: int = 200) -> dict:
    """列出当日评测日志（最近 limit 条）"""
    log_file = _eval_log_path(date)
    if not log_file.is_file():
        return {"ok": True, "file": log_file.name, "entries": [], "count": 0}
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    tail = lines[-max(1, min(limit, 2000)) :]
    entries = []
    for line in tail:
        try:
            entries.append(_json.loads(line))
        except _json.JSONDecodeError:
            continue
    return {"ok": True, "file": log_file.name, "count": len(lines), "entries": entries}


@app.post("/api/eval/score")
def api_eval_score(body: dict | None = None) -> dict:
    """对 eval_manual_*.jsonl + session jsonl 自动打分（10 Tasks rubric）"""
    body = body or {}
    date = str(body.get("date") or _dt.now(_tz.utc).strftime("%Y-%m-%d"))
    session_keys = body.get("sessionKeys")
    try:
        _test_dir = ROOT / "测试"
        if str(_test_dir) not in sys.path:
            sys.path.insert(0, str(_test_dir))
        from manual_eval.score_from_logs import run_score_report

        report = run_score_report(
            log_file=_eval_log_path(date),
            sessions_dir=SESSIONS_DIR,
            session_keys=session_keys,
            tasks_manifest=ROOT / "测试" / "manual_eval" / "tasks_10.json",
            repo_root=ROOT,
        )
        return {"ok": True, "report": report}
    except Exception as e:
        raise HTTPException(500, str(e)) from e
