#!/usr/bin/env python3
"""跑全量前自检：考卷、配置、ECS、代理、脚本依赖。"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

_BENCH = Path(__file__).resolve().parents[1]
_MODEL_SEL = Path(__file__).resolve().parent
_ENV = _BENCH.parent.parent / ".env"


def _load_cases(rel: str) -> list[dict]:
    p = _BENCH / rel
    return json.loads(p.read_text(encoding="utf-8"))


def _check_difficulty(cases: list[dict], expected: dict) -> list[str]:
    issues = []
    cnt = Counter(c.get("difficulty") for c in cases)
    total = len(cases)
    for k, ratio in expected.items():
        want = int(total * ratio)
        have = cnt.get(k, 0)
        if have != want:
            issues.append(f"difficulty {k}: want {want}, have {have}")
    return issues


def _get_env(key: str) -> str:
    if not _ENV.is_file():
        return ""
    m = re.search(rf"^{re.escape(key)}=(.*)$", _ENV.read_text(encoding="utf-8"), re.M)
    return m.group(1).strip() if m else ""


def run_self_check(cfg: dict) -> dict:
    issues: list[str] = []
    checks: dict = {}

    # 1) 考卷文件与比例
    for name, ds in cfg["datasets"].items():
        rel = ds["path"]
        p = _BENCH / rel
        if not p.is_file():
            issues.append(f"missing dataset: {rel}")
            continue
        cases = _load_cases(rel)
        checks[f"{name}_count"] = len(cases)
        if len(cases) != ds.get("cases", 50):
            issues.append(f"{name}: expected {ds.get('cases')} cases, got {len(cases)}")
        issues.extend(_check_difficulty(cases, ds["difficulty_ratio"]))

    # 1b) 隐藏卷（不参与 50 条选型，全量后防刷题）
    hold = cfg.get("hidden_holdout") or {}
    hold_rel = hold.get("path", "")
    if hold_rel:
        hold_path = _BENCH / hold_rel
        if not hold_path.is_file():
            issues.append(f"missing hidden holdout: {hold_rel}")
        else:
            hold_cases = _load_cases(hold_rel)
            checks["hidden_holdout_count"] = len(hold_cases)
            if len(hold_cases) != hold.get("cases", 15):
                issues.append(f"hidden holdout: expected {hold.get('cases')} cases, got {len(hold_cases)}")

    # 1c) 多轮考卷不得含裁判字段（防答案泄露）
    mt_rel = cfg["datasets"]["multiturn"]["path"]
    mt_cases = _load_cases(mt_rel)
    leaked = sum(1 for c in mt_cases if c.get("expected_behavior") or c.get("must_not"))
    checks["multiturn_leaked_judge_fields"] = leaked
    if leaked:
        issues.append(f"multiturn cases must not contain judge fields in model input: {leaked} cases")

    # 2) 多轮裁判标注
    judge_rel = cfg["datasets"]["multiturn"].get("local_judge_path") or cfg["datasets"]["multiturn"].get("judge_path", "")
    judge_path = _BENCH / judge_rel if judge_rel else _MODEL_SEL / "judge" / "multiturn_judge.json"
    if not judge_path.is_file():
        issues.append(f"missing judge annotations: {judge_rel} (run enrich_judge_annotations.py)")
    else:
        judges = json.loads(judge_path.read_text(encoding="utf-8"))
        checks["judge_count"] = len(judges)

    # 3) .env keys
    required_keys = [
        "ARK_API_KEY",
        "ARK_MODEL_NAME",
        "OPENROUTER_API_KEY",
        "deepseek_model",
        "openrouter_model2",
        "openrouter_model3",
        "openrouter_model4",
        "qwen_model",
        "qwen_api_key",
    ]
    for k in required_keys:
        if not _get_env(k):
            issues.append(f".env missing {k}")

    proxy = _get_env("OVERSEAS_PROXY_HTTPS")
    if not proxy and not (_get_env("WEBSHARE_PROXY_USERNAME") and _get_env("WEBSHARE_PROXY_PASSWORD")):
        issues.append("overseas proxy not configured (OVERSEAS_PROXY_HTTPS or WEBSHARE credentials)")

    # 4) ECS SSH
    host = cfg["ecs"]["host"]
    try:
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, "which openclaw"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        checks["ecs_openclaw"] = proc.stdout.strip() if proc.returncode == 0 else None
        if proc.returncode != 0:
            issues.append(f"ECS unreachable or openclaw missing: {host}")
    except Exception as e:
        issues.append(f"ECS ssh failed: {e}")

    # 5) 本地脚本
    for script in ["collect_openclaw_pred.py", "run_agent_eval.py", "rubric.json"]:
        if not (_BENCH / script).is_file():
            issues.append(f"missing bench script: {script}")

    switch_script = _BENCH.parent / "gateway-chat-ui" / "scripts" / "run_ecs_switch_model_from_local_env.py"
    checks["switch_script"] = str(switch_script)
    if not switch_script.is_file():
        issues.append("missing run_ecs_switch_model_from_local_env.py")

    # 6) import smoke
    try:
        sys.path.insert(0, str(_MODEL_SEL))
        import multiturn_metrics  # noqa: F401
        checks["multiturn_metrics_import"] = True
    except Exception as e:
        issues.append(f"multiturn_metrics import failed: {e}")

    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "checks": checks,
        "config_version": cfg.get("version"),
    }


if __name__ == "__main__":
    cfg = json.loads((_MODEL_SEL / "config.json").read_text(encoding="utf-8"))
    report = run_self_check(cfg)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["ok"] else 1)
