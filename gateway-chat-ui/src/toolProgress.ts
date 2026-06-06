/** 任务进展 · 工具调用：结构化解析 tool 名 → 中文标签 */

export type ProcessStep = { id: string; clock: string; msg: string };

/** 同一轮用户消息内，lifecare 主工具进展只展示一次（weather/search/route） */
export type LifecareProgressCategory = "weather" | "search" | "route";

const LIFECARE_CATEGORY_PREFIX = "__cat:";

const TOOL_LABELS: Record<string, string> = {
  lifecare__lifecare_get_weather: "查询天气",
  lifecare_get_weather: "查询天气",
  lifecare__lifecare_search_places: "搜索 POI / 地点",
  lifecare_search_places: "搜索 POI / 地点",
  lifecare__lifecare_plan_route: "规划路线",
  lifecare_plan_route: "规划路线",
  read: "加载行程规划指引",
  write: "更新配置文件",
  glob: "查找工作区文件",
};

export function isHiddenProcessStepMsg(msg: string): boolean {
  const t = msg.trim().replace(/^【+|】+$/g, "").trim();
  if (!t) return true;
  if (t === "本轮任务结束") return true;
  if (t === "加载历史会话信息" || /^加载.*历史.*会话/i.test(t)) return true;
  if (/^加载该会话历史/i.test(t)) return true;
  if (/^\[agent\]\s*\{/.test(t)) return true;
  if (t.startsWith("{") && /"runId"|"itemId"|"stream"\s*:\s*"item"/.test(t)) return true;
  if (/^行程图(?:生成|请求)失败/.test(t)) return true;
  if (/Gateway Time-out|504 Gateway/i.test(t)) return true;
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

function lifecareCategoryKey(cat: LifecareProgressCategory): string {
  return `${LIFECARE_CATEGORY_PREFIX}${cat}`;
}

/** 从展示文案或 tool 名推断 lifecare 主工具类别（用于进展条去重） */
export function lifecareProgressCategory(
  msgOrTool: string,
  kind: "msg" | "tool" = "msg",
): LifecareProgressCategory | null {
  if (kind === "tool") {
    const lower = msgOrTool.toLowerCase();
    if (/get_weather|weather/.test(lower)) return "weather";
    if (/search_places|search_poi/.test(lower)) return "search";
    if (/plan_route|route/.test(lower)) return "route";
    return null;
  }
  const t = msgOrTool.trim();
  if (t === "查询天气" || /^正在查询.+天气/.test(t)) return "weather";
  if (t === "搜索 POI / 地点" || /^正在搜索/.test(t)) return "search";
  if (t === "规划路线" || /^正在规划路线/.test(t)) return "route";
  return null;
}

function markLifecareCategory(seen: Set<string>, cat: LifecareProgressCategory): boolean {
  const key = lifecareCategoryKey(cat);
  if (seen.has(key)) return false;
  seen.add(key);
  return true;
}

/** 带来进展类别去重的步骤追加（fallback 路径用，避免 WS 重复事件刷「查询天气」） */
export function appendToolProgressStep(
  prev: ProcessStep[],
  msg: string,
  seen: Set<string>,
): ProcessStep[] {
  const cat = lifecareProgressCategory(msg, "msg");
  if (cat && !markLifecareCategory(seen, cat)) return prev;
  return appendProcessStep(prev, msg);
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
  if (lower === "read") return "加载行程规划指引";
  return `调用工具：${raw.replace(/^lifecare__/, "")}`;
}

function extractArgsFromPayload(payload: unknown): Record<string, unknown> {
  if (!payload || typeof payload !== "object") return {};
  const tryParse = (raw: string): Record<string, unknown> => {
    try {
      const j = JSON.parse(raw) as Record<string, unknown>;
      if (j.arguments && typeof j.arguments === "object") return j.arguments as Record<string, unknown>;
      if (j.input && typeof j.input === "object") return j.input as Record<string, unknown>;
      return j;
    } catch {
      return {};
    }
  };
  const p = payload as Record<string, unknown>;
  const data = p.data && typeof p.data === "object" ? (p.data as Record<string, unknown>) : null;
  for (const src of [data, p]) {
    if (!src) continue;
    const args = src.arguments ?? src.input ?? src.params;
    if (args && typeof args === "object") return args as Record<string, unknown>;
    if (typeof args === "string") {
      const parsed = tryParse(args);
      if (Object.keys(parsed).length) return parsed;
    }
  }
  const raw = JSON.stringify(payload ?? "");
  const m = raw.match(/"arguments"\s*:\s*(\{[\s\S]*?\})(?=,\s*"(?:name|tool|id)"|\})/);
  if (m) return tryParse(m[1]!);
  return {};
}

export function detailFromToolArgs(name: string, payload: unknown): string | null {
  const args = extractArgsFromPayload(payload);
  const lower = name.toLowerCase();

  if (/search_places|search_poi/.test(lower)) {
    const kw = [args.city, args.keyword, args.types, args.query].filter(Boolean).join(" ");
    return kw ? `正在搜索「${String(kw).slice(0, 48)}」` : null;
  }
  if (/get_weather|weather/.test(lower)) {
    const city = args.city ?? args.city_display;
    return city ? `正在查询${city}天气` : null;
  }
  if (/plan_route|route/.test(lower)) {
    const from = args.origin ?? args.from;
    const to = args.destination ?? args.to;
    if (from && to) return `正在规划路线：${from} → ${to}`;
  }
  return null;
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
    const cat = lifecareProgressCategory(name, "tool");
    if (cat && seenTools.has(lifecareCategoryKey(cat))) continue;
    seenTools.add(key);
    if (cat) seenTools.add(lifecareCategoryKey(cat));
    const label = detailFromToolArgs(name, payload) ?? labelForTool(name);
    next = appendProcessStep(next, label);
  }
  return next;
}
