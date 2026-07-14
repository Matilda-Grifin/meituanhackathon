#!/usr/bin/env bash
# Isolated pre-harness(post_output-off) Seed eval — MUST NOT touch 8081 / online stack.
#
# Guarantees:
# - Never edits /root/.openclaw/openclaw.json (MCP stays production run_mcp.py)
# - Never ecs_apply / never restarts gateway / never nginx
# - Never overwrites /root/meituan-lifecare-agent/{run_mcp.py,lifecare,workspace,gateway-chat-ui}
# - Writes only under /root/eval-seed-preharnes and results/.../seed-lite-v63-preharnes
# - Reuses production .env (read-only) so user/judge LLMs match yesterday Seed batch
#
# Caveat: production MCP pre_tool Harness remains (changing MCP would affect 8081).
# This run only disables vitabench post_output repair/POI whitelist on the eval trajectory.
set -euo pipefail

KEY="${SSH_KEY:-/Users/pdsg01lt2110001/Desktop/hackathon/meituanhackathon/新密钥.pem}"
HOST="${ECS_HOST:-root@121.41.81.58}"
SSH=(ssh -i "$KEY" -o BatchMode=yes -o IdentitiesOnly=yes)
SCP=(scp -i "$KEY" -o BatchMode=yes -o IdentitiesOnly=yes)

EVAL_ROOT=/root/eval-seed-preharnes
PROD_REPO=/root/meituan-lifecare-agent
PROD_BENCH="$PROD_REPO/benchmark"
OUT_ALIAS=seed-lite-v63-preharnes
OUT_DIR="$PROD_BENCH/model_selection/results/v63-batch/$OUT_ALIAS"
TASK_IDS="${TASK_IDS:-T063_002,T063_005,T063_010,T063_SAMPLE_001,T063_015,T063_020,T063_030,T063_035,T063_045,T063_050}"

assert_no_online_damage() {
  "${SSH[@]}" "$HOST" bash -s <<'REMOTE'
set -euo pipefail
mkdir -p /root/eval-seed-preharnes
python3 - <<'PY'
from pathlib import Path
import hashlib, json
paths = [
  Path("/root/.openclaw/openclaw.json"),
  Path("/root/meituan-lifecare-agent/run_mcp.py"),
  Path("/root/.openclaw/workspace/SOUL.md"),
]
out = {}
for p in paths:
    out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
Path("/root/eval-seed-preharnes/ONLINE_FINGERPRINT_BEFORE.json").write_text(
    json.dumps(out, indent=2) + "\n", encoding="utf-8"
)
print("fingerprint_saved", len(out))
PY
curl -sk --max-time 8 -o /dev/null -w "8081:%{http_code}\n" https://127.0.0.1:8081/ || true
ss -lntp | grep -E ':8081|:18789' || true
REMOTE
}

deploy_isolated() {
  "${SSH[@]}" "$HOST" bash -s <<REMOTE
set -euo pipefail
mkdir -p "$EVAL_ROOT/benchmark"
rm -rf "$EVAL_ROOT/benchmark/vitabench_eval"
cp -a "$PROD_BENCH/vitabench_eval" "$EVAL_ROOT/benchmark/vitabench_eval"
python3 - <<PY
from pathlib import Path
p = Path("$EVAL_ROOT/benchmark/vitabench_eval/harness_bridge.py")
t = p.read_text(encoding="utf-8")
if "LIFECARE_DISABLE_POST_OUTPUT" not in t:
    old = '''def apply_harness_post_output(session_key: str, assistant_text: str) -> dict[str, Any]:
    """
    Mirror POST /api/harness/validate-and-repair after assistant output.
    Returns repaired text for trajectory / user simulator (user-visible final).
    """
    sk = (session_key or "").strip()
'''
    new = '''def apply_harness_post_output(session_key: str, assistant_text: str) -> dict[str, Any]:
    """
    Mirror POST /api/harness/validate-and-repair after assistant output.
    Returns repaired text for trajectory / user simulator (user-visible final).
    """
    import os
    if os.environ.get("LIFECARE_DISABLE_POST_OUTPUT", "").strip().lower() in ("1", "true", "yes", "on"):
        text = assistant_text or ""
        return {
            "text": text,
            "skipped": True,
            "disabled": True,
            "repairs_applied": [],
            "checklist_missing": [],
            "poi_audit": {},
            "violations": [],
        }
    sk = (session_key or "").strip()
'''
    if old not in t:
        raise SystemExit("harness_bridge pattern not found; abort")
    p.write_text(t.replace(old, new, 1), encoding="utf-8")
    print("patched", p)
else:
    print("already patched", p)
PY
cat > "$EVAL_ROOT/run_preharnes_batch.py" <<'PY'
#!/usr/bin/env python3
"""Run seed pre-harness(post_output off) batch without touching online MCP/openclaw."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROD_REPO = Path("/root/meituan-lifecare-agent")
PROD_BENCH = PROD_REPO / "benchmark"
EVAL_ROOT = Path("/root/eval-seed-preharnes")
EVAL_BENCH = EVAL_ROOT / "benchmark"
FORBIDDEN = [
    PROD_REPO / "run_mcp.py",
    Path("/root/.openclaw/openclaw.json"),
    Path("/root/.openclaw/workspace/SOUL.md"),
]


def _fingerprint() -> dict[str, str | None]:
    import hashlib

    out: dict[str, str | None] = {}
    for p in FORBIDDEN:
        out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
    return out


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--model-alias", default="seed-lite-v63-preharnes")
    ap.add_argument("--thinking", default="medium")
    ap.add_argument("--task-ids", required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    before = _fingerprint()
    (EVAL_ROOT / "ONLINE_FINGERPRINT_BATCH_START.json").write_text(
        json.dumps(before, indent=2) + "\n", encoding="utf-8"
    )

    out_dir = PROD_BENCH / "model_selection/results/v63-batch" / args.model_alias
    out_dir.mkdir(parents=True, exist_ok=True)
    # results dir is under prod benchmark tree but only creates NEW alias folder — OK
    task_ids = [x.strip() for x in args.task_ids.split(",") if x.strip()]
    progress_path = out_dir / "batch_progress.json"
    summary_path = out_dir / "batch_summary.json"
    started = datetime.now(timezone.utc).isoformat()
    summary: list[dict] = []

    env = {k: v for k, v in os.environ.items() if isinstance(v, str)}
    # Prefer side vitabench (with disable patch); keep PROD_REPO for lifecare imports if needed
    env["PYTHONPATH"] = f"{EVAL_BENCH}:{PROD_REPO}:{PROD_BENCH}"
    env["V63_TASKS_DIR"] = str(PROD_BENCH / "eval_cases/vitabench/tasks")
    env["LIFECARE_MCP_TOOL_LOG"] = "1"
    env["LIFECARE_MCP_TOOL_LOG_PATH"] = str(PROD_BENCH / "results/mcp_tool_calls_preharnes.jsonl")
    env["V63_EVAL_THINKING"] = args.thinking
    env["V63_AGENT_LOCAL"] = "0"
    env["LIFECARE_DISABLE_POST_OUTPUT"] = "1"
    # Do NOT override user_llm_model / judge_llm_model — same .env as yesterday Seed run

    print(
        f"preharnes batch: {len(task_ids)} tasks -> {out_dir}; "
        f"LIFECARE_DISABLE_POST_OUTPUT=1; MCP untouched",
        flush=True,
    )

    for i, tid in enumerate(task_ids, 1):
        run_file = out_dir / f"{tid}_run.json"
        if run_file.is_file() and not args.force:
            data = json.loads(run_file.read_text(encoding="utf-8"))
            row = {
                "task_id": tid,
                "ok": True,
                "skipped": True,
                "termination": data.get("termination"),
                "reward": (data.get("reward_info") or {}).get("reward"),
            }
            summary.append(row)
            progress_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[{i}/{len(task_ids)}] skip existing {tid}", flush=True)
            continue
        print(f"[{i}/{len(task_ids)}] running {tid}...", flush=True)
        mcp_log = Path(env["LIFECARE_MCP_TOOL_LOG_PATH"])
        mcp_log.parent.mkdir(parents=True, exist_ok=True)
        mcp_log.write_text("", encoding="utf-8")
        cmd = [
            sys.executable,
            str(EVAL_BENCH / "vitabench_eval/run_benchmark.py"),
            "--task-id",
            tid,
            "--agent-timeout-s",
            "420",
            "--out",
            str(run_file),
            "--batch",
            args.model_alias,
            # aliases resolve via same .env as Seed yesterday
            "--user-model",
            "user",
            "--judge-model",
            "judge",
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(EVAL_BENCH),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            row = {
                "task_id": tid,
                "ok": False,
                "error": (proc.stderr or proc.stdout or f"exit {proc.returncode}")[:800],
            }
            print(f"  -> FAIL {row['error'][:200]}", flush=True)
        else:
            data = json.loads(run_file.read_text(encoding="utf-8"))
            # verify models
            tu = data.get("token_usage") or {}
            row = {
                "task_id": tid,
                "ok": True,
                "termination": data.get("termination"),
                "steps": data.get("steps"),
                "reward": (data.get("reward_info") or {}).get("reward"),
                "rubric_met": (data.get("reward_info") or {}).get("rubric_met"),
                "rubric_total": (data.get("reward_info") or {}).get("rubric_total"),
                "user_sim_model": (tu.get("user_sim") or {}).get("model"),
                "judge_model": (tu.get("judge") or {}).get("model"),
                "harness_disabled": True,
            }
            print(
                f"  -> reward={row.get('reward')} user={row.get('user_sim_model')} judge={row.get('judge_model')}",
                flush=True,
            )
        summary.append(row)
        progress_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        after = _fingerprint()
        if after != before:
            raise SystemExit(f"ONLINE FINGERPRINT CHANGED — abort. before={before} after={after}")

    finished = datetime.now(timezone.utc).isoformat()
    summary_path.write_text(
        json.dumps(
            {
                "started_at": started,
                "finished_at": finished,
                "model_alias": args.model_alias,
                "thinking": args.thinking,
                "mode": "post_output_disabled_mcp_untouched",
                "total": len(task_ids),
                "ok_count": sum(1 for r in summary if r.get("ok")),
                "results": summary,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (EVAL_ROOT / "ONLINE_FINGERPRINT_BATCH_END.json").write_text(
        json.dumps(_fingerprint(), indent=2) + "\n", encoding="utf-8"
    )
    print("wrote", summary_path, flush=True)


if __name__ == "__main__":
    main()
PY
chmod +x "$EVAL_ROOT/run_preharnes_batch.py"
echo "deploy_ok"
REMOTE
}

start_batch() {
  assert_no_online_damage
  deploy_isolated
  "${SSH[@]}" "$HOST" bash -s <<REMOTE
set -euo pipefail
OUT="$OUT_DIR"
EVAL_ROOT="$EVAL_ROOT"
OUT_ALIAS="$OUT_ALIAS"
TASK_IDS="$TASK_IDS"
mkdir -p "\$OUT"
LOG="\$OUT/batch.log"
PIDF="\$OUT/batch.pid"
pgrep -af ecs_apply || true
nohup python3 "\$EVAL_ROOT/run_preharnes_batch.py" \\
  --model-alias "\$OUT_ALIAS" \\
  --thinking medium \\
  --task-ids "\$TASK_IDS" \\
  --force \\
  < /dev/null >> "\$LOG" 2>&1 &
echo \$! > "\$PIDF"
sleep 1
echo "pid=\$(cat \$PIDF)"
head -5 "\$LOG" || true
curl -sk --max-time 8 -o /dev/null -w "8081_after_start:%{http_code}\\n" https://127.0.0.1:8081/ || true
REMOTE
}

status() {
  "${SSH[@]}" "$HOST" bash -s <<REMOTE
OUT="$OUT_DIR"
echo "=== pid ==="; cat "\$OUT/batch.pid" 2>/dev/null; ps -p "\$(cat \$OUT/batch.pid 2>/dev/null)" -o pid,etime,cmd 2>/dev/null || echo STOPPED
echo "=== progress ==="; python3 -c "import json,pathlib;p=pathlib.Path('\$OUT/batch_progress.json');
print('n',len(json.loads(p.read_text()))) if p.is_file() else print('none')" 2>/dev/null
echo "=== 8081 ==="; curl -sk --max-time 5 -o /dev/null -w "%{http_code}\\n" https://127.0.0.1:8081/ || echo fail
echo "=== fingerprint diff ==="; python3 - <<'PY'
import json
from pathlib import Path
a={}
b={}
pb=Path("/root/eval-seed-preharnes/ONLINE_FINGERPRINT_BEFORE.json")
pe=Path("/root/eval-seed-preharnes/ONLINE_FINGERPRINT_BATCH_END.json")
ps=Path("/root/eval-seed-preharnes/ONLINE_FINGERPRINT_BATCH_START.json")
if pb.is_file(): a=json.loads(pb.read_text())
if pe.is_file(): b=json.loads(pe.read_text())
elif ps.is_file(): b=json.loads(ps.read_text())
print("changed", {k: (a.get(k), b.get(k)) for k in set(a)|set(b) if a.get(k)!=b.get(k)} or "none")
PY
tail -20 "\$OUT/batch.log" 2>/dev/null || true
REMOTE
}

cmd="${1:-start}"
case "$cmd" in
  start) start_batch ;;
  status) status ;;
  deploy) deploy_isolated ;;
  *) echo "usage: $0 start|status|deploy"; exit 2 ;;
esac
