/* global Chart */
const ONLINE_CATS = {
  text: { label: "Agent 文字", color: "#60a5fa" },
  mcp: { label: "MCP 工具", color: "#34d399" },
};
const EVAL_CATS = {
  text: { label: "Agent", color: "#60a5fa" },
  user_sim: { label: "用户模拟", color: "#f472b6" },
  judge: { label: "裁判", color: "#fbbf24" },
  agent: { label: "Agent", color: "#60a5fa" },
};

const params = new URLSearchParams(location.search);
const token = params.get("token") || localStorage.getItem("usageDashboardToken") || "";
if (params.get("token")) localStorage.setItem("usageDashboardToken", token);

let stats = null;
let currentMode = "online";
let barChart = null;
let pieChart = null;

function apiUrl(path, extra = {}) {
  const u = new URL(path, location.origin);
  u.searchParams.set("mode", currentMode);
  if (token) u.searchParams.set("token", token);
  Object.entries(extra).forEach(([k, v]) => u.searchParams.set(k, v));
  return u.toString();
}

async function fetchStats() {
  const res = await fetch(apiUrl("/api/stats"));
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || res.statusText);
  return res.json();
}

function fmtWan(n) {
  return Number(n).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtCost(n) {
  return Number(n).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 4 });
}

function catMap() {
  return currentMode === "eval" ? EVAL_CATS : ONLINE_CATS;
}

function getPeriodData() {
  const p = document.getElementById("period").value;
  if (p === "weekly") return stats.weekly || [];
  if (p === "monthly") return stats.monthly || [];
  return stats.daily || [];
}

function periodLabel(row) {
  return row.date || row.period;
}

function rowMetric(row, metric) {
  return metric === "cost" ? row.cost ?? 0 : row.tokensWan ?? 0;
}

function renderSummaryCards() {
  const s = stats.summary;
  const el = document.getElementById("summaryCards");
  const modeLabel = currentMode === "eval" ? "6.3 测评" : "线上 Demo";
  el.innerHTML = `
    <div class="card"><div class="label">${modeLabel} · 总 Token</div><div class="value">${fmtWan(s.tokensWan)}<span class="unit"> 万</span></div></div>
    <div class="card"><div class="label">估算费用</div><div class="value">¥${fmtCost(s.cost)}</div></div>
    <div class="card"><div class="label">Agent 轮次</div><div class="value">${s.textRuns ?? 0}</div></div>
    <div class="card"><div class="label">${currentMode === "eval" ? "测评任务" : "MCP 调用"}</div><div class="value">${currentMode === "eval" ? (stats.evalOnly?.byTask?.length ?? "—") : (s.mcpCalls ?? 0)}</div></div>
  `;
}

function renderUsageCostTable() {
  const rows = getPeriodData();
  const period = document.getElementById("period").value;
  const isDaily = period === "daily";
  const periodName = isDaily ? "日期" : period === "weekly" ? "周" : "月";
  const cats = catMap();
  const keys = Object.keys(cats);
  const thead = document.querySelector("#usageCostTable thead");
  const tbody = document.querySelector("#usageCostTable tbody");

  document.getElementById("usageCostTitle").textContent = `${currentMode === "eval" ? "测试" : "线上"} · ${isDaily ? "每日" : period === "weekly" ? "每周" : "每月"}用量与费用`;

  let head = `<tr><th rowspan="2">${periodName}</th>`;
  keys.forEach((k) => {
    head += `<th colspan="2">${cats[k].label}</th>`;
  });
  head += `<th rowspan="2">合计(元)</th></tr><tr>`;
  keys.forEach(() => {
    head += `<th>用量</th><th class="group-cost">元</th>`;
  });
  head += `</tr>`;
  thead.innerHTML = head;

  tbody.innerHTML = rows
    .map((row) => {
      const c = row.categories || {};
      let cells = `<td>${periodLabel(row)}</td>`;
      keys.forEach((k) => {
        const x = c[k] || {};
        const usage =
          k === "mcp"
            ? `${x.calls ?? 0} 次`
            : `${fmtWan(x.tokensWan || 0)} 万`;
        cells += `<td>${usage}</td><td class="cost">¥${fmtCost(x.cost || 0)}</td>`;
      });
      cells += `<td class="cost cost-total">¥${fmtCost(row.cost ?? 0)}</td>`;
      return `<tr>${cells}</tr>`;
    })
    .join("");
}

function renderModelTable() {
  const tbody = document.querySelector("#modelTable tbody");
  const models = stats.byModel || {};
  const rows = Object.entries(models);
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="7">暂无文字模型用量</td></tr>`;
    return;
  }
  tbody.innerHTML = rows
    .map(([id, m]) => {
      const label = m.label && m.label !== id ? m.label : id;
      return `<tr>
        <td>${label}</td>
        <td>${m.provider || "—"}</td>
        <td>${fmtWan(m.tokensWan || 0)}</td>
        <td>${(m.input || 0).toLocaleString("zh-CN")}</td>
        <td>${(m.output || 0).toLocaleString("zh-CN")}</td>
        <td>${m.runs ?? 0}</td>
        <td>${fmtCost(m.cost || 0)}</td>
      </tr>`;
    })
    .join("");
}

function renderMcpTable() {
  const panel = document.getElementById("mcpPanel");
  panel.hidden = currentMode === "eval";
  const tbody = document.querySelector("#mcpTable tbody");
  const tools = stats.byMcpTool || {};
  const rows = Object.entries(tools);
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="3">暂无 MCP 调用记录</td></tr>`;
    return;
  }
  tbody.innerHTML = rows
    .map(([id, m]) => `<tr><td>${m.label || id}</td><td>${m.calls ?? 0}</td><td class="cost">¥${fmtCost(m.cost || 0)}</td></tr>`)
    .join("");
}

function renderRoleTable() {
  const panel = document.getElementById("rolePanel");
  const evalPanel = document.getElementById("evalBatchPanel");
  panel.hidden = currentMode !== "eval";
  evalPanel.hidden = currentMode !== "eval";
  if (currentMode !== "eval") return;

  const byRole = stats.evalOnly?.byRole || {};
  const tbody = document.querySelector("#roleTable tbody");
  const rows = Object.entries(byRole);
  tbody.innerHTML = rows.length
    ? rows
        .map(
          ([r, m]) =>
            `<tr><td>${m.label || r}</td><td>${fmtWan(m.tokensWan || 0)}</td><td>${m.runs ?? 0}</td><td class="cost">¥${fmtCost(m.cost || 0)}</td></tr>`
        )
        .join("")
    : `<tr><td colspan="4">暂无角色分项（新跑批后将写入 eval-llm-usage.jsonl）</td></tr>`;

  const batchBody = document.querySelector("#batchTable tbody");
  const batches = stats.evalOnly?.byBatch || [];
  batchBody.innerHTML = batches.length
    ? batches
        .map(
          (b) =>
            `<tr><td>${b.batch}</td><td>${b.tasks ?? "—"}</td><td>${fmtWan(b.tokensWan || 0)}</td><td class="cost">¥${fmtCost(b.cost || 0)}</td></tr>`
        )
        .join("")
    : `<tr><td colspan="4">暂无 batch 汇总</td></tr>`;

  const taskBody = document.querySelector("#taskTable tbody");
  const tasks = stats.evalOnly?.byTask || [];
  taskBody.innerHTML = tasks.length
    ? tasks
        .slice(0, 50)
        .map(
          (t) =>
            `<tr><td>${t.batch}</td><td>${t.task_id}</td><td>${t.termination || "—"}</td><td>${fmtWan(t.tokensWan || 0)}</td><td class="cost">¥${fmtCost(t.cost || 0)}</td></tr>`
        )
        .join("")
    : `<tr><td colspan="5">暂无 run.json token_usage</td></tr>`;
}

function renderCharts() {
  if (typeof Chart === "undefined") return;
  const metric = document.getElementById("metric").value;
  const rows = getPeriodData();
  const labels = rows.map(periodLabel);
  const metricLabel = metric === "cost" ? "费用（元）" : "Token（万）";
  const cats = catMap();

  if (barChart) barChart.destroy();
  barChart = new Chart(document.getElementById("barChart"), {
    type: "bar",
    data: {
      labels,
      datasets: [{ label: metricLabel, data: rows.map((r) => rowMetric(r, metric)), backgroundColor: "rgba(22, 119, 255, 0.7)", borderRadius: 4 }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, ticks: { color: "#8b9bb4" } }, x: { ticks: { color: "#8b9bb4", maxRotation: 45 } } },
    },
  });

  const summaryCats = stats.summary.categories || {};
  const pieLabels = [];
  const pieData = [];
  const pieColors = [];
  Object.keys(cats).forEach((k) => {
    const c = summaryCats[k] || {};
    const v = metric === "cost" ? c.cost || 0 : c.tokensWan || c.calls || 0;
    if (v <= 0) return;
    pieLabels.push(cats[k].label);
    pieData.push(v);
    pieColors.push(cats[k].color);
  });

  document.getElementById("pieTitle").textContent = metric === "cost" ? "类型费用占比（元）" : "类型用量占比";
  if (pieChart) pieChart.destroy();
  pieChart = new Chart(document.getElementById("pieChart"), {
    type: "pie",
    data: { labels: pieLabels, datasets: [{ data: pieData, backgroundColor: pieColors }] },
    options: { responsive: true, plugins: { legend: { position: "right", labels: { color: "#e7ecf3" } } } },
  });
}

function renderAll() {
  renderSummaryCards();
  renderUsageCostTable();
  renderModelTable();
  renderMcpTable();
  renderRoleTable();
  renderCharts();
  const t = new Date(stats.updatedAt);
  document.getElementById("meta").textContent =
    `${currentMode === "eval" ? "测试看板" : "线上真实费用"} · 更新于 ${t.toLocaleString("zh-CN")} · 点「立即刷新」重新统计`;
  document.getElementById("notes").innerHTML = "<ul>" + (stats.notes || []).map((n) => `<li>${n}</li>`).join("") + "</ul>";
}

function setMode(mode) {
  currentMode = mode;
  document.querySelectorAll(".mode-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.mode === mode);
  });
}

async function runCollect() {
  const res = await fetch(apiUrl("/api/collect", { mode: "all" }), { method: "POST" });
  if (!res.ok) throw new Error("统计失败 " + res.status);
}

async function waitCollectDone(maxMs = 45000) {
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    const res = await fetch("/api/health");
    const h = await res.json();
    if (!h.collecting) return;
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error("统计超时");
}

async function load(opts = {}) {
  const { collect = false } = opts;
  try {
    if (collect) {
      document.getElementById("meta").textContent = "正在统计用量…";
      await runCollect();
      await waitCollectDone();
    }
    stats = await fetchStats();
    renderAll();
  } catch (e) {
    document.getElementById("meta").textContent = "加载失败: " + e.message;
    console.error(e);
  }
}

document.getElementById("tabOnline").addEventListener("click", () => {
  setMode("online");
  load();
});
document.getElementById("tabEval").addEventListener("click", () => {
  setMode("eval");
  load();
});
document.getElementById("period").addEventListener("change", () => stats && renderAll());
document.getElementById("metric").addEventListener("change", () => stats && renderAll());
document.getElementById("refresh").addEventListener("click", () => load({ collect: true }));

setMode("online");
load({ collect: true });
