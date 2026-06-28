/** 用户同意定位后写入 localStorage */
export const LOCATION_CONSENT_LS = "gw.locationConsent";
export const LOCATION_CONSENT_VALUE = "granted-v1";
export const LOCATION_SNAPSHOT_LS = "gw.locationSnapshot";

/** 注入 Agent 的首条上下文前缀（对话区隐藏） */
export const LOCATION_CTX_MARKER = "[位置上下文]";

export type ResolvedLocation = {
  summary: string;
  city: string;
  district: string;
  address: string;
  lng?: number;
  lat?: number;
  source: "browser" | "ip" | "mixed";
  accuracyM?: number;
};

export type IpLocationPayload = {
  ok?: boolean;
  province?: string;
  city?: string;
  district?: string;
  lng?: number;
  lat?: number;
  error?: string;
};

export type ClientContextResponse = {
  ok?: boolean;
  client_ip?: string;
  ip_location?: IpLocationPayload;
  ip_note?: string;
};

export type RegeoResponse = {
  ok?: boolean;
  formatted_address?: string;
  province?: string;
  city?: string;
  district?: string;
  township?: string;
  street?: string;
  lng?: number;
  lat?: number;
  accuracy_m?: number;
  error?: string;
};

export function clientContextApiBase(): string {
  const fromEnv = (import.meta.env.VITE_CLIENT_CONTEXT_API as string | undefined)?.trim();
  if (fromEnv) return fromEnv.replace(/\/$/, "");
  return "";
}

export function hasStoredLocationConsent(): boolean {
  try {
    return localStorage.getItem(LOCATION_CONSENT_LS) === LOCATION_CONSENT_VALUE;
  } catch {
    return false;
  }
}

export function storeLocationConsent(): void {
  localStorage.setItem(LOCATION_CONSENT_LS, LOCATION_CONSENT_VALUE);
}

export function loadStoredLocationSnapshot(): ResolvedLocation | null {
  try {
    const raw = localStorage.getItem(LOCATION_SNAPSHOT_LS);
    if (!raw) return null;
    const o = JSON.parse(raw) as ResolvedLocation;
    if (!o || typeof o.summary !== "string" || !o.summary.trim()) return null;
    return o;
  } catch {
    return null;
  }
}

export function storeLocationSnapshot(loc: ResolvedLocation): void {
  try {
    localStorage.setItem(LOCATION_SNAPSHOT_LS, JSON.stringify(loc));
  } catch {
    /* quota / private mode */
  }
}

export function isSecureContextForGeo(): boolean {
  return typeof window !== "undefined" && window.isSecureContext;
}

export function readBrowserPosition(): Promise<GeolocationPosition | null> {
  if (typeof navigator === "undefined" || !navigator.geolocation) {
    return Promise.resolve(null);
  }
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve(pos),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 14_000, maximumAge: 0 },
    );
  });
}

function cleanCity(city: unknown): string {
  if (city == null || Array.isArray(city)) return "";
  const s = String(city).replace(/\[|\]/g, "").trim();
  return s === "[]" ? "" : s;
}

/** 直辖市等 province 与 city 相同时避免「北京市北京市」 */
function formatIpRegion(province: string, city: string): string {
  const p = province.trim();
  const c = city.trim();
  if (!p && !c) return "";
  if (!p) return c;
  if (!c || p === c || c.startsWith(p) || p.startsWith(c)) return p;
  return `${p}${c}`;
}

export function buildResolvedLocation(
  ipLoc: IpLocationPayload | null | undefined,
  regeo: RegeoResponse | null,
  browser: { lng: number; lat: number; accuracyM?: number } | null,
): ResolvedLocation | null {
  const ipCity = cleanCity(ipLoc?.city ?? "");
  const ipProvince = (ipLoc as { province?: string })?.province?.replace(/\[|\]/g, "") ?? "";

  if (regeo?.ok) {
    const city = cleanCity(regeo.city || ipCity || ipProvince);
    const district = (regeo.district || "").replace(/\[|\]/g, "");
    const address =
      regeo.formatted_address ||
      [regeo.province, city, district, regeo.township, regeo.street].filter(Boolean).join("");
    const summary = address || [city, district].filter(Boolean).join(" ");
    return {
      summary: summary || city || "未知",
      city,
      district,
      address: address || summary,
      lng: regeo.lng ?? browser?.lng,
      lat: regeo.lat ?? browser?.lat,
      source: browser ? "browser" : "mixed",
      accuracyM: browser?.accuracyM ?? regeo.accuracy_m,
    };
  }

  if (browser) {
    return {
      summary: `坐标 ${browser.lng.toFixed(5)}, ${browser.lat.toFixed(5)}`,
      city: ipCity,
      district: "",
      address: "",
      lng: browser.lng,
      lat: browser.lat,
      source: "browser",
      accuracyM: browser.accuracyM,
    };
  }

  if (ipLoc?.ok && ipCity) {
    const region = formatIpRegion(ipProvince, ipCity);
    return {
      summary: region || ipCity,
      city: ipCity,
      district: "",
      address: region || ipCity,
      lng: ipLoc.lng,
      lat: ipLoc.lat,
      source: "ip",
    };
  }

  return null;
}

/** 根据用户首句粗分场景（注入 Agent 时用，非最终判定） */
export type TravelSceneHint = "nearby" | "city" | "unknown";

/** 从用户首句生成 intake 去重提示（注入 Agent，减少重复提问） */
export function buildUserSlotHints(userText: string): string {
  const t = userText.trim();
  if (!t) return "";
  const lines: string[] = [];
  if (/今晚|今天晚上|晚上|夜间|傍晚|夜逛|晚上想|夜里/i.test(t)) {
    lines.push("时段=今晚晚间（勿再问日期/时段，勿出半日/一日/两日时长题）");
  }
  if (/明天|后天|周[一二三四五六日天]|上午|下午|早上|中午/i.test(t)) {
    lines.push("原话含日期或时段（勿重复问同一时间维度）");
  }
  if (/(?:^|[^\d])(?:1|一)\s*人|独自|单身|一个人|2\s*人|两人|双人|情侣|3[-~]4|一家|带娃|亲子|\d+\s*人/i.test(t)) {
    lines.push("原话可能已含人数（若明确则本轮勿再问人数）");
  }
  if (/半天|一天|两天|两日|三日|\d+\s*天/i.test(t)) {
    lines.push("原话可能已含游玩时长（勿再问半日/一日题）");
  }
  if (/自驾|地铁|公交|打车|步行|骑行/i.test(t)) {
    lines.push("原话可能已含交通方式（勿重复问交通题）");
  }
  if (/现在|马上|这就|立刻/i.test(t)) {
    lines.push("depart_window=now（勿再问出发窗口；用上下文当前当地时间作 T_now）");
  }
  if (/明天|后天|周末|周[一二三四五六日天]/i.test(t)) {
    lines.push("原话含出发日期（勿再问「现在/明天/周末」出发窗口题）");
  }
  if (/几小时|2[-~]3\s*小时|三小时|四小时/i.test(t)) {
    lines.push("原话可能已含 play_duration（勿再问玩多久）");
  }
  if (/古镇|博物馆|乐园|爬山|海边|森林公园|露营|农家乐/i.test(t)) {
    lines.push("原话可能已含地点类型倾向（若很明确则勿再问 A–F 类型题）");
  }
  if (/几点前回|回家|赶回|六点前|下班前/i.test(t)) {
    lines.push("口头回程时刻=软约束 T_end（勿单独问回程题；return_to 默认定位区）");
  }
  if (lines.length === 0) return "";
  return `【原话槽位】${lines.join("；")}。`;
}

/** 注入 Agent 的当前当地时间（Asia/Shanghai） */
export function formatLocalNowForAgent(): string {
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date());
  const get = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((p) => p.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")}`;
}

export function inferTravelSceneFromUserText(text: string): TravelSceneHint {
  const t = text.trim();
  if (!t) return "unknown";
  if (/周边|附近|郊野|不出城|半日|溜娃|家门口|周边玩|出去逛逛|附近玩|同城/i.test(t)) return "nearby";
  if (
    /(?:去|到|在|想去|要去|计划去|飞往|飞到)[\u4e00-\u9fa5]{2,}(?:市|城|玩|旅游|旅行|出差)/.test(t) ||
    /\d+\s*天.*(?:游|玩|行程)/.test(t) ||
    /异地|出城游|城市游|几日游/.test(t)
  ) {
    return "city";
  }
  return "unknown";
}

export function formatLocationContextMessage(loc: ResolvedLocation, userText?: string): string {
  const acc =
    loc.accuracyM != null && loc.accuracyM < 500
      ? `（浏览器定位，精度约 ${Math.round(loc.accuracyM)} 米）`
      : loc.source === "ip"
        ? "（来自公网 IP + 高德 IP 库，手机热点/4G 常不准，请以问卷为准）"
        : "";
  const coord =
    loc.lng != null && loc.lat != null ? `坐标 ${loc.lng.toFixed(5)}, ${loc.lat.toFixed(5)}。` : "";
  const region = `${loc.city || "未知城市"}${loc.district ? ` · ${loc.district}` : ""}`;
  const scene = userText ? inferTravelSceneFromUserText(userText) : "unknown";

  let sceneBlock: string;
  const slotHints = userText ? buildUserSlotHints(userText) : "";

  if (scene === "nearby") {
    const cityFilled = Boolean(loc.city?.trim());
    const districtHint = loc.district
      ? `场景 B：city=${loc.city} 已由定位填写，勿再问城市。区=${loc.district}，用一题确认是否从该区出发（A/B/C 为同城其他区名，D. 其他填区或地标），禁止「出行范围/公里圈」题。return_to 默认=${loc.district}。`
      : cityFilled
        ? `场景 B：city=${loc.city} 已填，勿再问城市。须用一题问具体区（A/B/C 为该市辖区名，D. 其他填区）。return_to 默认同出发区。`
        : `场景 B：定位无 city，才可用一题问城市；有 city 后再问区。`;
    sceneBlock =
      `判定倾向：周边游玩。${districtHint} 须按 travel-intake 问 place_type（A–F）、depart_window、play_duration（已填不问）；禁止回程题。` +
      `${slotHints ? ` ${slotHints}` : ""}`;
  } else if (scene === "city") {
    sceneBlock =
      `判定倾向：城市出行（场景 A）。目的地以用户原话为准；当前 GPS/IP 仅作出发地参考（${region}），勿把出发地当成目的地。${slotHints ? ` ${slotHints}` : ""}`;
  } else {
    sceneBlock =
      `场景待用户明确：若「周边/附近」按场景 B 用当前位置（${region}）；若「去某城」按场景 A。${slotHints ? ` ${slotHints}` : ""}`;
  }

  const nowLocal = formatLocalNowForAgent();
  return (
    `${LOCATION_CTX_MARKER} 用户已同意本页获取位置（本条与用户首句在同一条 user 消息中）。` +
    `读完下方用户原话与定位后，直接按 travel-intake 出 2～3 道选择题；禁止 NO_REPLY、禁止先调 lifecare 工具。` +
    `问卷排版强制：题用「1. 题干」「2. 题干」、选项用「A. …」各占一行，题间空行；禁止 ---、1️⃣、第1题、Markdown 加粗题号。` +
    `当前推测：${loc.summary}${acc}。${coord}` +
    `当前当地时间：${nowLocal}（Asia/Shanghai）。用户选「现在出发」时以此为 T_now；可玩截止默认当日 23:00。` +
    sceneBlock
  );
}

export function locationSnapshotKey(loc: ResolvedLocation): string {
  const lng = loc.lng != null ? loc.lng.toFixed(3) : "";
  const lat = loc.lat != null ? loc.lat.toFixed(3) : "";
  return `${loc.city}|${loc.district}|${lng}|${lat}`;
}

export function mergeLocationPrefix(loc: ResolvedLocation, userText: string): string {
  const visible = userText.trim();
  const prefix = formatLocationContextMessage(loc, visible);
  return `${prefix}\n\n${visible}`;
}

/** 从合并后的 user 消息中取出对话区应展示的用户原话 */
export function extractUserVisibleTextFromMessage(text: string): string {
  const t = text.trimStart();
  if (!t.startsWith(LOCATION_CTX_MARKER)) return text;
  const sep = text.indexOf("\n\n");
  if (sep < 0) return "";
  return text.slice(sep + 2).trim();
}

/** 是否为「仅位置注入、无用户原话」的 hidden user（旧会话或异常） */
export function isLocationContextOnlyMessage(text: string): boolean {
  const t = text.trimStart();
  if (!t.startsWith(LOCATION_CTX_MARKER)) return false;
  return !extractUserVisibleTextFromMessage(text).trim();
}

export function shouldInjectLocationPrefix(
  loc: ResolvedLocation | null,
  sessionKey: string,
  lastInjectedKeyBySession: Map<string, string>,
): boolean {
  if (!loc || !sessionKey.trim()) return false;
  const key = locationSnapshotKey(loc);
  return lastInjectedKeyBySession.get(sessionKey.trim()) !== key;
}

export function isLocationContextMessage(text: string): boolean {
  return text.trimStart().startsWith(LOCATION_CTX_MARKER);
}

export async function fetchClientContext(): Promise<ClientContextResponse> {
  const base = clientContextApiBase();
  const url = base ? `${base}/api/client-context` : "/api/client-context";
  const r = await fetch(url, { credentials: "same-origin" });
  if (!r.ok) throw new Error(`client-context ${r.status}`);
  return (await r.json()) as ClientContextResponse;
}

export async function fetchRegeo(
  lng: number,
  lat: number,
  accuracyM?: number,
): Promise<RegeoResponse> {
  const base = clientContextApiBase();
  const url = base ? `${base}/api/client-context/regeo` : "/api/client-context/regeo";
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ lng, lat, accuracy_m: accuracyM }),
  });
  if (!r.ok) throw new Error(`regeo ${r.status}`);
  return (await r.json()) as RegeoResponse;
}

/** 浏览器定位超时（与 readBrowserPosition 一致） */
export const BROWSER_GEO_TIMEOUT_MS = 14_000;

/** 发首条消息前最多等待位置注入的时长 */
export const LOCATION_INJECT_WAIT_MS = 5_000;

export type LocationResolveTiming = {
  totalMs: number;
  ipMs: number;
  browserMs: number;
  regeoMs: number;
  secureContext: boolean;
};

export async function resolveUserLocation(): Promise<ResolvedLocation | null> {
  const { loc } = await resolveUserLocationTimed();
  return loc;
}

/** IP 与浏览器定位并行，典型：仅 IP ~0.3–1s；HTTPS+GPS+逆地理 ~2–6s（用户授权后） */
export async function resolveUserLocationTimed(): Promise<{
  loc: ResolvedLocation | null;
  timing: LocationResolveTiming;
}> {
  const t0 = performance.now();
  const secureContext = isSecureContextForGeo();

  let ipMs = 0;
  let browserMs = 0;
  let regeoMs = 0;

  const ipStarted = performance.now();
  const ipTask = fetchClientContext()
    .then((ctx) => {
      ipMs = Math.round(performance.now() - ipStarted);
      return ctx.ip_location ?? null;
    })
    .catch(() => {
      ipMs = Math.round(performance.now() - ipStarted);
      return null;
    });

  const browserStarted = performance.now();
  const browserTask = readBrowserPosition().then((pos) => {
    browserMs = Math.round(performance.now() - browserStarted);
    if (!pos) return null;
    return {
      lng: pos.coords.longitude,
      lat: pos.coords.latitude,
      accuracyM: pos.coords.accuracy,
    };
  });

  const [ipLoc, browser] = await Promise.all([ipTask, browserTask]);

  let regeo: RegeoResponse | null = null;
  if (browser) {
    const regeoStarted = performance.now();
    try {
      regeo = await fetchRegeo(browser.lng, browser.lat, browser.accuracyM);
    } catch {
      regeo = null;
    }
    regeoMs = Math.round(performance.now() - regeoStarted);
  }

  const loc = buildResolvedLocation(ipLoc, regeo, browser);
  return {
    loc,
    timing: {
      totalMs: Math.round(performance.now() - t0),
      ipMs,
      browserMs,
      regeoMs,
      secureContext,
    },
  };
}
