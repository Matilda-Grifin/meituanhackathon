#!/usr/bin/env python3
"""
读取 eval_manual_YYYY-MM-DD.jsonl + OpenClaw session jsonl，对 10 Tasks 自动打分。

用法（ECS 或本机）：
  cd meituan-lifecare-agent
  python3 测试/manual_eval/score_from_logs.py
  python3 测试/manual_eval/score_from_logs.py --date 2026-06-23
  python3 测试/manual_eval/score_from_logs.py --write-md 测试/eval_logs/report_2026-06-23.md

或 HTTP：
  curl -sk -X POST https://121.41.81.58:8080/api/eval/score -H 'Content-Type: application/json' -d '{}'
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_TEST_PKG_ROOT = Path(__file__).resolve().parents[1]
if str(_TEST_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_TEST_PKG_ROOT))

from manual_eval.parse_session import load_session_snapshot, session_uuid
from manual_eval.score_rubrics import score_process_metrics, score_task_rubrics

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG = ROOT / "测试" / "eval_logs"
DEFAULT_MANIFEST = Path(__file__).resolve().parent / "tasks_10.json"
SESSIONS_DIR = Path.home() / ".openclaw" / "agents" / "main" / "sessions"

_TASK_ID_RE = re.compile(r"T063_\d{3}|task_0\d{2}", re.I)


def _parse_task_id(*candidates: str | None) -> str | None:
    for c in candidates:
        if not c:
            continue
        m = _TASK_ID_RE.search(c)
        if m:
            tid = m.group(0).upper()
            if tid.startswith("TASK_"):
                num = tid.split("_")[1]
                return f"T063_{num}"
            return tid
    return None


def load_manifest(path: Path, repo_root: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    tasks = []
    for t in data.get("tasks") or []:
        rel = t.get("file") or ""
        candidates = [
            path.parent / rel,
            repo_root / rel,
            repo_root.parent / rel,
        ]
        task_path = next((p for p in candidates if p.is_file()), repo_root / rel)
        task_json = {}
        if task_path.is_file():
            task_json = json.loads(task_path.read_text(encoding="utf-8"))
        tasks.append({**t, "task_json": task_json, "task_path": str(task_path)})
    return tasks


def load_eval_events(log_file: Path) -> list[dict]:
    if not log_file.is_file():
        return []
    out = []
    for line in log_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def group_events_by_session(events: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        sk = str(e.get("sessionKey") or "").strip()
        if sk:
            groups[sk].append(e)
    return groups


def derive_metrics(events: list[dict], snap: Any) -> dict:
    metrics: dict[str, Any] = {}
    task_id = _parse_task_id(*(e.get("taskId") for e in events), *(e.get("threadTitle") for e in events))
    metrics["task_id"] = task_id

    intake_shown_ts: float | None = None
    image_start: float | None = None
    image_end: float | None = None
    last_assistant = ""
    turn_completes: list[dict] = []
    eval_tokens = 0
    tokens_reported = False

    for e in events:
        ev = e.get("event")
        ts = (e.get("recordedAt") or 0) / 1000.0
        payload = e.get("payload") or {}
        if metrics.get("modelId") is None:
            metrics["modelId"] = e.get("modelId") or payload.get("modelId")
        if metrics.get("deviceId") is None:
            metrics["deviceId"] = e.get("deviceId")
        if metrics.get("testerLabel") is None:
            metrics["testerLabel"] = e.get("testerLabel")
        if ev == "model_switch" and payload.get("toModelId"):
            metrics["modelId"] = payload["toModelId"]

        if ev == "turn_complete":
            user = payload.get("user") or e.get("user") or {}
            asst = payload.get("assistant") or e.get("assistant") or {}
            if asst.get("text"):
                last_assistant = str(asst["text"])
            turn_completes.append(
                {
                    "phase": payload.get("phase"),
                    "isIntakeQuestion": payload.get("isIntakeQuestion"),
                    "isPlan": payload.get("isPlan"),
                    "user_ts": user.get("timestamp"),
                    "ttftMs": asst.get("ttftMs"),
                    "durationMs": asst.get("durationMs"),
                    "firstToolMs": asst.get("firstToolMs"),
                    "totalTokens": asst.get("totalTokens"),
                }
            )
            tok = asst.get("totalTokens")
            if isinstance(tok, (int, float)) and tok > 0:
                eval_tokens += int(tok)
                tokens_reported = True
            continue

        if ev == "intake_shown":
            ttft = payload.get("ttftMs")
            if isinstance(ttft, (int, float)) and ttft >= 0:
                if metrics.get("intake_ttft_ms") is None:
                    metrics["intake_ttft_ms"] = int(ttft)
            if intake_shown_ts is None:
                intake_shown_ts = ts
        elif ev == "intake_submitted":
            metrics["intake_submitted_count"] = int(metrics.get("intake_submitted_count") or 0) + 1
        elif ev == "tool_progress" and payload.get("phase") == "B":
            metrics["b_tool_progress_ok"] = True
        elif ev == "image_gen_start":
            image_start = ts
        elif ev == "image_gen_complete":
            image_end = ts
            if payload.get("durationMs"):
                metrics["image_e2e_ms"] = payload["durationMs"]
            metrics["image_completed"] = payload.get("ok", True)

    if metrics.get("intake_ttft_ms") is None:
        for tc in turn_completes:
            if tc.get("isIntakeQuestion") and isinstance(tc.get("ttftMs"), (int, float)) and tc["ttftMs"] >= 0:
                metrics["intake_ttft_ms"] = int(tc["ttftMs"])
                break

    if metrics.get("intake_ttft_ms") is None and intake_shown_ts:
        for tc in turn_completes:
            if tc.get("isIntakeQuestion") and tc.get("user_ts"):
                delta = intake_shown_ts - tc["user_ts"] / 1000.0
                if 0 <= delta <= 120:
                    metrics["intake_ttft_ms"] = int(delta * 1000)
                    break

    if image_start and image_end and not metrics.get("image_e2e_ms"):
        metrics["image_e2e_ms"] = int((image_end - image_start) * 1000)

    metrics["turn_complete_count"] = len(turn_completes)
    metrics["plan_turn_count"] = sum(1 for tc in turn_completes if tc.get("isPlan"))
    if eval_tokens > 0:
        metrics["eval_total_tokens"] = eval_tokens
    metrics["tokens_from_provider"] = tokens_reported or (getattr(snap, "total_tokens", 0) or 0) > 0
    metrics["last_assistant_text"] = last_assistant
    metrics["weather_in_assistant"] = "天气" in last_assistant
    return metrics


def run_score_report(
    *,
    log_file: Path,
    sessions_dir: Path,
    session_keys: list[str] | None = None,
    tasks_manifest: Path,
    repo_root: Path,
) -> dict:
    events = load_eval_events(log_file)
    grouped = group_events_by_session(events)
    if session_keys:
        grouped = {k: v for k, v in grouped.items() if k in session_keys or session_uuid(k) in session_keys}

    manifest = load_manifest(tasks_manifest, repo_root)
    by_task_id = {t["task_id"]: t for t in manifest}

    sessions_scored = []
    for sk, evts in grouped.items():
        snap = load_session_snapshot(sessions_dir, sk)
        if not snap:
            continue
        metrics = derive_metrics(evts, snap)
        tid = metrics.get("task_id")
        task_entry = by_task_id.get(tid) if tid else None
        task_json = (task_entry or {}).get("task_json") or {}
        rubric = score_task_rubrics(task_json, snap, metrics) if task_json else {"rubrics": [], "met": 0, "total": 0, "reward": 0, "full_success": False}
        process = score_process_metrics(snap, evts, metrics)
        sessions_scored.append(
            {
                "sessionKey": sk,
                "sessionUuid": session_uuid(sk),
                "taskId": tid,
                "taskLabel": (task_entry or {}).get("label"),
                "difficulty": (task_entry or {}).get("difficulty"),
                "threadTitle": next((e.get("threadTitle") for e in evts if e.get("threadTitle")), None),
                "modelId": metrics.get("modelId"),
                "deviceId": metrics.get("deviceId"),
                "testerLabel": metrics.get("testerLabel"),
                "reward": rubric["reward"],
                "full_success": rubric["full_success"],
                "rubric_met": rubric["met"],
                "rubric_total": rubric["total"],
                "rubrics": rubric["rubrics"],
                "process": process,
                "tools": snap.tool_counts,
            }
        )

    sessions_scored.sort(key=lambda x: x.get("taskId") or "Z")

    by_diff: dict[str, list] = defaultdict(list)
    for s in sessions_scored:
        d = s.get("difficulty") or "unknown"
        by_diff[d].append(s)

    summary_rows = []
    total_met = total_r = 0
    full_success_count = 0
    for s in sessions_scored:
        total_met += s["rubric_met"]
        total_r += s["rubric_total"]
        if s["full_success"]:
            full_success_count += 1

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "logFile": str(log_file),
        "sessionsDir": str(sessions_dir),
        "sessionCount": len(sessions_scored),
        "meanReward": round(total_met / total_r, 4) if total_r else 0,
        "fullSuccessRate": round(full_success_count / len(sessions_scored), 4) if sessions_scored else 0,
        "fullSuccessCount": full_success_count,
        "byDifficulty": {
            d: {
                "count": len(rows),
                "meanReward": round(sum(r["rubric_met"] for r in rows) / max(1, sum(r["rubric_total"] for r in rows)), 4),
            }
            for d, rows in by_diff.items()
        },
        "sessions": sessions_scored,
        "unmappedSessions": [sk for sk, ev in grouped.items() if not _parse_task_id(*(e.get("taskId") for e in ev), *(e.get("threadTitle") for e in ev))],
    }


def format_markdown(report: dict) -> str:
    lines = [
        f"# 人工评测 10 Tasks 自动打分报告",
        "",
        f"- 生成时间：{report.get('generatedAt')}",
        f"- 日志：{report.get('logFile')}",
        f"- 会话数：{report.get('sessionCount')}",
        f"- **Mean Reward**：{report.get('meanReward')}",
        f"- **Full Success Rate**：{report.get('fullSuccessRate')} ({report.get('fullSuccessCount')}/{report.get('sessionCount')})",
        "",
        "## 汇总（按难度）",
        "",
        "| 难度 | 会话数 | mean reward |",
        "|------|--------|-------------|",
    ]
    for d, row in (report.get("byDifficulty") or {}).items():
        lines.append(f"| {d} | {row['count']} | {row['meanReward']} |")

    lines.extend(["", "## 单任务明细", ""])
    for s in report.get("sessions") or []:
        lines.append(f"### {s.get('taskId') or '未映射'} · {s.get('taskLabel') or s.get('sessionUuid', '')[:8]}")
        lines.append("")
        lines.append(f"- session：`{s.get('sessionUuid')}`")
        lines.append(f"- **reward**：{s.get('rubric_met')}/{s.get('rubric_total')} = **{s.get('reward')}** · Full Success：**{s.get('full_success')}**")
        p = s.get("process") or {}
        lines.append(f"- A 阶段 intake ≤10s：{p.get('intake_within_10s')} ({p.get('intake_ttft_ms')} ms)")
        lines.append(f"- B 阶段工具进展可见：{p.get('b_tool_progress_visible')} ({p.get('b_tool_progress_events')} 事件)")
        lines.append(f"- turn_complete 记录：{p.get('turn_complete_count')} 轮 · 方案轮：{p.get('plan_turn_count')}")
        lines.append(f"- 生图端到端：{p.get('image_e2e_ms')} ms · ok={p.get('image_e2e_ok')}")
        tok_note = "" if p.get("tokens_from_provider") else "（Provider 未回报 token，显示 0）"
        lines.append(f"- Token：{p.get('total_tokens')}{tok_note} · 工具调用：{(s.get('tools') or {}).get('total')}")
        te = p.get("trajectory_efficiency") or {}
        lines.append(f"- 轨迹：tools/turn={te.get('tools_per_turn')} · assistant_msgs={te.get('assistant_messages')}")
        lines.append("")
        lines.append("| Rubric | 判定 | 说明 |")
        lines.append("|--------|------|------|")
        for r in s.get("rubrics") or []:
            mark = "✅" if r.get("pass") else "❌"
            lines.append(f"| {r.get('rubric', '')[:40]}… | {mark} | {r.get('detail', '')} |")
        lines.append("")

    unmapped = report.get("unmappedSessions") or []
    if unmapped:
        lines.extend(["## 未映射 TaskId 的会话", "", "请将侧边栏标题改为 `T063_002` 等形式后重测：", ""])
        for sk in unmapped[:20]:
            lines.append(f"- `{session_uuid(sk)}`")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Score manual 10-task eval from eval logs")
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    ap.add_argument("--log-dir", type=Path, default=DEFAULT_LOG)
    ap.add_argument("--sessions-dir", type=Path, default=SESSIONS_DIR)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--repo-root", type=Path, default=ROOT)
    ap.add_argument("--write-md", type=Path, default=None)
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args()

    log_file = args.log_dir / f"eval_manual_{args.date}.jsonl"
    report = run_score_report(
        log_file=log_file,
        sessions_dir=args.sessions_dir,
        tasks_manifest=args.manifest,
        repo_root=args.repo_root,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    if args.write_md:
        args.write_md.parent.mkdir(parents=True, exist_ok=True)
        args.write_md.write_text(format_markdown(report), encoding="utf-8")


if __name__ == "__main__":
    main()
