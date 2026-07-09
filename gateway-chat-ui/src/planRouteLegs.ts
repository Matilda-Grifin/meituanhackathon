import { haversineMeters } from "./geo/distance";
import type { SessionPoi } from "./types/sessionPoi";
import type { RouteLegMode, SessionRouteLeg } from "./types/sessionRoute";

function inferMode(text: string): RouteLegMode {
  const t = text.toLowerCase();
  if (/驾车|自驾|开车/.test(t)) return "driving";
  if (/打车|出租|网约车/.test(t)) return "taxi";
  if (/地铁|公交|乘车|轻轨/.test(t)) return "transit";
  if (/骑行|骑车|单车/.test(t)) return "bicycling";
  if (/步行|走路|徒步/.test(t)) return "walking";
  return "unknown";
}

function legIcon(mode: RouteLegMode): string {
  if (mode === "driving" || mode === "taxi") return "🚗";
  if (mode === "transit") return "🚇";
  if (mode === "bicycling") return "🚲";
  return "🚶";
}

function extractBetween(planText: string, fromName: string, toName: string): string {
  const fromIdx = planText.indexOf(fromName);
  if (fromIdx < 0) return "";
  const searchFrom = fromIdx + fromName.length;
  const toIdx = planText.indexOf(toName, searchFrom);
  if (toIdx < 0) return planText.slice(searchFrom, searchFrom + 400);
  return planText.slice(searchFrom, toIdx);
}

function parseDistanceDuration(text: string): { distance_m?: number; duration_s?: number } {
  let distance_m: number | undefined;
  let duration_s: number | undefined;

  const kmMatch = text.match(/(?:全程约?|约)?\s*(\d+(?:\.\d+)?)\s*(?:公里|km)/i);
  if (kmMatch) distance_m = Math.round(parseFloat(kmMatch[1]!) * 1000);

  const mMatch = text.match(/(?:步行约?|约)\s*(\d+)\s*(?:米|m)(?!\w)/i);
  if (mMatch) distance_m = parseInt(mMatch[1]!, 10);

  const minMatch = text.match(/(?:车程约?|约|需要)?\s*(\d+)\s*分钟/);
  if (minMatch) duration_s = parseInt(minMatch[1]!, 10) * 60;

  return { distance_m, duration_s };
}

function buildLabel(mode: RouteLegMode, distance_m: number, duration_s: number, raw?: string): string {
  if (raw && raw.trim().length >= 6 && raw.length <= 80) {
    const trimmed = raw.replace(/\s+/g, " ").trim();
    if (/公里|分钟|步行|打车|驾车|地铁|km|m/.test(trimmed)) {
      return trimmed.length > 48 ? `${trimmed.slice(0, 48)}…` : trimmed;
    }
  }
  const icon = legIcon(mode);
  const km =
    distance_m >= 1000
      ? `${(distance_m / 1000).toFixed(1)}km`
      : `${Math.round(distance_m)}m`;
  const min = Math.max(1, Math.round(duration_s / 60));
  return `${icon} ${km} · ${min}分钟`;
}

export function formatRouteLegDisplay(leg: SessionRouteLeg): string {
  if (leg.label) return leg.label;
  return buildLabel(leg.mode, leg.distance_m, leg.duration_s);
}

/** 从方案正文 + POI 顺序构建段距（API 未返回时的前端 fallback）。 */
export function buildLegsFromPlanText(
  planText: string,
  orderedPois: SessionPoi[],
): SessionRouteLeg[] {
  const legs: SessionRouteLeg[] = [];
  for (let i = 1; i < orderedPois.length; i++) {
    const from = orderedPois[i - 1]!;
    const to = orderedPois[i]!;
    const between = extractBetween(planText, from.name, to.name);
    const mode = inferMode(between);
    const parsed = parseDistanceDuration(between);

    const fl = from.location!;
    const tl = to.location!;
    const estM = haversineMeters(fl.lng, fl.lat, tl.lng, tl.lat);
    const distance_m = parsed.distance_m ?? Math.round(estM);
    const duration_s =
      parsed.duration_s ??
      Math.max(60, Math.round((distance_m / (mode === "walking" ? 1.2 : 8)) ));

    const snippet = between
      .replace(/[#*!\[\]()]/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 80);

    legs.push({
      from_poi_id: from.id,
      to_poi_id: to.id,
      mode,
      distance_m,
      duration_s,
      label: buildLabel(mode, distance_m, duration_s, snippet || undefined),
      source: parsed.distance_m || parsed.duration_s ? "plan_text" : "estimated",
    });
  }
  return legs;
}

export function summarizeRoute(
  poiCount: number,
  legs: SessionRouteLeg[],
): { totalDistanceM: number; totalDurationS: number; summary: string } {
  const totalDistanceM = legs.reduce((s, l) => s + l.distance_m, 0);
  const totalDurationS = legs.reduce((s, l) => s + l.duration_s, 0);
  const km =
    totalDistanceM >= 1000
      ? `${(totalDistanceM / 1000).toFixed(1)} km`
      : `${totalDistanceM} m`;
  return {
    totalDistanceM,
    totalDurationS,
    summary: `包含 ${poiCount} 个地点，全程约 ${km}`,
  };
}
