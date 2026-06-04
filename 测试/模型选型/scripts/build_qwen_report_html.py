#!/usr/bin/env python3
"""Build human-readable HTML report for qwen 6.3 eval."""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATS = ROOT / "results" / "v63-batch" / "qwen" / "report_stats.json"
OUT = ROOT / "results" / "v63-batch" / "qwen" / "qwen_6.3_测评报告.html"


def pct(n: float) -> str:
    return f"{n * 100:.1f}%"


def term_label(t: str) -> str:
    return {
        "user_stop": "用户满意结束",
        "agent_stop": "助手主动结束",
        "agent_error": "助手异常（未评分）",
        "max_steps": "达到轮次上限",
        "too_many_errors": "工具错误过多",
    }.get(t, t)


def fr_reason_label(r: str | None) -> str:
    if not r:
        return "—"
    if r == "progress_no_timing":
        return "首轮有回复，未采集首字耗时"
    if r.startswith("ttft_ms="):
        ms = int(r.split("=")[1])
        return f"首字耗时 {ms/1000:.1f} 秒"
    if r == "no_visible_progress":
        return "首轮无可见进展"
    return r


def main() -> None:
    data = json.loads(STATS.read_text(encoding="utf-8"))
    rows = [r for r in data["rows"] if not r.get("missing")]
    tasks_meta = {t["id"]: t for t in data["tasks"]}

    judged = [r for r in rows if r.get("rubric_total")]
    user_stop = [r for r in rows if r.get("termination") == "user_stop"]
    agent_err = [r for r in rows if r.get("termination") == "agent_error"]
    timeout_err = [r for r in agent_err if r.get("agent_error_kind") == "timeout"]
    empty_msg_err = [r for r in agent_err if r.get("agent_error_kind") == "empty_message"]

    rewards_judged = [r["reward"] for r in judged]
    rewards_all = [r["reward"] for r in rows]
    avg_judged = statistics.mean(rewards_judged) if rewards_judged else 0
    avg_all = statistics.mean(rewards_all) if rewards_all else 0
    full_pass = sum(1 for r in rows if (r.get("reward") or 0) >= 1.0)
    partial_80 = sum(1 for r in rows if (r.get("reward") or 0) >= 0.8)
    fr_scores = [r["first_response_score"] for r in rows if r.get("first_response_score") is not None]
    fr_avg = statistics.mean(fr_scores) if fr_scores else 0
    fr_pass70 = sum(1 for s in fr_scores if s >= 70)
    ttft_vals = [r["ttft_ms"] for r in rows if r.get("ttft_ms")]

    by_diff = defaultdict(list)
    for r in judged:
        d = r.get("difficulty") or tasks_meta[r["id"]].get("difficulty", "?")
        by_diff[d].append(r["reward"])

    term_counts = defaultdict(int)
    for r in rows:
        term_counts[r.get("termination") or "unknown"] += 1

    reward_bins = {"满分 100%": 0, "75%–99%": 0, "50%–74%": 0, "25%–49%": 0, "0%（含未评分）": 0}
    for r in rows:
        v = r.get("reward") or 0
        if not r.get("rubric_total"):
            reward_bins["0%（含未评分）"] += 1
        elif v >= 1.0:
            reward_bins["满分 100%"] += 1
        elif v >= 0.75:
            reward_bins["75%–99%"] += 1
        elif v >= 0.5:
            reward_bins["50%–74%"] += 1
        elif v >= 0.25:
            reward_bins["25%–49%"] += 1
        else:
            reward_bins["0%（含未评分）"] += 1

    fr_bins = defaultdict(int)
    for r in rows:
        s = r.get("first_response_score")
        if s is not None:
            fr_bins[str(int(s))] += 1

    fail_rows_html = ""
    for r in sorted(agent_err, key=lambda x: x["id"]):
        kind = "轮次超时" if r.get("agent_error_kind") == "timeout" else (
            "桥接空消息" if r.get("agent_error_kind") == "empty_message" else "其他"
        )
        fail_rows_html += (
            f"<tr><td>{r['id']}</td><td>{tasks_meta[r['id']].get('scenario','')}</td>"
            f"<td>{r.get('steps','—')}</td><td>{kind}</td>"
            f"<td>{r.get('agent_error','—')}</td></tr>"
        )

    table_rows = ""
    for r in sorted(rows, key=lambda x: (-(x.get("reward") or 0), x["id"])):
        meta = tasks_meta.get(r["id"], {})
        rm, rt = r.get("rubric_met"), r.get("rubric_total")
        rubric_txt = f"{rm}/{rt}" if rm is not None and rt else "未评分"
        reward_txt = f"{(r.get('reward') or 0)*100:.0f}%" if rt else "0%（助手异常）"
        fr_s = r.get("first_response_score")
        fr_txt = f"{fr_s} 分" if fr_s is not None else "—"
        ttft = r.get("ttft_ms")
        ttft_txt = f"{ttft/1000:.1f}s" if ttft else "未采集"
        table_rows += (
            f"<tr><td>{meta.get('city','')}</td><td>{meta.get('scenario','')}</td>"
            f"<td>{meta.get('difficulty','')}</td><td>{term_label(r.get('termination',''))}</td>"
            f"<td>{r.get('steps','—')}</td><td>{reward_txt}</td><td>{rubric_txt}</td>"
            f"<td>{fr_txt}</td><td>{fr_reason_label(r.get('first_response_reason'))}</td>"
            f"<td>{ttft_txt}</td></tr>"
        )

    diff_labels = json.dumps(list(by_diff.keys()), ensure_ascii=False)
    diff_vals = json.dumps([round(statistics.mean(v) * 100, 1) for v in by_diff.values()])
    term_labels = json.dumps([term_label(k) for k in term_counts], ensure_ascii=False)
    term_vals = json.dumps(list(term_counts.values()))
    bin_labels = json.dumps(list(reward_bins.keys()), ensure_ascii=False)
    bin_vals = json.dumps(list(reward_bins.values()))
    fr_bin_labels = json.dumps(sorted(fr_bins.keys(), key=int), ensure_ascii=False)
    fr_bin_vals = json.dumps([fr_bins[k] for k in sorted(fr_bins.keys(), key=int)])

    timeout_ids = "、".join(r["id"].replace("T063_", "") for r in timeout_err) or "—"
    empty_ids = "、".join(
        r["id"].replace("T063_", "").replace("T063_SAMPLE_001", "样例001") for r in empty_msg_err
    ) or "—"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Qwen3.6-Plus · 6.3 本地生活测评报告</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    :root {{
      --bg: #f6f8fb; --card: #fff; --text: #1a2332; --muted: #5c6b7a;
      --accent: #1677ff; --border: #e8ecf1; --warn: #fff7e6; --warn-b: #ffd591;
    }}
    body {{ margin: 0; font-family: "PingFang SC","Microsoft YaHei",sans-serif;
      background: var(--bg); color: var(--text); line-height: 1.8; font-size: 15px; }}
    .wrap {{ max-width: 1140px; margin: 0 auto; padding: 32px 20px 64px; }}
    h1 {{ font-size: 1.75rem; margin: 0 0 8px; font-weight: 600; }}
    .subtitle {{ color: var(--muted); margin-bottom: 28px; line-height: 1.6; }}
    section {{ background: var(--card); border-radius: 12px; padding: 24px 28px;
      margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,.06); border: 1px solid var(--border); }}
    h2 {{ font-size: 1.15rem; margin: 0 0 14px; color: var(--accent); font-weight: 600; }}
    h3 {{ font-size: 1rem; margin: 18px 0 10px; color: var(--text); }}
    p {{ margin: 0 0 14px; }}
  p:last-child {{ margin-bottom: 0; }}
    .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 12px; margin: 18px 0; }}
    .kpi {{ background: #f0f5ff; border-radius: 10px; padding: 14px; text-align: center; }}
    .kpi strong {{ display: block; font-size: 1.45rem; color: var(--accent); }}
    .kpi span {{ font-size: 0.82rem; color: var(--muted); line-height: 1.4; }}
    .charts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; margin-top: 16px; }}
    .chart-box {{ position: relative; height: 260px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; margin-top: 10px; }}
    th, td {{ border: 1px solid var(--border); padding: 8px 10px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f5ff; font-weight: 600; }}
    tr:nth-child(even) {{ background: #fafbfc; }}
    .callout {{ background: var(--warn); border: 1px solid var(--warn-b); border-radius: 8px; padding: 14px 16px; margin: 14px 0; }}
    .flow {{ background: #fafbfc; border-radius: 8px; padding: 16px 20px; margin: 12px 0;
      font-size: 0.92rem; line-height: 2; }}
    ol.metrics {{ margin: 8px 0 0 1.2em; padding: 0; }}
    ol.metrics li {{ margin-bottom: 8px; }}
  </style>
</head>
<body>
<div class="wrap">
  <h1>Qwen3.6-Plus · 6.3 本地生活 Agent 测评报告</h1>
  <p class="subtitle">模型：通义 Qwen3.6-Plus（思考深度 medium，温度 0）｜任务集：50 条本地出行+餐饮场景｜方案版本：6.3｜报告生成：{datetime.now().strftime("%Y-%m-%d %H:%M")}</p>

  <section>
    <h2>一、测评在做什么（6.3 流程）</h2>
    <p>本次测评的目标是：在统一的仿真环境与任务集上，比较哪一个大模型更适合作为「本地生活出行规划 Agent」的大脑。整体思路沿用 VitaBench 式「环境 + 用户 + 助手 + 裁判」四段式，而不是让脚本代替用户发固定话术。</p>
    <p>每条任务预先写好四块内容：仿真环境（住址、历史订单、城市与时间）、用户画像、隐藏任务指令（仅用户模拟器可见）、以及检查清单（仅裁判可见）。正式开跑后，由调度器循环推进：用户模拟器根据画像和指令生成首轮及后续用户发言；助手通过 OpenClaw 网关调用天气、高德 POI、路线等工具并回复；若用户判定需求已满足则结束，否则继续对话。对话结束后，裁判模型按「滑动窗口」阅读整段轨迹（默认每窗 10 轮、重叠 2 轮），逐条更新检查项是否满足，并汇总为得分率。</p>
    <div class="flow">用户模拟器（DeepSeek）→ 助手（Qwen 网关 + MCP 工具）→ 用户 … → 结束 → 滑动窗口裁判（GPT-5.5）→ 得分率 + 首响分</div>
    <p>与旧版 6.2 脚本打分不同：6.3 的主分由裁判根据任务附带的检查清单判定，更贴近「方案是否真正满足约束」；用户模拟器与裁判走 OpenRouter 海外线路，助手走 ECS 上的 Qwen 网关，三路相互独立。</p>
  </section>

  <section>
    <h2>二、测评指标怎么读（6.3 北极星）</h2>
    <p>答辩与选型时建议同时看「做对多少」和「首响快不快」，二者分开计算、不互相替代。</p>
    <ol class="metrics">
      <li><strong>检查项得分率（主指标）</strong>：满足的检查条数 ÷ 该题总条数。例如 8 条里满足 6 条则为 75%。全部满足为 100%，是「满分题」。</li>
      <li><strong>满分率（Full Success）</strong>：50 题里得分率为 100% 的题数占比，表示「整题做对」的比例。另有辅线：得分率 ≥ 80% 的题数（部分成功），用于看「大体可用」有多少。</li>
      <li><strong>首响时效分（first_response，北极星之二）</strong>：只看助手<strong>第一轮</strong>响应速度体验。若采集到首字耗时：≤10 秒 100 分，≤15 秒 70 分，≤25 秒 40 分，更慢 10 分；若未采集耗时但首轮有可见文字或工具进度，记 75 分；首轮无进展记 40 分。达标线常用 70 分（对应 15 秒内或有等价进展）。</li>
      <li><strong>对话轮次、结束方式</strong>：轮次反映交互深度；结束方式为「用户满意结束」最理想。助手异常、超步数、工具错误过多时，检查项得分率直接记 0，且通常不做裁判打分。</li>
    </ol>
    <p>本次跑数中，网关未回传首字耗时字段，故 50 题首响分均为 75 分（「首轮有回复，未采集首字耗时」）。若后续网关补齐计时，首响分布会更有区分度。</p>
  </section>

  <section>
    <h2>三、Qwen 跑数结果概览</h2>
    <p>50 条任务均已落盘，具备对话轨迹与结束原因。其中 41 条走完「用户满意结束 + 裁判打分」，9 条在助手侧异常退出，检查项得分率记 0 且未调用裁判。另有一批曾在批量过程中因 OpenRouter 欠费或代理抖动失败，已重跑或并入成功试跑结果（如第 33 题），不计入下列 9 条助手异常。</p>
    <div class="kpis">
      <div class="kpi"><strong>50/50</strong><span>题目均有记录</span></div>
      <div class="kpi"><strong>{len(judged)}</strong><span>完成裁判打分</span></div>
      <div class="kpi"><strong>{pct(avg_judged)}</strong><span>已评分题平均得分率</span></div>
      <div class="kpi"><strong>{pct(avg_all)}</strong><span>全 50 题平均（含 0 分）</span></div>
      <div class="kpi"><strong>{full_pass}</strong><span>满分题数（100%）</span></div>
      <div class="kpi"><strong>{partial_80}</strong><span>得分率 ≥80%</span></div>
      <div class="kpi"><strong>{fr_avg:.0f}</strong><span>首响均分（0–100）</span></div>
      <div class="kpi"><strong>{fr_pass70}/{len(fr_scores)}</strong><span>首响 ≥70 分</span></div>
      <div class="kpi"><strong>{len(user_stop)}</strong><span>用户满意结束</span></div>
      <div class="kpi"><strong>{len(agent_err)}</strong><span>助手异常未评分</span></div>
    </div>
    <div class="charts">
      <div class="chart-box"><canvas id="chartTerm"></canvas></div>
      <div class="chart-box"><canvas id="chartReward"></canvas></div>
      <div class="chart-box"><canvas id="chartDiff"></canvas></div>
      <div class="chart-box"><canvas id="chartFr"></canvas></div>
    </div>
  </section>

  <section>
    <h2>四、失败原因说明（勿与「网络重跑」混淆）</h2>
    <p>曾有多题因<strong>海外裁判/用户模拟</strong>线路（OpenRouter 欠费、IPRoyal 代理）在对话结束后打分失败，与助手网关无关；该批已通过重跑或并入试跑结果修复，例如 12、23、25、26、27、28 等已正常得分，33 已并入正式集。</p>
    <p>下列 9 题属于<strong>助手 / OpenClaw 桥接</strong>问题，重跑 OpenRouter 无法解决；表现为对话中途助手异常退出，检查项得分率为 0。</p>
    <div class="callout">
      <p><strong>3 题 — 助手单轮等待超时</strong>（020、041、043）：在约 7 分钟时限内网关未返回，记为超时，多发生在首轮或前几轮。</p>
      <p><strong>6 题 — 桥接传入空消息</strong>（样例 001、009、017、022、024、044）：OpenClaw 命令行报错「消息不能为空」，多为评测程序向网关提交的用户内容为空，属于对接问题，不是海外代理故障。其中 044 曾先遇裁判网络失败，重跑后变为该类桥接错误。</p>
    </div>
    <table>
      <thead><tr><th>题号</th><th>场景</th><th>轮次</th><th>归类</th><th>原始报错摘要</th></tr></thead>
      <tbody>{fail_rows_html}</tbody>
    </table>
  </section>

  <section>
    <h2>五、分任务明细</h2>
    <p>下表按检查项得分率从高到低排列。列含义：结束方式；对话轮次；检查项得分率及通过条数；首响分及说明；首字耗时（若网关提供）。</p>
    <table>
      <thead>
        <tr>
          <th>城市</th><th>场景</th><th>难度</th><th>结束方式</th><th>轮次</th>
          <th>得分率</th><th>检查项</th><th>首响分</th><th>首响说明</th><th>首字耗时</th>
        </tr>
      </thead>
      <tbody>{table_rows}</tbody>
    </table>
    <p style="margin-top:14px;font-size:0.88rem;color:var(--muted)">数据目录：测试/模型选型/results/v63-batch/qwen/ · 方案说明：待修复/模型选型评测/6.3方案/</p>
  </section>
</div>
<script>
const font = {{ family: "'PingFang SC','Microsoft YaHei',sans-serif" }};
new Chart(document.getElementById('chartTerm'), {{
  type: 'doughnut',
  data: {{ labels: {term_labels}, datasets: [{{ data: {term_vals}, backgroundColor: ['#1677ff','#69b1ff','#ff7875'] }}] }},
  options: {{ plugins: {{ title: {{ display: true, text: '对话结束方式', font }}, legend: {{ position: 'bottom' }} }}, responsive: true, maintainAspectRatio: false }}
}});
new Chart(document.getElementById('chartReward'), {{
  type: 'bar',
  data: {{ labels: {bin_labels}, datasets: [{{ label: '题数', data: {bin_vals}, backgroundColor: '#1677ff' }}] }},
  options: {{ plugins: {{ title: {{ display: true, text: '检查项得分率分布（50 题）', font }} }}, scales: {{ y: {{ beginAtZero: true }} }}, responsive: true, maintainAspectRatio: false }}
}});
new Chart(document.getElementById('chartDiff'), {{
  type: 'bar',
  data: {{ labels: {diff_labels}, datasets: [{{ label: '平均得分率 %', data: {diff_vals}, backgroundColor: '#52c41a' }}] }},
  options: {{ plugins: {{ title: {{ display: true, text: '分难度平均得分率（已评分）', font }} }}, scales: {{ y: {{ max: 100, beginAtZero: true }} }}, responsive: true, maintainAspectRatio: false }}
}});
new Chart(document.getElementById('chartFr'), {{
  type: 'bar',
  data: {{ labels: {fr_bin_labels}, datasets: [{{ label: '题数', data: {fr_bin_vals}, backgroundColor: '#722ed1' }}] }},
  options: {{ plugins: {{ title: {{ display: true, text: '首响时效分分布', font }} }}, scales: {{ y: {{ beginAtZero: true }} }}, responsive: true, maintainAspectRatio: false }}
}});
</script>
</body>
</html>"""
    OUT.write_text(html, encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
