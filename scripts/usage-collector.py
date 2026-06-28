#!/usr/bin/env python3
"""LifeCare 费用采集：线上 Demo vs 6.3 测评分流。"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

OPENCLAW = Path(os.environ.get("OPENCLAW_HOME", "~/.openclaw")).expanduser()
REPO = Path(
    os.environ.get(
        "LIFECARE_REPO",
        os.environ.get("MEITUAN_REPO", "/root/meituan-lifecare-agent"),
    )
).expanduser()
WS = Path(os.environ.get("OPENCLAW_WORKSPACE", OPENCLAW / "workspace")).expanduser()
AGENTS = OPENCLAW / "agents"
PRICING_PATH = Path(__file__).resolve().parent.parent / "dashboard" / "pricing.json"
if (WS / "dashboard" / "pricing.json").is_file():
    PRICING_PATH = WS / "dashboard" / "pricing.json"

OUT_ONLINE = WS / "logs" / "usage-stats-online.json"
OUT_EVAL = WS / "logs" / "usage-stats-eval.json"
EVAL_LLM_LOG = WS / "logs" / "eval-llm-usage.jsonl"
MCP_LOG_CANDIDATES = [
    REPO / "测试" / "results" / "mcp_tool_calls.jsonl",
    REPO / "benchmark" / "results" / "mcp_tool_calls.jsonl",
    WS / "logs" / "mcp_tool_calls.jsonl",
]
V63_BATCH_CANDIDATES = [
    REPO / "测试" / "模型选型" / "results" / "v63-batch",
    REPO / "benchmark" / "model_selection" / "results" / "v63-batch",
]


def v63_batch_roots() -> list[Path]:
    return [p for p in V63_BATCH_CANDIDATES if p.is_dir()]


def day_key(ts) -> str:
    if isinstance(ts, (int, float)):
        if ts > 1e12:
            ts /= 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    if isinstance(ts, str) and len(ts) >= 10:
        return ts[:10]
    return "unknown"


def week_key(day: str) -> str:
    try:
        d = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError:
        return day
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def month_key(day: str) -> str:
    return day[:7] if len(day) >= 7 else day


def wan(tokens: int) -> float:
    return round(tokens / 10000.0, 2)


def load_pricing() -> dict:
    if PRICING_PATH.is_file():
        return json.loads(PRICING_PATH.read_text(encoding="utf-8"))
    return {}


def get_text_model_cfg(model_id: str, p: dict) -> dict:
    models = p.get("textModels") or {}
    if model_id in models:
        return models[model_id]
    for key, cfg in models.items():
        if key in model_id or model_id in key:
            return cfg
    return models.get("qwen3.6-plus") or {}


def pick_text_tier(inp: int, model_cfg: dict) -> dict:
    tiers = model_cfg.get("tiers") or []
    if not tiers:
        return {
            "inputPerMillion": float(model_cfg.get("inputPerMillion", 0)),
            "outputPerMillion": float(model_cfg.get("outputPerMillion", 0)),
            "cacheReadPerMillion": float(model_cfg.get("cacheReadPerMillion", 0)),
        }
    for tier in tiers:
        if inp <= int(tier.get("maxInputTokens", 0)):
            return tier
    return tiers[-1]


def to_display_cny(amount: float, currency: str, p: dict) -> float:
    if currency.upper() == "USD":
        return amount * float(p.get("fxUsdToCny", 7.25))
    return amount


def cost_text_tokens(
    inp: int, out: int, reas: int, cache_read: int, p: dict, model_id: str
) -> float:
    model_cfg = get_text_model_cfg(model_id, p)
    tier = pick_text_tier(inp, model_cfg)
    in_rate = float(tier.get("inputPerMillion", 0))
    out_rate = float(tier.get("outputPerMillion", 0))
    cache_rate = float(tier.get("cacheReadPerMillion", 0))
    billable_in = max(0, inp - cache_read)
    cost = (
        billable_in * in_rate / 1_000_000
        + cache_read * cache_rate / 1_000_000
        + out * out_rate / 1_000_000
    )
    if reas and model_cfg.get("reasoningUsesOutputPrice", True):
        cost += reas * out_rate / 1_000_000
    return to_display_cny(cost, model_cfg.get("currency", p.get("currency", "CNY")), p)


def is_eval_source(path: str, prefix: str) -> bool:
    low = path.replace("\\", "/").lower()
    return prefix.lower() in low


def normalize_usage(u: dict | None) -> dict:
    u = u or {}
    inp = int(u.get("prompt_tokens") or u.get("input") or u.get("input_tokens") or 0)
    out = int(u.get("completion_tokens") or u.get("output") or u.get("output_tokens") or 0)
    total = int(u.get("total_tokens") or u.get("total") or inp + out)
    reas = int(u.get("reasoning_tokens") or u.get("reasoningTokens") or 0)
    cache = int(u.get("cache_read_tokens") or u.get("cacheRead") or 0)
    return {"input": inp, "output": out, "total": total, "reasoning": reas, "cacheRead": cache}


def merge_usage_bucket(bucket: dict, usage: dict, cost: float) -> None:
    bucket["input"] += usage["input"]
    bucket["output"] += usage["output"]
    bucket["reasoning"] += usage["reasoning"]
    bucket["total"] += usage["total"]
    bucket["cacheRead"] += usage["cacheRead"]
    bucket["runs"] += 1
    bucket["cost"] += cost


def empty_bucket() -> dict:
    return dict(input=0, output=0, reasoning=0, total=0, runs=0, cost=0.0, cacheRead=0)


def scan_trajectories(pricing: dict, *, eval_mode: bool) -> tuple[dict, dict, dict]:
    prefix = pricing.get("evalSessionPrefix") or "v63-"
    daily: dict[str, dict] = defaultdict(empty_bucket)
    by_model: dict[str, dict] = defaultdict(empty_bucket)
    totals = empty_bucket()
    seen: set[tuple[str, str]] = set()

    for path in glob.glob(str(AGENTS / "**" / "*.trajectory.jsonl"), recursive=True):
        path_eval = is_eval_source(path, prefix)
        if eval_mode != path_eval:
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if o.get("type") != "model.completed":
                    continue
                data = o.get("data") or {}
                u = normalize_usage(data.get("usage"))
                if not u["total"] and not u["input"]:
                    continue
                run = str(o.get("runId") or o.get("traceId") or "")
                key = (path, run)
                if key in seen:
                    continue
                seen.add(key)
                model = o.get("modelId") or "qwen3.6-plus"
                event_cost = cost_text_tokens(
                    u["input"], u["output"], u["reasoning"], u["cacheRead"], pricing, model
                )
                dk = day_key(o.get("ts") or 0)
                for bucket in (daily[dk], by_model[model], totals):
                    merge_usage_bucket(bucket, u, event_cost)
    return daily, by_model, totals


def mcp_tool_cost(tool: str, pricing: dict) -> float:
    cfg = (pricing.get("mcpTools") or {}).get(tool) or {}
    if not cfg:
        short = tool.replace("lifecare__", "").replace("lifecare_", "")
        cfg = (pricing.get("mcpTools") or {}).get(short) or {}
    return float(cfg.get("perCall") or 0)


def scan_mcp_log(pricing: dict, *, eval_mode: bool) -> tuple[dict, dict, dict]:
    """MCP 日志无 session 时：仅计入线上看板（eval 看板不重复计 MCP）。"""
    if eval_mode:
        return {}, {}, {"calls": 0, "cost": 0.0, "tools": {}}
    daily: dict[str, dict] = defaultdict(lambda: {"calls": 0, "cost": 0.0, "tools": defaultdict(int)})
    by_tool: dict[str, int] = defaultdict(int)
    totals = {"calls": 0, "cost": 0.0, "tools": {}}
    log_path = next((p for p in MCP_LOG_CANDIDATES if p.is_file()), None)
    if not log_path:
        return daily, by_tool, totals
    with open(log_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            tool = str(o.get("tool") or "unknown")
            if not o.get("ok", True):
                continue
            dk = day_key(o.get("ts") or 0)
            c = mcp_tool_cost(tool, pricing)
            daily[dk]["calls"] += 1
            daily[dk]["cost"] += c
            daily[dk]["tools"][tool] += 1
            by_tool[tool] += 1
            totals["calls"] += 1
            totals["cost"] += c
    totals["tools"] = dict(by_tool)
    totals["cost"] = round(totals["cost"], 4)
    return daily, dict(by_tool), totals


def scan_eval_llm_log(pricing: dict) -> tuple[dict, dict, dict, list]:
    daily: dict[str, dict] = defaultdict(lambda: defaultdict(empty_bucket))
    by_role: dict[str, dict] = defaultdict(empty_bucket)
    by_model: dict[str, dict] = defaultdict(empty_bucket)
    by_batch: dict[str, dict] = defaultdict(lambda: {"cost": 0.0, "tokens": 0, "tasks": set()})
    events: list[dict] = []

    paths = [EVAL_LLM_LOG]
    if (REPO / "logs" / "eval-llm-usage.jsonl").is_file():
        paths.append(REPO / "logs" / "eval-llm-usage.jsonl")

    for log_path in paths:
        if not log_path.is_file():
            continue
        with open(log_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                events.append(o)
                u = normalize_usage(o.get("usage"))
                model = o.get("model") or "unknown"
                role = o.get("role") or "eval_llm"
                dk = day_key(o.get("ts") or 0)
                cost = cost_text_tokens(
                    u["input"], u["output"], u["reasoning"], u["cacheRead"], pricing, model
                )
                for bucket in (daily[dk][role], by_role[role], by_model[model]):
                    merge_usage_bucket(bucket, u, cost)
                batch = o.get("batch") or o.get("batch_alias") or "unknown"
                by_batch[batch]["cost"] += cost
                by_batch[batch]["tokens"] += u["total"]
                if o.get("task_id"):
                    by_batch[batch]["tasks"].add(o["task_id"])

    batch_rows = []
    for name, b in sorted(by_batch.items()):
        batch_rows.append(
            {
                "batch": name,
                "cost": round(b["cost"], 4),
                "tokens": b["tokens"],
                "tokensWan": wan(b["tokens"]),
                "tasks": len(b["tasks"]),
            }
        )
    return daily, by_role, by_model, batch_rows


def scan_run_json_usage(pricing: dict) -> tuple[dict, list]:
    """从 v63-batch run.json 读取 orchestrator 写入的 token_usage。"""
    by_role = defaultdict(empty_bucket)
    task_rows: list[dict] = []
    roots = v63_batch_roots()
    if not roots:
        return dict(by_role), task_rows

    for batch_root in roots:
        for run_path in sorted(batch_root.glob("*/*_run.json")):
            try:
                run = json.loads(run_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            tu = run.get("token_usage") or {}
            batch = run_path.parent.name
            task_id = run.get("task_id") or run_path.stem.replace("_run", "")
            task_cost = 0.0
            task_tokens = 0
            for role, usage in tu.items():
                if not isinstance(usage, dict):
                    continue
                u = normalize_usage(usage)
                model = usage.get("model") or {
                    "agent": "qwen3.6-plus",
                    "user_sim": "deepseek/deepseek-v4-flash",
                    "judge": "openai/gpt-5.5",
                }.get(role, "unknown")
                cost = cost_text_tokens(
                    u["input"], u["output"], u["reasoning"], u["cacheRead"], pricing, str(model)
                )
                merge_usage_bucket(by_role[role], u, cost)
                task_cost += cost
                task_tokens += u["total"]
            if tu:
                task_rows.append(
                    {
                        "batch": batch,
                        "task_id": task_id,
                        "cost": round(task_cost, 4),
                        "tokensWan": wan(task_tokens),
                        "termination": run.get("termination"),
                    }
                )
    return dict(by_role), task_rows


def aggregate_period(rows: list[dict]) -> dict:
    cats = defaultdict(lambda: {"tokens": 0, "cost": 0.0, "calls": 0, "runs": 0})
    for row in rows:
        for k, c in (row.get("categories") or {}).items():
            cats[k]["tokens"] += c.get("tokens", 0)
            cats[k]["cost"] = round(cats[k]["cost"] + c.get("cost", 0), 4)
            cats[k]["calls"] += c.get("calls", 0)
            cats[k]["runs"] += c.get("runs", 0)
    for k in cats:
        cats[k]["tokensWan"] = wan(cats[k]["tokens"])
    total_tok = sum(c["tokens"] for c in cats.values())
    total_cost = round(sum(c["cost"] for c in cats.values()), 4)
    return {"categories": dict(cats), "tokens": total_tok, "tokensWan": wan(total_tok), "cost": total_cost}


def build_daily_rows(chat_daily, mcp_daily, extra_daily, pricing, *, include_mcp: bool) -> list[dict]:
    all_days = sorted(set(chat_daily) | set(mcp_daily) | set(extra_daily))
    rows = []
    for d in all_days:
        c = chat_daily.get(d) or empty_bucket()
        m = mcp_daily.get(d) or {"calls": 0, "cost": 0.0, "tools": {}}
        cats = {
            "text": {
                "tokens": c["total"],
                "tokensWan": wan(c["total"]),
                "cost": round(c["cost"], 4),
                "runs": c["runs"],
            }
        }
        if include_mcp:
            cats["mcp"] = {
                "tokens": 0,
                "tokensWan": 0,
                "cost": round(m.get("cost", 0), 4),
                "calls": m.get("calls", 0),
            }
        for role, buckets in (extra_daily.get(d) or {}).items():
            if isinstance(buckets, dict) and "total" in buckets:
                b = buckets
            else:
                continue
            cats[role] = {
                "tokens": b["total"],
                "tokensWan": wan(b["total"]),
                "cost": round(b["cost"], 4),
                "runs": b["runs"],
            }
        total_cost = round(sum(x["cost"] for x in cats.values()), 4)
        total_tok = sum(x.get("tokens", 0) for x in cats.values())
        rows.append(
            {
                "date": d,
                "week": week_key(d),
                "month": month_key(d),
                "tokens": total_tok,
                "tokensWan": wan(total_tok),
                "cost": total_cost,
                "categories": cats,
            }
        )
    return rows


def collect_mode(mode: str) -> dict:
    pricing = load_pricing()
    eval_mode = mode == "eval"

    chat_daily, by_model, chat_totals = scan_trajectories(pricing, eval_mode=eval_mode)
    mcp_daily, by_mcp_tool, mcp_totals = scan_mcp_log(pricing, eval_mode=eval_mode)

    extra_daily: dict = defaultdict(dict)
    by_role = {}
    batch_rows: list[dict] = []
    task_rows: list[dict] = []
    if eval_mode:
        llm_daily, by_role, by_eval_model, batch_from_log = scan_eval_llm_log(pricing)
        run_roles, task_rows = scan_run_json_usage(pricing)
        for role, bucket in run_roles.items():
            if role not in by_role:
                by_role[role] = empty_bucket()
            for k in ("input", "output", "reasoning", "total", "runs", "cacheRead"):
                by_role[role][k] += bucket.get(k, 0)
            by_role[role]["cost"] += bucket.get("cost", 0)
        for d, roles in llm_daily.items():
            extra_daily[d] = roles
        if batch_from_log:
            batch_rows = batch_from_log

    include_mcp = not eval_mode
    daily_rows = build_daily_rows(chat_daily, mcp_daily, extra_daily, pricing, include_mcp=include_mcp)

    weekly: dict[str, list] = defaultdict(list)
    monthly: dict[str, list] = defaultdict(list)
    for row in daily_rows:
        weekly[row["week"]].append(row)
        monthly[row["month"]].append(row)

    def period_table(groups: dict) -> list:
        return [dict(period=k, **aggregate_period(groups[k])) for k in sorted(groups)]

    totals_cats = aggregate_period(daily_rows)["categories"] if daily_rows else {"text": {"tokens": 0, "cost": 0, "tokensWan": 0, "runs": 0}}
    if include_mcp and mcp_totals.get("calls"):
        totals_cats.setdefault("mcp", {"tokens": 0, "tokensWan": 0, "cost": 0, "calls": 0})
        totals_cats["mcp"]["cost"] = round(mcp_totals["cost"], 4)
        totals_cats["mcp"]["calls"] = mcp_totals["calls"]

    total_cost = round(sum(c.get("cost", 0) for c in totals_cats.values()), 4)
    total_tok = chat_totals["total"] + sum(
        (by_role.get(r) or {}).get("total", 0) for r in by_role
    )

    notes = [
        "估算费用，非官方账单；对账以 DashScope / OpenRouter / 高德控制台为准。",
        "文字：OpenClaw trajectory 中 model.completed 事件。",
    ]
    if eval_mode:
        notes.append("测试看板：session 前缀 v63- 的轨迹 + eval-llm-usage.jsonl + run.json token_usage。")
    else:
        notes.append("线上看板：非 v63- session 轨迹 + MCP 工具日志（测试期间 MCP 可能略混入）。")
        notes.append("不展示 ECS 固定基础设施成本。")

    result = {
        "mode": mode,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "source": str(OPENCLAW),
        "repo": str(REPO),
        "pricingFile": str(PRICING_PATH),
        "summary": {
            "tokens": total_tok,
            "tokensWan": wan(total_tok),
            "cost": total_cost,
            "textRuns": chat_totals["runs"],
            "mcpCalls": mcp_totals.get("calls", 0) if include_mcp else 0,
            "categories": totals_cats,
        },
        "byModel": {
            m: {
                **v,
                "tokensWan": wan(v["total"]),
                "label": get_text_model_cfg(m, pricing).get("label", m),
                "provider": get_text_model_cfg(m, pricing).get("provider", ""),
            }
            for m, v in sorted(by_model.items(), key=lambda x: -x[1]["total"])
        },
        "byMcpTool": {
            t: {
                "calls": n,
                "cost": round(n * mcp_tool_cost(t, pricing), 4),
                "label": (pricing.get("mcpTools") or {}).get(t, {}).get("label", t),
            }
            for t, n in sorted(by_mcp_tool.items(), key=lambda x: -x[1])
        },
        "daily": daily_rows,
        "weekly": period_table(weekly),
        "monthly": period_table(monthly),
        "notes": notes,
    }

    if eval_mode:
        result["evalOnly"] = {
            "byRole": {
                r: {**b, "tokensWan": wan(b["total"]), "label": (pricing.get("roleLabels") or {}).get(r, r)}
                for r, b in by_role.items()
            },
            "byBatch": batch_rows,
            "byTask": sorted(task_rows, key=lambda x: (-x.get("cost", 0), x.get("task_id", ""))),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("online", "eval", "all"), default="all")
    args = parser.parse_args()
    modes = ["online", "eval"] if args.mode == "all" else [args.mode]
    for m in modes:
        data = collect_mode(m)
        out = OUT_ONLINE if m == "online" else OUT_EVAL
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {out} cost={data['summary']['cost']} CNY")


if __name__ == "__main__":
    main()
