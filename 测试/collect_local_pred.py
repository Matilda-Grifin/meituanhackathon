#!/usr/bin/env python3
"""无 OpenClaw 网关时，用 run_local_agent 的 LLM+MCP 采集 pred（格式与 collect_openclaw_pred 一致）。"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

_BENCH = Path(__file__).resolve().parent
_ROOT = _BENCH.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_BENCH) not in sys.path:
    sys.path.insert(0, str(_BENCH))

from intake_simulator import (  # noqa: E402
    has_intake_pattern,
    looks_like_plan_without_intake,
    scripted_reply_for_turn,
)
from load_cases import load_eval_cases  # noqa: E402
from simulate_user_reply import resolve_user_reply  # noqa: E402

# run_local_agent
sys.path.insert(0, str(_ROOT / "scripts"))
from run_local_agent import run_llm  # noqa: E402


def _trace_to_turn(user_message: str, trace: list[dict], assistant_turn: int) -> dict:
    tools: list[str] = []
    final_text = ""
    for item in trace:
        if item.get("tool"):
            name = str(item["tool"])
            if not name.startswith("lifecare"):
                name = f"lifecare__{name}" if "__" not in name else name
            if name.startswith("lifecare_") and "__" not in name:
                name = f"lifecare__{name}"
            tools.append(name)
        if "final_reply" in item:
            final_text = str(item["final_reply"])
    return {
        "assistant_turn": assistant_turn,
        "user_message": user_message,
        "assistant_text": final_text,
        "tools": tools,
    }


def _collect_case_local(
    case: dict,
    *,
    max_turns: int,
    sim_mode: str,
    disable_amap: bool = False,
) -> dict:
    cid = case["case_id"]
    session_id = f"local-{cid}-{uuid.uuid4().hex[:8]}"
    turns: list[dict] = []
    user_messages: list[str] = []
    tools_in_order: list[str] = []
    msg = case["user_text"]
    t0 = time.perf_counter()

    old_amap = os.environ.get("AMAP_KEY")
    if disable_amap:
        os.environ["AMAP_KEY"] = ""

    try:
        for assistant_turn in range(1, max_turns + 1):
            user_messages.append(msg)
            trace = run_llm(msg, max_turns=8)
            turn = _trace_to_turn(msg, trace, assistant_turn)
            turns.append(turn)
            for t in turn.get("tools") or []:
                tools_in_order.append(t)
            sim = case.get("simulation") or {}
            scripted = scripted_reply_for_turn(
                case,
                assistant_turn=assistant_turn,
                assistant_text=turn.get("assistant_text") or "",
            )
            if not scripted and not (sim.get("replies") or []):
                break
            spec = None
            for r in sim.get("replies") or []:
                if int(r.get("after_assistant_turn", 0)) == assistant_turn:
                    spec = r
                    break
            if spec is None:
                break
            mode = spec.get("reply_mode", sim_mode)
            user_reply, _src = resolve_user_reply(
                scripted,
                assistant_text=turn.get("assistant_text") or "",
                case_user_text=case.get("user_text", ""),
                prior_user_messages=user_messages,
                default_mode=mode,
            )
            if spec.get("reply_mode") == "script" and spec.get("user_message"):
                user_reply = spec["user_message"]
            if not user_reply.strip():
                break
            msg = user_reply
    finally:
        if disable_amap:
            if old_amap is not None:
                os.environ["AMAP_KEY"] = old_amap
            else:
                os.environ.pop("AMAP_KEY", None)

    first_asst = turns[0]["assistant_text"] if turns else ""
    last_asst = turns[-1]["assistant_text"] if turns else ""
    pred = {
        "case_id": cid,
        "assistant_text": last_asst,
        "first_assistant_text": first_asst,
        "tools_in_order": tools_in_order,
        "user_messages": user_messages,
        "turns": turns,
        "simulation_log": [],
        "session_id": session_id,
        "latency_first_token_ms": int((time.perf_counter() - t0) * 1000),
        "failure_hints": [],
        "collect_source": "local_llm",
    }
    if not tools_in_order:
        pred["failure_hints"].append("no_mcp_tools_called")
    return pred


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=Path, default=_BENCH / "eval_cases" / "dev" / "cases.json")
    ap.add_argument("-o", type=Path, default=_BENCH / "results" / "agent_pred_cases_21_24.jsonl")
    ap.add_argument("--only", type=str, default="21,22,23,24")
    ap.add_argument("--max-turns", type=int, default=5)
    ap.add_argument("--dry", action="store_true", help="仅打印 case 列表")
    args = ap.parse_args()

    cases = load_eval_cases(args.cases)
    if args.only.strip():
        allow: set = set()
        for x in args.only.split(","):
            x = x.strip()
            if not x:
                continue
            allow.add(x)
            if x.isdigit():
                allow.add(int(x))
        cases = [c for c in cases if c["case_id"] in allow or str(c["case_id"]) in allow]

    if args.dry:
        for c in cases:
            print(c["case_id"], c.get("difficulty"), c.get("user_text", "")[:60])
        return 0

    if not os.environ.get("LLM_API_KEY", "").strip():
        for alt in ("ARK_API_KEY", "OPENAI_API_KEY"):
            if os.environ.get(alt, "").strip():
                os.environ["LLM_API_KEY"] = os.environ[alt]
                break
    if not os.environ.get("LLM_API_KEY", "").strip():
        print("需要 LLM_API_KEY / ARK_API_KEY / OPENAI_API_KEY 才能本地采集", file=sys.stderr)
        return 2

    preds: list[dict] = []
    args.o.parent.mkdir(parents=True, exist_ok=True)
    for i, case in enumerate(cases):
        cid = case["case_id"]
        disable = bool((case.get("eval") or {}).get("expect_tool_unavailable_ack"))
        print(f"[{i+1}/{len(cases)}] case {cid} disable_amap={disable} …", flush=True)
        pred = _collect_case_local(
            case,
            max_turns=args.max_turns,
            sim_mode="choices",
            disable_amap=disable,
        )
        preds.append(pred)
        with args.o.open("w", encoding="utf-8") as f:
            for p in preds:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
        print(f"  tools={len(pred.get('tools_in_order') or [])} chars={len(pred.get('assistant_text') or '')}")

    print(json.dumps({"out": str(args.o), "cases": len(preds)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
