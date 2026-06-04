#!/usr/bin/env python3
"""
生成 VitaBench 风格选型报告：表格 + 图表 + HTML。

对标论文（VitaBench / 美团模型测评论文）：
  - Table 3 风格：分 domain（easy/medium/hard）× 指标（Avg / Pass@1 / task_success）
  - Fig 5：Performance vs Turns 散点
  - Fig 7：子集规模 vs 指标稳定性（bootstrap MSE）
  - Fig 9：失败类型分布饼图
  - 额外：6 模型总览表、Token 成本柱图、多轮 5 指标雷达/柱图

用法：
  python 模型选型/generate_report.py --run-id smoke-doubao-v1
  python 模型选型/generate_report.py --run-id 20260602-full
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_MODEL_SEL = Path(__file__).resolve().parent
_BENCH = _MODEL_SEL.parent

# matplotlib 可选：无则只出 JSON/HTML 表
try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    HAS_MPL = True
except ImportError:
    HAS_MPL = False

FAILURE_BUCKETS = {
    "intake": r"intake|should_ask",
    "tool_order": r"forbidden_tools|required_tools|tool",
    "plan_quality": r"plan_completeness|plan_route|must_contain",
    "refusal": r"refusal|illegal",
    "degrade": r"degrade|tool_down",
    "schedule": r"schedule|conflict|replan",
    "score": r"total_score",
    "simulation": r"simulation",
}


def _load_json(path: Path) -> dict | list | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _model_labels(cfg: dict) -> dict[str, str]:
    return {m["alias"]: m.get("label", m["alias"]) for m in cfg.get("models", [])}


def _avg_score(eval_report: dict) -> float:
    scores = [r.get("total_score", 0) for r in eval_report.get("results") or []]
    return round(sum(scores) / len(scores), 1) if scores else 0.0


def _domain_metrics(eval_report: dict) -> dict[str, dict[str, float]]:
    """Table 3 风格：按 difficulty 分 domain。"""
    by_diff: dict[str, list[dict]] = defaultdict(list)
    for r in eval_report.get("results") or []:
        diff = r.get("difficulty") or "unknown"
        by_diff[diff].append(r)

    out = {}
    for diff, rows in by_diff.items():
        n = len(rows) or 1
        out[diff] = {
            "avg_score": round(sum(r.get("total_score", 0) for r in rows) / n, 1),
            "pass_rate": round(100 * sum(1 for r in rows if r.get("pass")) / n, 1),
            "task_success_rate": round(100 * sum(1 for r in rows if r.get("task_success")) / n, 1),
            "count": len(rows),
        }
    return out


def _token_totals(preds: list[dict]) -> dict[str, int]:
    pt, ct, tt = 0, 0, 0
    for p in preds:
        u = p.get("token_usage") or {}
        pt += int(u.get("prompt_tokens") or 0)
        ct += int(u.get("completion_tokens") or 0)
        tt += int(u.get("total_tokens") or 0)
    return {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": tt}


def _turn_stats(preds: list[dict]) -> dict[str, float]:
    turns = [len(p.get("turns") or []) or 1 for p in preds]
    if not turns:
        return {"avg_turns": 0, "max_turns": 0}
    return {
        "avg_turns": round(sum(turns) / len(turns), 2),
        "max_turns": max(turns),
    }


def _classify_failure(reasons: list[str]) -> str:
    text = " ".join(reasons).lower()
    for bucket, pat in FAILURE_BUCKETS.items():
        if re.search(pat, text, re.I):
            return bucket
    return "other"


def _error_distribution(eval_report: dict) -> dict[str, int]:
    cnt: Counter[str] = Counter()
    for r in eval_report.get("results") or []:
        if r.get("task_success"):
            continue
        reasons = r.get("reasons_fail") or r.get("failures") or []
        if isinstance(reasons, list):
            bucket = _classify_failure([str(x) for x in reasons])
        else:
            bucket = "other"
        cnt[bucket] += 1
    return dict(cnt)


def _bootstrap_mse(values: list[float], runs: list[int], seed: int = 42) -> list[float]:
    """Fig 7 风格：不同子集规模下 task_success 估计的 MSE。"""
    rng = random.Random(seed)
    if not values:
        return [0.0] * len(runs)
    true_mean = sum(values) / len(values)
    mses = []
    for k in runs:
        if k >= len(values):
            mses.append(0.0)
            continue
        estimates = []
        for _ in range(200):
            sample = rng.choices(values, k=k)
            estimates.append(sum(sample) / k)
        mse = sum((e - true_mean) ** 2 for e in estimates) / len(estimates)
        mses.append(round(mse * 1000, 4))  # ×1000 便于读
    return mses


def collect_run_data(run_dir: Path, cfg: dict) -> dict[str, Any]:
    labels = _model_labels(cfg)
    models_data = {}
    for model_dir in sorted(run_dir.iterdir()):
        if not model_dir.is_dir() or model_dir.name in ("figures", "report"):
            continue
        alias = model_dir.name
        entry: dict[str, Any] = {"alias": alias, "label": labels.get(alias, alias)}
        for ds in ("singleturn", "multiturn"):
            ev = _load_json(model_dir / f"eval_{ds}.json")
            preds = _load_jsonl(model_dir / f"pred_{ds}.jsonl")
            if not ev:
                continue
            entry[ds] = {
                "task_success_rate_pct": ev.get("task_success_rate_pct"),
                "passed": ev.get("passed"),
                "total": ev.get("cases"),
                "avg_score": _avg_score(ev),
                "by_difficulty": _domain_metrics(ev),
                "token_usage": _token_totals(preds),
                "turn_stats": _turn_stats(preds),
                "error_distribution": _error_distribution(ev),
                "task_success_values": [
                    1.0 if r.get("task_success") else 0.0 for r in ev.get("results") or []
                ],
            }
            if ds == "multiturn":
                mt = _load_json(model_dir / "multiturn_metrics.json")
                if mt:
                    entry[ds]["multiturn"] = {
                        "history_constraint_rate_avg": mt.get("history_constraint_rate_avg"),
                        "followup_efficiency_rate_avg": mt.get("followup_efficiency_rate_avg"),
                        "replan_success_rate": mt.get("replan_success_rate"),
                        "tool_compliance_rate_avg": mt.get("tool_compliance_rate_avg"),
                        "execution_success_rate": mt.get("execution_success_rate"),
                    }
        models_data[alias] = entry
    return models_data


def _plot_table3(models_data: dict, dataset: str, fig_dir: Path) -> str | None:
    if not HAS_MPL:
        return None
    domains = ["easy", "medium", "hard"]
    aliases = list(models_data.keys())
    if not aliases:
        return None

    fig, axes = plt.subplots(1, 3, figsize=(14, max(4, len(aliases) * 0.45)))
    metrics = [
        ("avg_score", "Avg Score"),
        ("pass_rate", "Pass Rate (%)"),
        ("task_success_rate", "Task Success (%)"),
    ]
    for ax, (mk, title) in zip(axes, metrics):
        for i, alias in enumerate(aliases):
            dom = (models_data[alias].get(dataset) or {}).get("by_difficulty") or {}
            vals = [dom.get(d, {}).get(mk, 0) for d in domains]
            y = [i] * 3
            ax.barh(y, vals, height=0.2, left=[0, 0, 0], alpha=0.7)
            for j, v in enumerate(vals):
                ax.text(v + 0.5, i + (j - 1) * 0.08, f"{domains[j][:1]}:{v}", fontsize=7)
        ax.set_yticks(range(len(aliases)))
        ax.set_yticklabels([a for a in aliases], fontsize=8)
        ax.set_title(title)
        ax.set_xlabel("Score")
    fig.suptitle(f"Table-3 style: {dataset} by difficulty (e/m/h)")
    fig.tight_layout()
    out = fig_dir / f"table3_{dataset}.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out.name


def _plot_performance_vs_turns(models_data: dict, dataset: str, fig_dir: Path) -> str | None:
    if not HAS_MPL:
        return None
    fig, ax = plt.subplots(figsize=(8, 5))
    for alias, data in models_data.items():
        ds = data.get(dataset) or {}
        if not ds:
            continue
        perf = ds.get("avg_score") or ds.get("task_success_rate_pct") or 0
        turns = (ds.get("turn_stats") or {}).get("avg_turns") or 1
        group = "domestic" if alias in ("doubao", "deepseek", "qwen") else "overseas"
        color = "#e74c3c" if group == "domestic" else "#3498db"
        ax.scatter(turns, perf, s=80, c=color, alpha=0.85)
        ax.annotate(alias, (turns, perf), fontsize=7, xytext=(4, 4), textcoords="offset points")
    ax.set_xlabel("Avg Turns (Fig 5 style)")
    ax.set_ylabel("Performance (Avg Score)")
    ax.set_title(f"Performance vs Turns — {dataset}")
    ax.grid(True, alpha=0.3)
    out = fig_dir / f"fig5_performance_vs_turns_{dataset}.png"
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out.name


def _plot_error_pie(models_data: dict, dataset: str, fig_dir: Path) -> str | None:
    if not HAS_MPL:
        return None
    merged: Counter[str] = Counter()
    for data in models_data.values():
        dist = (data.get(dataset) or {}).get("error_distribution") or {}
        merged.update(dist)
    if not merged:
        return None
    fig, ax = plt.subplots(figsize=(7, 7))
    labels, sizes = zip(*merged.most_common())
    ax.pie(sizes, labels=labels, autopct="%1.1f%%", startangle=140)
    ax.set_title(f"Fig 9 style: Error Distribution — {dataset}")
    out = fig_dir / f"fig9_error_distribution_{dataset}.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out.name


def _plot_stability(models_data: dict, dataset: str, fig_dir: Path) -> str | None:
    if not HAS_MPL:
        return None
    runs = list(range(2, min(21, 12)))
    fig, ax = plt.subplots(figsize=(8, 5))
    for alias, data in models_data.items():
        vals = (data.get(dataset) or {}).get("task_success_values") or []
        if len(vals) < 3:
            continue
        mses = _bootstrap_mse(vals, runs)
        ax.plot(runs, mses, marker="o", label=alias)
    ax.set_xlabel("Bootstrap sample size k (Fig 7 style)")
    ax.set_ylabel("MSE of success-rate estimate (×1000)")
    ax.set_title(f"Metric stability — {dataset}")
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.3)
    out = fig_dir / f"fig7_stability_{dataset}.png"
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out.name


def _plot_overview_bar(models_data: dict, fig_dir: Path) -> str | None:
    if not HAS_MPL:
        return None
    aliases = list(models_data.keys())
    st = [(models_data[a].get("singleturn") or {}).get("task_success_rate_pct") or 0 for a in aliases]
    mt = [(models_data[a].get("multiturn") or {}).get("task_success_rate_pct") or 0 for a in aliases]
    x = range(len(aliases))
    w = 0.35
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar([i - w / 2 for i in x], st, w, label="Single-turn Pass@1")
    ax.bar([i + w / 2 for i in x], mt, w, label="Multi-turn Pass@1")
    ax.set_xticks(list(x))
    ax.set_xticklabels(aliases, rotation=20, ha="right", fontsize=8)
    ax.set_ylabel("Task Success Rate (%)")
    ax.set_title("6 Models Overview")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    out = fig_dir / "overview_task_success.png"
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out.name


def _plot_token_cost(models_data: dict, fig_dir: Path) -> str | None:
    if not HAS_MPL:
        return None
    aliases = list(models_data.keys())
    tokens = []
    for a in aliases:
        st = (models_data[a].get("singleturn") or {}).get("token_usage") or {}
        mt = (models_data[a].get("multiturn") or {}).get("token_usage") or {}
        tokens.append((st.get("total_tokens") or 0) + (mt.get("total_tokens") or 0))
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(aliases, tokens, color="#95a5a6")
    ax.set_title("Total Tokens (singleturn + multiturn run)")
    ax.set_ylabel("Tokens")
    out = fig_dir / "token_cost_total.png"
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out.name


def _html_table3(models_data: dict, dataset: str) -> str:
    rows = []
    for alias, data in models_data.items():
        dom = (data.get(dataset) or {}).get("by_difficulty") or {}
        cross = (data.get(dataset) or {})
        rows.append(
            f"<tr><td>{data.get('label', alias)}</td>"
            f"<td>{cross.get('avg_score', '-')}</td>"
            f"<td>{cross.get('task_success_rate_pct', '-')}</td>"
            + "".join(
                f"<td>{dom.get(d, {}).get('task_success_rate', '-')}</td>" for d in ("easy", "medium", "hard")
            )
            + "</tr>"
        )
    return (
        f"<h3>Table 3 风格 — {dataset}</h3>"
        "<table border='1' cellpadding='6' style='border-collapse:collapse;font-size:13px'>"
        "<tr><th>Model</th><th>Avg@1</th><th>Pass@1</th><th>Easy</th><th>Medium</th><th>Hard</th></tr>"
        + "".join(rows)
        + "</table>"
    )


def generate_report(run_dir: Path, cfg: dict) -> dict[str, Any]:
    fig_dir = run_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    models_data = collect_run_data(run_dir, cfg)

    figures: list[str] = []
    for fn in (
        lambda: _plot_overview_bar(models_data, fig_dir),
        lambda: _plot_token_cost(models_data, fig_dir),
    ):
        name = fn()
        if name:
            figures.append(name)

    for ds in ("singleturn", "multiturn"):
        for plot_fn in (
            lambda d=ds: _plot_table3(models_data, d, fig_dir),
            lambda d=ds: _plot_performance_vs_turns(models_data, d, fig_dir),
            lambda d=ds: _plot_error_pie(models_data, d, fig_dir),
            lambda d=ds: _plot_stability(models_data, d, fig_dir),
        ):
            name = plot_fn()
            if name:
                figures.append(name)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(run_dir),
        "models": models_data,
        "figures": figures,
        "has_matplotlib": HAS_MPL,
    }
    (run_dir / "report_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    html_parts = [
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>",
        f"<title>{cfg.get('report', {}).get('title', '模型选型报告')}</title>",
        "<style>body{font-family:sans-serif;max-width:960px;margin:24px auto;padding:0 16px}"
        "table{margin:12px 0}img{max-width:100%;margin:12px 0}</style></head><body>",
        f"<h1>{cfg.get('report', {}).get('title', '模型选型报告')}</h1>",
        f"<p>Run: <code>{run_dir.name}</code> · 生成时间 UTC {summary['generated_at'][:19]}</p>",
        "<h2>1. 总览（对标 VitaBench Table 3）</h2>",
        _html_table3(models_data, "singleturn"),
        _html_table3(models_data, "multiturn"),
        "<h2>2. 图表（对标论文 Fig 5/7/9）</h2>",
        "<ul><li>Fig 5：Performance vs Turns</li><li>Fig 7：子集规模 vs 指标 MSE</li>"
        "<li>Fig 9：失败类型分布</li></ul>",
    ]
    for fig in figures:
        html_parts.append(f"<figure><img src='figures/{fig}' alt='{fig}'/><figcaption>{fig}</figcaption></figure>")
    html_parts.append("</body></html>")
    (run_dir / "report.html").write_text("\n".join(html_parts), encoding="utf-8")

    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--config", type=Path, default=_MODEL_SEL / "config.json")
    args = ap.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    run_dir = _MODEL_SEL / "results" / args.run_id
    if not run_dir.is_dir():
        print(f"missing {run_dir}", file=sys.stderr)
        return 1
    summary = generate_report(run_dir, cfg)
    print(json.dumps({"report_html": str(run_dir / "report.html"), "figures": len(summary["figures"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main())
