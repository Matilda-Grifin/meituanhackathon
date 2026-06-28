#!/usr/bin/env python3
"""Inspect one eval session: events + rubric score (resolves dashboard key via sessions.json)."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

_TEST_ROOT = Path(__file__).resolve().parents[1]
if str(_TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(_TEST_ROOT))

from manual_eval.parse_session import load_session_snapshot, session_uuid
from manual_eval.score_from_logs import derive_metrics, group_events_by_session, load_eval_events, load_manifest
from manual_eval.score_rubrics import score_process_metrics, score_task_rubrics

SESSIONS_JSON = Path.home() / ".openclaw/agents/main/sessions/sessions.json"
SESSIONS_DIR = Path.home() / ".openclaw/agents/main/sessions"


def resolve_session_file(session_key: str) -> str | None:
    uid = session_uuid(session_key)
    direct = SESSIONS_DIR / f"{uid}.jsonl"
    if direct.is_file():
        return str(direct)
    if SESSIONS_JSON.is_file():
        data = json.loads(SESSIONS_JSON.read_text(encoding="utf-8"))
        entry = data.get(session_key) if isinstance(data, dict) else None
        if isinstance(entry, dict) and entry.get("sessionFile"):
            return str(entry["sessionFile"])
        if isinstance(entry, dict) and entry.get("sessionId"):
            p = SESSIONS_DIR / f"{entry['sessionId']}.jsonl"
            if p.is_file():
                return str(p)
    for p in SESSIONS_DIR.glob("*.jsonl"):
        if uid in p.stem:
            return str(p)
    return None


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--session-key", required=True)
    ap.add_argument("--date", default="2026-06-23")
    ap.add_argument("--task-id", default=None)
    args = ap.parse_args()

    repo = Path(__file__).resolve().parents[2]
    log = repo / "测试" / "eval_logs" / f"eval_manual_{args.date}.jsonl"
    events = group_events_by_session(load_eval_events(log)).get(args.session_key, [])
    sf = resolve_session_file(args.session_key)
    snap = load_session_snapshot(SESSIONS_DIR, args.session_key)

    metrics = derive_metrics(events, snap) if snap else {}
    tid = args.task_id or metrics.get("task_id")
    manifest = load_manifest(Path(__file__).parent / "tasks_10.json", repo)
    task_entry = next((t for t in manifest if t["task_id"] == tid), None)

    out: dict = {
        "sessionKey": args.session_key,
        "sessionFile": sf,
        "taskId": tid,
        "eventCounts": dict(Counter(e.get("event") for e in events)),
        "modelId": metrics.get("modelId"),
        "deviceId": metrics.get("deviceId"),
        "hasSnapshot": snap is not None,
    }
    if snap:
        out["userTurns"] = snap.user_turns
        out["tools"] = snap.tool_counts
        out["tokens"] = snap.total_tokens
        out["planLen"] = len(snap.final_plan_text)
        out["process"] = score_process_metrics(snap, events, metrics)
        if task_entry:
            rubric = score_task_rubrics(task_entry["task_json"], snap, metrics)
            out["reward"] = rubric["reward"]
            out["rubricMet"] = f"{rubric['met']}/{rubric['total']}"
            out["rubrics"] = [{"pass": r["pass"], "rubric": r["rubric"][:60], "detail": r["detail"]} for r in rubric["rubrics"]]

    expected = {"session_start", "intake_shown", "intake_submitted", "tool_progress", "turn_complete", "image_gen_start", "image_gen_complete"}
    got = set(out["eventCounts"])
    out["missingEvents"] = sorted(expected - got)
    out["extraEvents"] = sorted(got - expected - {"model_switch"})

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
