/** 任务进展 · 工具调用：结构化解析 tool 名 → 中文标签 */

export type ProcessStep = { id: string; clock: string; msg: string };

const TOOL_LABELS: Record<string, string> = {
  lifecare__lifecare_get_weather: "查询天气",
  lifecare_get_weather: "查询天气",
  lifecare__lifecare_search_places: "搜索 POI / 地点",
  lifecare_search_places: "搜索 POI / 地点",
  lifecare__lifecare_plan_route: "规划路线",
  lifecare_plan_route: "规划路线",
};

export function isHiddenProcessStepMsg(msg: string): boolean {
  const t = msg.trim().replace(/^【+|】+$/g, "").trim();
  if (!t) return true;
  if (t === "本轮任务结束") return true;
  if (t === "加载历史会话信息" || /^加载.*历史.*会话/i.test(t)) return true;
  if (/^加载该会话历史/i.test(t)) return true;
  return false;
}

export function appendProcessStep(prev: ProcessStep[], msg: string): ProcessStep[] {
  const line = msg.trim();
  if (!line || isHiddenProcessStepMsg(line)) return prev;
  const last = prev[prev.length - 1];
  if (last && last.msg === line) return prev;
  const clock = new Date().toLocaleTimeString();
  return [...prev.slice(-80), { id: `${Date.now()}-${prev.length}`, clock, msg: line }];
}

export function labelForTool(name: string): string {
  const raw = name.trim();
  if (!raw) return "工具调用";
  const lower = raw.toLowerCase();
  if (TOOL_LABELS[lower]) return TOOL_LABELS[lower]!;
  const short = lower.replace(/^lifecare__/, "");
  if (TOOL_LABELS[short]) return TOOL_LABELS[short]!;
  if (/weather/i.test(lower)) return "查询天气";
  if (/search_places|search_poi|poi/i.test(lower)) return "搜索 POI / 地点";
  if (/plan_route|route/i.test(lower)) return "规划路线";
  return `调用工具：${raw.replace(/^lifecare__/, "")}`;
}

function addToolName(names: string[], seen: Set<string>, name: unknown): void {
  if (typeof name !== "string") return;
  const t = name.trim();
  if (!t) return;
  const key = t.toLowerCase();
  if (seen.has(key)) return;
  seen.add(key);
  names.push(t);
}

function scanContentBlocks(content: unknown, names: string[], seen: Set<string>): void {
  if (!Array.isArray(content)) return;
  for (const block of content) {
    if (!block || typeof block !== "object") continue;
    const b = block as Record<string, unknown>;
    const typ = typeof b.type === "string" ? b.type.toLowerCase() : "";
    if (typ === "toolcall" || typ === "tool_use" || typ === "function_call") {
      addToolName(names, seen, b.name ?? b.toolName ?? b.tool);
    }
    if (typ === "toolresult" || typ === "tool_result") {
      addToolName(names, seen, b.toolName ?? b.name ?? b.tool);
    }
  }
}

/** 从 WS / history payload 提取 tool 名（去重保序） */
export function extractToolNamesFromPayload(payload: unknown): string[] {
  const names: string[] = [];
  const seen = new Set<string>();

  if (payload && typeof payload === "object") {
    const p = payload as Record<string, unknown>;
    const data = p.data && typeof p.data === "object" ? (p.data as Record<string, unknown>) : null;
    for (const src of [p, data]) {
      if (!src) continue;
      for (const key of ["tool", "name", "toolName"]) {
        addToolName(names, seen, src[key]);
      }
      scanContentBlocks(src.content, names, seen);
    }
    const msg = p.message;
    if (msg && typeof msg === "object") {
      const m = msg as Record<string, unknown>;
      for (const key of ["tool", "name", "toolName"]) {
        addToolName(names, seen, m[key]);
      }
      scanContentBlocks(m.content, names, seen);
    }
    const delta = p.delta;
    if (delta && typeof delta === "object") {
      scanContentBlocks((delta as Record<string, unknown>).content, names, seen);
    }
  }

  const raw = JSON.stringify(payload ?? "");
  for (const m of raw.matchAll(/lifecare__[a-z0-9_]+/gi) ?? []) {
    addToolName(names, seen, m[0]!);
  }
  return names;
}

export function historyDataUsedSearchPlaces(data: unknown): boolean {
  const raw = JSON.stringify(data ?? "");
  return /lifecare_search_places|lifecare__lifecare_search_places|"mcpTool"\s*:\s*"lifecare_search_places"/i.test(
    raw,
  );
}

export function appendToolStepsFromPayload(
  prev: ProcessStep[],
  payload: unknown,
  seenTools: Set<string>,
): ProcessStep[] {
  let next = prev;
  for (const name of extractToolNamesFromPayload(payload)) {
    const key = name.toLowerCase();
    if (seenTools.has(key)) continue;
    seenTools.add(key);
    next = appendProcessStep(next, labelForTool(name));
  }
  return next;
}
