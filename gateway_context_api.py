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


class HarnessUserMessageIn(BaseModel):
    session_key: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1, max_length=8000)


class HarnessValidateIn(BaseModel):
    session_key: str = Field(..., min_length=1, max_length=200)
    text: str = Field(..., min_length=1, max_length=120_000)
    apply_repairs: bool = True


@app.post("/api/harness/on-user-message")
def api_harness_on_user_message(body: HarnessUserMessageIn) -> dict:
    state = on_user_message(body.session_key.strip(), body.message)
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
