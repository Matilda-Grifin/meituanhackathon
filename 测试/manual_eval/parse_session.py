#!/usr/bin/env python3
"""从 OpenClaw session jsonl 提取对话、工具、token。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


_WEATHER = re.compile(r"get_weather|weather", re.I)
_SEARCH = re.compile(r"search_places|search_poi", re.I)
_ROUTE = re.compile(r"plan_route", re.I)
_TIME_SLOT = re.compile(r"\d{1,2}[:：]\d{2}|上午|下午|中午|晚餐|午餐|早餐")
_POI_HINT = re.compile(r"馆|店|街|广场|公园|博物馆|展览|Livehouse|寺|塔|湖|商场|高铁|虹桥|电梯|无障碍|台阶")
_WEATHER_TEXT = re.compile(r"天气|气温|°C|℃|多云|晴|雨|雪|风", re.I)
_PRICE = re.compile(r"人均\s*(\d+)\s*[-~～至到]\s*(\d+)|人均\s*(\d+)", re.I)
_TRAVEL_MIN = re.compile(r"(\d+)\s*分钟|(\d+)\s*公里|地铁|打车|驾车|步行", re.I)


def session_uuid(session_key: str) -> str:
    sk = (session_key or "").strip()
    if ":" in sk:
        sk = sk.split(":")[-1]
    return sk


def _session_message_count(path: Path) -> int:
    try:
        n = 0
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("type") == "message":
                n += 1
        return n
    except OSError:
        return 0


def _reset_backups_for_stem(sessions_dir: Path, stem: str) -> list[Path]:
    return sorted(
        sessions_dir.glob(f"{stem}.jsonl.reset.*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def _session_file_from_entry(sessions_dir: Path, entry: dict) -> Path | None:
    sf = entry.get("sessionFile")
    if sf:
        p = Path(str(sf))
        if p.is_file():
            return p
    sid = entry.get("sessionId")
    if not sid:
        return None
    direct = sessions_dir / f"{sid}.jsonl"
    if direct.is_file():
        return direct
    resets = _reset_backups_for_stem(sessions_dir, str(sid))
    return resets[0] if resets else None


def _pick_richest_session_file(sessions_dir: Path, candidates: list[Path]) -> Path | None:
    best: Path | None = None
    best_count = 0
    seen: set[str] = set()
    for p in candidates:
        if not p.is_file():
            continue
        stems = [p.stem.split(".jsonl")[0]]
        for candidate in (p, *_reset_backups_for_stem(sessions_dir, stems[0])):
            cs = str(candidate)
            if cs in seen or not candidate.is_file():
                continue
            seen.add(cs)
            count = _session_message_count(candidate)
            if count > best_count:
                best_count = count
                best = candidate
    return best


def find_session_jsonl(sessions_dir: Path, session_key: str) -> Path | None:
    uid = session_uuid(session_key)
    candidates: list[Path] = []

    direct = sessions_dir / f"{uid}.jsonl"
    if direct.is_file():
        candidates.append(direct)

    sessions_json = sessions_dir / "sessions.json"
    json_sources = [sessions_json] if sessions_json.is_file() else []
    json_sources.extend(sorted(sessions_dir.glob("sessions.json.bak-*"), key=lambda p: p.stat().st_mtime, reverse=True))
    for sj in json_sources:
        try:
            data = json.loads(sj.read_text(encoding="utf-8"))
            entry = data.get(session_key) if isinstance(data, dict) else None
            if isinstance(entry, dict):
                p = _session_file_from_entry(sessions_dir, entry)
                if p and p not in candidates:
                    candidates.append(p)
                sid = entry.get("sessionId")
                if sid:
                    sid_path = sessions_dir / f"{sid}.jsonl"
                    if sid_path.is_file() and sid_path not in candidates:
                        candidates.append(sid_path)
        except (json.JSONDecodeError, OSError):
            continue

    richest = _pick_richest_session_file(sessions_dir, candidates)
    if richest:
        return richest

    for p in sessions_dir.glob("*.jsonl"):
        if "trajectory" in p.name or ".reset." in p.name:
            continue
        if uid in p.stem:
            candidates.append(p)
    richest = _pick_richest_session_file(sessions_dir, candidates)
    if richest:
        return richest

    resets = _reset_backups_for_stem(sessions_dir, uid)
    return resets[0] if resets else (direct if direct.is_file() else None)


def _parse_ts(ts: str | int | float | None) -> float | None:
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts) / 1000.0 if ts > 1e12 else float(ts)
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _text_from_content(content: list | str | None) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif isinstance(block.get("text"), str):
                parts.append(block["text"])
    return "\n".join(parts)


@dataclass
class SessionSnapshot:
    session_key: str
    session_file: str
    tools_in_order: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    user_messages: list[dict] = field(default_factory=list)
    assistant_messages: list[dict] = field(default_factory=list)
    total_tokens: int = 0
    message_count: int = 0
    final_plan_text: str = ""

    @property
    def tool_counts(self) -> dict[str, int]:
        w = s = r = 0
        for t in self.tools_in_order:
            if _WEATHER.search(t):
                w += 1
            if _SEARCH.search(t):
                s += 1
            if _ROUTE.search(t):
                r += 1
        return {"weather": w, "search": s, "route": r, "total": len(self.tools_in_order)}

    @property
    def user_turns(self) -> int:
        return len([m for m in self.user_messages if not m.get("hidden")])


def load_session_snapshot(sessions_dir: Path, session_key: str) -> SessionSnapshot | None:
    path = find_session_jsonl(sessions_dir, session_key)
    if not path:
        return None
    snap = SessionSnapshot(session_key=session_key, session_file=str(path))
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("type") != "message":
            continue
        msg = row.get("message") or {}
        role = str(msg.get("role") or "").lower()
        ts = _parse_ts(row.get("timestamp") or msg.get("timestamp"))
        usage = msg.get("usage") or {}
        tok = int(usage.get("totalTokens") or 0)
        if tok <= 0:
            inp = int(usage.get("input") or usage.get("promptTokens") or 0)
            out = int(usage.get("output") or usage.get("completionTokens") or 0)
            tok = inp + out
        snap.total_tokens += tok
        snap.message_count += 1
        content = msg.get("content")
        if role == "assistant":
            text = _text_from_content(content)
            tools_this: list[str] = []
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "toolCall":
                        name = str(block.get("name") or "")
                        if name:
                            tools_this.append(name)
                            snap.tools_in_order.append(name)
                            snap.tool_calls.append(
                                {
                                    "name": name,
                                    "timestamp": ts,
                                    "arguments": block.get("arguments"),
                                }
                            )
            snap.assistant_messages.append({"text": text, "timestamp": ts, "tools": tools_this})
            if text and len(text) > 400 and ("#" in text or "行程" in text or "Day" in text):
                if len(text) > len(snap.final_plan_text):
                    snap.final_plan_text = text
        elif role == "user":
            text = _text_from_content(content)
            hidden = "[位置上下文]" in text or "[系统预热]" in text
            snap.user_messages.append({"text": text, "timestamp": ts, "hidden": hidden})
        elif role == "toolresult":
            tool_name = str(msg.get("toolName") or "")
            if tool_name and tool_name not in snap.tools_in_order:
                snap.tools_in_order.append(tool_name)
    return snap


def plan_heuristics(plan_text: str) -> dict:
    t = plan_text or ""
    return {
        "has_weather_mention": bool(_WEATHER_TEXT.search(t)),
        "time_slots": len(_TIME_SLOT.findall(t)),
        "poi_hints": len(_POI_HINT.findall(t)),
        "travel_evidence": bool(_TRAVEL_MIN.search(t)),
        "prices": _PRICE.findall(t),
        "length": len(t),
    }
