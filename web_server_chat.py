"""
独立对话网页后端：不经过 OpenClaw，只调本仓库 MCP 实现（与 scripts/run_local_agent.py 同源）。

启动（在项目根目录）：
  uvicorn web_server_chat:app --host 127.0.0.1 --port 8099

浏览器打开 http://127.0.0.1:8099/
答辩若赛题要求 OpenClaw，仍以网关演示为准；本页用于「自研前端 + 同款工具链」体验。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_local_agent import run_dry, run_llm  # noqa: E402


def _dry_to_markdown(data: dict) -> str:
    lines: list[str] = [
        "### 本地演练（dry · 未调用大模型）",
        "",
        f"**城市** {data.get('used_city', '')}  ·  **关键词** {data.get('used_keywords', '')}",
        "",
        "```json",
        json.dumps(data.get("intent_heuristic"), ensure_ascii=False, indent=2)[:2000],
        "```",
        "",
    ]
    search = data.get("search") or {}
    if search.get("ok") and search.get("pois"):
        lines.append("### 检索到的 POI（节选）")
        lines.append("")
        for p in (search.get("pois") or [])[:6]:
            name = p.get("name") or ""
            url = p.get("amap_place_url") or ""
            photos = p.get("photo_urls") or []
            lines.append(f"- **{name}**")
            if url:
                lines.append(f"  - [高德地图]({url})")
            if photos:
                lines.append(f"  - ![]({photos[0]})")
            lines.append("")
    else:
        lines.append("_本次检索无结果或 AMAP_KEY 未配置。_")
    return "\n".join(lines)


def _llm_trace_to_reply(trace: list) -> str:
    for item in reversed(trace):
        if isinstance(item, dict) and "final_reply" in item:
            return str(item["final_reply"] or "").strip()
    return "_模型未返回最终正文，请查看服务端日志或改用 --dry 自测。_"


app = FastAPI(title="lifecare-chat", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    dry: bool = False
    max_turns: int = Field(8, ge=1, le=16)


@app.get("/")
def index() -> FileResponse:
    p = WEB / "lifecare-chat.html"
    if not p.exists():
        raise HTTPException(500, "lifecare-chat.html missing")
    return FileResponse(p, media_type="text/html; charset=utf-8")


@app.post("/api/chat")
def api_chat(body: ChatIn) -> dict:
    try:
        if body.dry:
            out = run_dry(body.message)
            md = _dry_to_markdown(out)
            return {"ok": True, "mode": "dry", "reply_markdown": md, "raw": out}
        trace = run_llm(body.message, body.max_turns)
        md = _llm_trace_to_reply(trace)
        return {"ok": True, "mode": "llm", "reply_markdown": md, "trace": trace}
    except SystemExit as e:
        raise HTTPException(400, str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e)) from e


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "lifecare-chat-web"}
