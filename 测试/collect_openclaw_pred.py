#!/usr/bin/env python3
"""
从 OpenClaw CLI 采集 Agent 预测；支持多轮模拟用户答 intake 选择题并写审计日志。

用法：
  python benchmark/collect_openclaw_pred.py
  python benchmark/collect_openclaw_pred.py --cases benchmark/eval_cases/dev/cases.json
  python benchmark/collect_openclaw_pred.py --max-turns 5 --session-prefix eval
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

_BENCH = Path(__file__).resolve().parent
_ROOT = _BENCH.parent
if str(_BENCH) not in sys.path:
    sys.path.insert(0, str(_BENCH))

from intake_simulator import (  # noqa: E402
    audit_entry,
    has_intake_pattern,
    looks_like_plan_without_intake,
    parse_option_letters,
    scripted_reply_for_turn,
)
from load_cases import load_eval_cases  # noqa: E402
from simulate_user_reply import llm_available, resolve_user_reply  # noqa: E402


def _find_openclaw() -> str | None:
    return shutil.which("openclaw") or shutil.which("openclaw.cmd")


_OPENCLAW_CFG = Path.home() / ".openclaw" / "openclaw.json"


def _set_lifecare_amap_key(amap_key: str) -> dict | None:
    """临时改写 openclaw.json 里 lifecare MCP 的 AMAP_KEY（case 21 降级评测）。"""
    if not _OPENCLAW_CFG.is_file():
        return None
    data = json.loads(_OPENCLAW_CFG.read_text(encoding="utf-8"))
    lifecare = ((data.get("mcp") or {}).get("servers") or {}).get("lifecare")
    if not lifecare:
        return None
    env = dict(lifecare.get("env") or {})
    backup = {"amap_key": env.get("AMAP_KEY")}
    env["AMAP_KEY"] = amap_key
    lifecare["env"] = env
    _OPENCLAW_CFG.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return backup


def _restore_lifecare_amap_key(backup: dict | None) -> None:
    if not backup or not _OPENCLAW_CFG.is_file():
        return
    data = json.loads(_OPENCLAW_CFG.read_text(encoding="utf-8"))
    lifecare = ((data.get("mcp") or {}).get("servers") or {}).get("lifecare")
    if not lifecare:
        return
    env = dict(lifecare.get("env") or {})
    if backup.get("amap_key") is not None:
        env["AMAP_KEY"] = backup["amap_key"]
    lifecare["env"] = env
    _OPENCLAW_CFG.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run_agent(message: str, *, timeout_s: int, session_id: str) -> dict | None:
    exe = _find_openclaw()
    if not exe:
        return {"error": "openclaw not found"}
    cmd = [
        exe,
        "agent",
        "--agent",
        "main",
        "-m",
        message,
        "--json",
        "--session-id",
        session_id,
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
        )
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "message": message}
    if proc.returncode != 0 and not proc.stdout.strip():
        return {"error": proc.stderr.strip() or f"exit {proc.returncode}", "message": message}
    raw = proc.stdout.strip()
    if not raw:
        return {"error": "empty stdout", "stderr": proc.stderr[:500]}
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < 0:
        return {"error": "no json in stdout", "raw_head": raw[:400]}
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError as e:
        return {"error": f"json parse: {e}", "raw_head": raw[:400]}


def _extract_tool_calls(meta: dict, doc: dict | None) -> list[dict]:
    """§6.1：从 OpenClaw meta 抽取 tool_calls（name/arguments/ok/error/duration_ms）。"""
    calls: list[dict] = []
    for src in (
        meta.get("toolCalls"),
        meta.get("tool_calls"),
        meta.get("toolsDetail"),
        (doc or {}).get("toolCalls"),
    ):
        if not isinstance(src, list):
            continue
        for item in src:
            if not isinstance(item, dict):
                continue
            calls.append(
                {
                    "name": item.get("name") or item.get("tool"),
                    "arguments": item.get("arguments") or item.get("args"),
                    "ok": item.get("ok"),
                    "error": item.get("error"),
                    "duration_ms": item.get("durationMs") or item.get("duration_ms"),
                }
            )
    return calls


def _merge_token_usage(acc: dict, meta: dict) -> dict:
    u = meta.get("usage") or meta.get("tokenUsage") or {}
    if not isinstance(u, dict):
        return acc
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        v = u.get(k) or u.get(k.replace("_", ""))
        if v is not None:
            acc[k] = int(acc.get(k) or 0) + int(v)
    if not acc.get("total_tokens") and acc.get("prompt_tokens") and acc.get("completion_tokens"):
        acc["total_tokens"] = acc["prompt_tokens"] + acc["completion_tokens"]
    return acc


def _extract_turn(doc: dict | None) -> dict:
    if doc is None or doc.get("error"):
        return {
            "assistant_text": "",
            "tools": [],
            "tool_calls": [],
            "error": (doc or {}).get("error", "unknown"),
        }
    tools: list[str] = []
    meta = doc.get("meta") or {}
    ts = meta.get("toolSummary") or {}
    if isinstance(ts.get("tools"), list):
        tools = list(ts["tools"])
    tool_calls = _extract_tool_calls(meta, doc)
    if not tools and tool_calls:
        tools = [str(c.get("name") or "") for c in tool_calls if c.get("name")]
    text = (
        meta.get("finalAssistantVisibleText")
        or meta.get("finalAssistantRawText")
        or ""
    )
    if not text:
        payloads = doc.get("payloads") or []
        if payloads and isinstance(payloads[0], dict):
            text = str(payloads[0].get("text") or "")
    timing = {
        "duration_ms": meta.get("durationMs"),
        "time_to_first_progress_ms": meta.get("timeToFirstProgressMs"),
        "time_to_first_assistant_text_ms": meta.get("timeToFirstAssistantTextMs"),
    }
    return {
        "assistant_text": text,
        "tools": tools,
        "tool_calls": tool_calls,
        "meta": meta,
        **{k: v for k, v in timing.items() if v is not None},
    }


def _collect_case(
    case: dict,
    *,
    timeout_s: int,
    max_turns: int,
    session_prefix: str,
    sim_mode: str = "choices",
) -> tuple[dict, list[dict]]:
    cid = case["case_id"]
    session_id = f"{session_prefix}-{cid}-{uuid.uuid4().hex[:8]}"
    sim_log: list[dict] = []
    turns: list[dict] = []
    user_messages: list[str] = []
    tools_in_order: list[str] = []
    tool_calls_detail: list[dict] = []
    token_usage: dict = {}
    msg = case["user_text"]
    t0 = time.perf_counter()
    assistant_turn = 0
    sent_sim_keys: set[str] = set()
    stage_timings: dict = {}
    amap_override = (case.get("eval") or {}).get("collect_amap_key_override")
    amap_backup = _set_lifecare_amap_key(amap_override) if amap_override else None

    try:
        for _ in range(max_turns):
            doc = _run_agent(msg, timeout_s=timeout_s, session_id=session_id)
            turn_data = _extract_turn(doc)
            asst = turn_data["assistant_text"]
            assistant_turn += 1
            for t in turn_data["tools"]:
                tools_in_order.append(t)
            for tc in turn_data.get("tool_calls") or []:
                tool_calls_detail.append({**tc, "turn": assistant_turn})
            if turn_data.get("meta"):
                token_usage = _merge_token_usage(token_usage, turn_data["meta"])
            if assistant_turn == 1:
                if turn_data.get("time_to_first_assistant_text_ms") is not None:
                    stage_timings["intake_first_visible_s"] = round(
                        turn_data["time_to_first_assistant_text_ms"] / 1000.0, 2
                    )
                if turn_data.get("time_to_first_progress_ms") is not None:
                    stage_timings["tool_progress_visible_s"] = round(
                        turn_data["time_to_first_progress_ms"] / 1000.0, 2
                    )
            if turn_data["tools"] and turn_data.get("duration_ms"):
                stage_timings.setdefault(
                    "post_tool_long_reply_s",
                    round(turn_data["duration_ms"] / 1000.0, 2),
                )
            turns.append(
                {
                    "assistant_turn": assistant_turn,
                    "user_message": msg,
                    "assistant_text": asst,
                    "tools": turn_data["tools"],
                    "tool_calls": turn_data.get("tool_calls") or [],
                    "error": turn_data.get("error"),
                    "duration_ms": turn_data.get("duration_ms"),
                    "time_to_first_progress_ms": turn_data.get("time_to_first_progress_ms"),
                    "time_to_first_assistant_text_ms": turn_data.get("time_to_first_assistant_text_ms"),
                }
            )
            user_messages.append(msg)

            if turn_data.get("error"):
                break

            scripted = scripted_reply_for_turn(case, assistant_turn)
            if not scripted:
                break

            mode = (scripted.get("reply_mode") or sim_mode).lower()
            user_reply, reply_source = resolve_user_reply(
                scripted,
                assistant_text=asst,
                case_user_text=case.get("user_text", ""),
                prior_user_messages=user_messages,
                default_mode=mode,
            )
            sim_key = f"{assistant_turn}:{user_reply}"
            if sim_key in sent_sim_keys:
                break
            sent_sim_keys.add(sim_key)
            sim_log.append(
                audit_entry(
                    case_id=cid,
                    turn=assistant_turn,
                    assistant_excerpt=asst,
                    parsed_options=parse_option_letters(asst),
                    scripted=scripted,
                    user_reply=user_reply,
                    reply_source=reply_source,
                )
            )
            msg = user_reply
    finally:
        _restore_lifecare_amap_key(amap_backup)

    first_asst = turns[0]["assistant_text"] if turns else ""
    last_asst = turns[-1]["assistant_text"] if turns else ""

    elapsed_s = round(time.perf_counter() - t0, 2)
    stage_timings["total_elapsed_s"] = elapsed_s

    pred = {
        "case_id": cid,
        "assistant_text": last_asst,
        "first_assistant_text": first_asst,
        "tools_in_order": tools_in_order,
        "tool_calls_detail": tool_calls_detail,
        "token_usage": token_usage or None,
        "stage_timings": stage_timings,
        "elapsed_s": elapsed_s,
        "user_messages": user_messages,
        "turns": turns,
        "simulation_log": sim_log,
        "session_id": session_id,
        "latency_first_token_ms": int(elapsed_s * 1000),
        "failure_hints": [],
    }
    if not has_intake_pattern(first_asst) and looks_like_plan_without_intake(first_asst):
        pred["failure_hints"].append("first_turn_skipped_intake_or_direct_plan")
    if looks_like_plan_without_intake(first_asst) and not (turns and turns[0].get("tools")):
        pred["failure_hints"].append("first_turn_hallucinated_plan_without_tools")
    if not tools_in_order:
        pred["failure_hints"].append("no_mcp_tools_called")
    first_tools = (turns[0].get("tools") if turns else []) or []
    if first_tools and "first_turn_hallucinated_plan_without_tools" in pred["failure_hints"]:
        pred["failure_hints"] = [
            h for h in pred["failure_hints"] if h != "first_turn_hallucinated_plan_without_tools"
        ]
    return pred, sim_log


def _load_preds_by_id(path: Path) -> dict[int, dict]:
    by_id: dict[int, dict] = {}
    if not path.is_file():
        return by_id
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        by_id[row["case_id"]] = row
    return by_id


def _write_preds_ordered(path: Path, case_order: list[dict], preds_by_id: dict[int, dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for case in case_order:
            cid = case["case_id"]
            if cid not in preds_by_id:
                continue
            f.write(json.dumps(preds_by_id[cid], ensure_ascii=False) + "\n")
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=Path, default=_BENCH / "eval_cases" / "dev" / "cases.json")
    ap.add_argument("-o", "--out", type=Path, default=_BENCH / "results" / "agent_pred_live.jsonl")
    ap.add_argument(
        "--audit-out",
        type=Path,
        default=_BENCH / "results" / "simulation_audit.jsonl",
    )
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--max-turns", type=int, default=5)
    ap.add_argument("--session-prefix", type=str, default="eval")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", type=str, default="", help="逗号分隔 case_id")
    ap.add_argument(
        "--resume",
        action="store_true",
        help="若输出文件已有 case_id 则跳过采集（断点续跑）；最终按考卷顺序重写 jsonl",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="与 --resume 同用时强制重采已有 case_id",
    )
    ap.add_argument(
        "--sim-mode",
        choices=("auto", "choices", "script", "llm"),
        default="choices",
        help="模拟用户：choices=按 user_facts 匹配 A/B/C（默认）；auto=有 facts 则 choices；llm=口语",
    )
    args = ap.parse_args()

    all_cases = load_eval_cases(args.cases)
    cases = all_cases
    if args.only.strip():
        allow: set = set()
        for x in args.only.split(","):
            x = x.strip()
            if not x:
                continue
            allow.add(x)
            if x.isdigit():
                allow.add(int(x))
        cases = [c for c in all_cases if c["case_id"] in allow or str(c["case_id"]) in allow]

    if args.dry_run:
        for c in cases:
            sim = c.get("simulation") or {}
            print(c["case_id"], "→", c.get("user_text", "")[:50])
            for r in sim.get("replies") or []:
                mode = r.get("reply_mode", args.sim_mode)
                print(f"  sim mode={mode} hint={(r.get('intent_hint') or '')[:50]}")
        print("llm_available:", llm_available())
        return 0

    if not _find_openclaw():
        print("未找到 openclaw", file=sys.stderr)
        return 2

    preds_by_id = _load_preds_by_id(args.out) if args.resume else {}
    if args.resume and preds_by_id:
        print(f"resume: loaded {len(preds_by_id)} existing rows from {args.out}", flush=True)

    all_audit: list[dict] = []
    args.out.parent.mkdir(parents=True, exist_ok=True)
    collected = 0
    skipped = 0

    for i, case in enumerate(cases):
        cid = case["case_id"]
        if args.resume and cid in preds_by_id and not args.force:
            skipped += 1
            print(f"[{i+1}/{len(cases)}] {cid} skip (resume)", flush=True)
            continue
        print(f"[{i+1}/{len(cases)}] {cid} …", flush=True)
        pred, audit = _collect_case(
            case,
            timeout_s=args.timeout,
            max_turns=args.max_turns,
            session_prefix=args.session_prefix,
            sim_mode=args.sim_mode,
        )
        preds_by_id[cid] = pred
        all_audit.extend(audit)
        collected += 1
        write_order = all_cases if args.resume and not args.only.strip() else cases
        n = _write_preds_ordered(args.out, write_order, preds_by_id)
        hints = pred.get("failure_hints") or []
        print(
            f"  turns={len(pred.get('turns') or [])} tools={pred.get('tools_in_order')} "
            f"sim_steps={len(audit)} hints={hints} (file rows={n})",
            flush=True,
        )

    write_order = all_cases if (args.resume and not args.only.strip()) else cases
    total_rows = _write_preds_ordered(args.out, write_order, preds_by_id)
    if all_audit:
        mode = "a" if args.resume and args.audit_out.is_file() else "w"
        with args.audit_out.open(mode, encoding="utf-8") as f:
            for a in all_audit:
                f.write(json.dumps(a, ensure_ascii=False) + "\n")
    print(
        f"wrote {args.out} ({total_rows} rows, collected={collected}, skipped={skipped}), "
        f"audit {args.audit_out}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
