import { useEffect, useMemo, useRef, useState } from "react";
import { useAmapRouteMap } from "../hooks/useAmapRouteMap";
import { useSessionRoute } from "../hooks/useSessionRoute";
import { orderedPlanPois } from "../orderedPlanPois";
import { buildLegsFromPlanText, summarizeRoute } from "../planRouteLegs";
import type { ResolvedLocation } from "../location";
import type { SessionPoi } from "../types/sessionPoi";
import { RouteSheetList } from "./RouteSheetList";

type RouteSheetOverlayProps = {
  open: boolean;
  planText: string;
  pois: SessionPoi[];
  sessionKey: string;
  userLocation: ResolvedLocation | null;
  onClose: () => void;
};

export function RouteSheetOverlay({
  open,
  planText,
  pois,
  sessionKey,
  onClose,
}: RouteSheetOverlayProps) {
  const mapRef = useRef<HTMLDivElement>(null);
  const [activeIndex, setActiveIndex] = useState<number | null>(0);

  const ordered = useMemo(() => orderedPlanPois(planText, pois), [planText, pois]);
  const route = useSessionRoute(sessionKey, planText, pois, open && ordered.length >= 2);

  const legs = route?.legs ?? buildLegsFromPlanText(planText, ordered);
  const { summary } = summarizeRoute(ordered.length, legs);

  const path = useMemo(() => {
    if (route?.path && route.path.length >= 2) {
      return route.path.map((p) => [p.lng, p.lat] as [number, number]);
    }
    return undefined;
  }, [route?.path]);

  const { mapError, resize } = useAmapRouteMap(mapRef, ordered, {
    enabled: open,
    activeIndex,
    path,
    zoom: 12,
  });

  useEffect(() => {
    if (!open) return;
    const t = window.setTimeout(() => resize(), 380);
    return () => window.clearTimeout(t);
  }, [open, resize]);

  useEffect(() => {
    if (open) setActiveIndex(0);
  }, [open, planText]);

  if (!open || ordered.length < 2) return null;

  return (
    <div className={`route-sheet-overlay${open ? " open" : ""}`} role="dialog" aria-modal="true">
      <div className="route-sheet-map-area">
        <button type="button" className="route-sheet-back" onClick={onClose} aria-label="返回对话">
          ←
        </button>
        <div ref={mapRef} className="route-sheet-map-canvas" />
        {mapError ? (
          <p className="route-sheet-map-fallback">地图加载失败，路线列表仍可查看</p>
        ) : null}
      </div>
      <div className="route-sheet-panel">
        <RouteSheetList
          pois={ordered}
          legs={legs}
          summary={summary}
          activeIndex={activeIndex}
          onSelectStop={setActiveIndex}
        />
      </div>
    </div>
  );
}
