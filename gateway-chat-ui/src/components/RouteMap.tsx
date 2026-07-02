import { useEffect, useRef, useState } from "react";
import { load as loadAmap } from "@amap/amap-jsapi-loader";
import type { SessionPoi } from "../types/sessionPoi";

type RouteMapPreviewProps = {
  pois: SessionPoi[];
  userLng?: number;
  userLat?: number;
};

export function RouteMapPreview({ pois, userLng, userLat }: RouteMapPreviewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<unknown>(null);
  const [expanded, setExpanded] = useState(false);
  const [mapError, setMapError] = useState(false);

  const points = pois
    .map((p) => p.location)
    .filter((l): l is { lng: number; lat: number } => l != null && l.lng != null && l.lat != null);

  useEffect(() => {
    const key = (import.meta.env.VITE_AMAP_JS_KEY as string | undefined)?.trim();
    const el = containerRef.current;
    if (!key || !el || points.length < 1) return;

    let cancelled = false;
    setMapError(false);

    void loadAmap({ key, version: "2.0" })
      .then((AMap: {
        Map: new (el: HTMLElement, opts: Record<string, unknown>) => {
          add: (o: unknown) => void;
          setFitView: () => void;
        };
        Marker: new (opts: { position: [number, number] }) => unknown;
        Polyline: new (opts: Record<string, unknown>) => unknown;
      }) => {
        if (cancelled || !containerRef.current) return;
        const center = points[0]!;
        const map = new AMap.Map(containerRef.current, {
          zoom: 14,
          center: [center.lng, center.lat],
          viewMode: "2D",
          dragEnable: true,
          zoomEnable: true,
          touchZoom: true,
        });
        mapRef.current = map;

        const path: [number, number][] = [];
        if (userLng != null && userLat != null) {
          path.push([userLng, userLat]);
        }
        for (const p of points) {
          path.push([p.lng, p.lat]);
          const marker = new AMap.Marker({ position: [p.lng, p.lat] });
          map.add(marker);
        }
        if (path.length >= 2) {
          const polyline = new AMap.Polyline({
            path,
            strokeColor: "#34c759",
            strokeWeight: 5,
            lineJoin: "round",
          });
          map.add(polyline);
          map.setFitView();
        }
      })
      .catch(() => {
        if (!cancelled) setMapError(true);
      });

    return () => {
      cancelled = true;
      const m = mapRef.current as { destroy?: () => void } | null;
      m?.destroy?.();
      mapRef.current = null;
    };
  }, [points, userLng, userLat, expanded]);

  if (points.length < 1) return null;

  return (
    <div className={`route-map-wrap${expanded ? " expanded" : ""}`}>
      <button
        type="button"
        className="route-map-toggle"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        {expanded ? "收起地图" : "展开路线地图"}
      </button>
      <div
        ref={containerRef}
        className="route-map-canvas"
        role="img"
        aria-label="行程路线地图"
      />
      {mapError ? (
        <p className="route-map-fallback">地图加载失败，请检查 VITE_AMAP_JS_KEY 与白名单</p>
      ) : null}
    </div>
  );
}
