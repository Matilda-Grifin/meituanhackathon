import { useEffect, useState } from "react";
import { clientContextApiBase } from "../location";
import { buildLegsFromPlanText } from "../planRouteLegs";
import { orderedPlanPois } from "../orderedPlanPois";
import type { SessionPoi } from "../types/sessionPoi";
import type { SessionRoute } from "../types/sessionRoute";

export function useSessionRoute(
  sessionKey: string,
  planText: string,
  pois: SessionPoi[],
  enabled: boolean,
): SessionRoute | null {
  const [route, setRoute] = useState<SessionRoute | null>(null);

  useEffect(() => {
    if (!enabled || !planText.trim() || !sessionKey.trim()) {
      setRoute(null);
      return;
    }

    const ordered = orderedPlanPois(planText, pois);
    if (ordered.length < 2) {
      setRoute(null);
      return;
    }

    const fallback = (): SessionRoute => {
      const legs = buildLegsFromPlanText(planText, ordered);
      return {
        ordered_poi_ids: ordered.map((p) => p.id),
        legs,
        total_distance_m: legs.reduce((s, l) => s + l.distance_m, 0),
        total_duration_s: legs.reduce((s, l) => s + l.duration_s, 0),
      };
    };

    const base = clientContextApiBase();
    const url =
      `${base}/api/session-route?session_key=${encodeURIComponent(sessionKey)}` +
      `&plan_text=${encodeURIComponent(planText.slice(0, 12000))}` +
      `&include_polyline=true`;

    let cancelled = false;
    void fetch(url)
      .then((r) => r.json())
      .then((d: { ok?: boolean; route?: SessionRoute }) => {
        if (cancelled) return;
        if (d.ok && d.route && Array.isArray(d.route.legs)) {
          setRoute(d.route);
        } else {
          setRoute(fallback());
        }
      })
      .catch(() => {
        if (!cancelled) setRoute(fallback());
      });

    return () => {
      cancelled = true;
    };
  }, [sessionKey, planText, pois, enabled]);

  return route;
}
