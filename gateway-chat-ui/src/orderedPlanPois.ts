import { splitPlanWithPois } from "./planPoiEmbed";
import type { SessionPoi } from "./types/sessionPoi";

function hasCoords(poi: SessionPoi): boolean {
  const loc = poi.location;
  return loc != null && loc.lng != null && loc.lat != null;
}

/** 按方案正文出现顺序提取有坐标的 POI（去重），供行程地图使用。 */
export function orderedPlanPois(planText: string, pois: SessionPoi[]): SessionPoi[] {
  const segments = splitPlanWithPois(planText, pois);
  const seen = new Set<string>();
  const out: SessionPoi[] = [];

  for (const seg of segments) {
    if (seg.kind !== "poi") continue;
    if (seen.has(seg.poi.id)) continue;
    if (!hasCoords(seg.poi)) continue;
    seen.add(seg.poi.id);
    out.push(seg.poi);
  }

  if (out.length < 2) {
    for (const p of pois) {
      if (seen.has(p.id) || !hasCoords(p)) continue;
      seen.add(p.id);
      out.push(p);
      if (out.length >= 8) break;
    }
  }

  return out;
}

export function canShowRouteMap(planText: string, pois: SessionPoi[]): boolean {
  return orderedPlanPois(planText, pois).length >= 2;
}
