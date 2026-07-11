import { useEffect, useRef, useState } from "react";
import { load as loadAmap } from "@amap/amap-jsapi-loader";
import type { SessionPoi } from "../types/sessionPoi";

const ROUTE_COLOR = "#34c759";

export function markerHtml(num: number, active: boolean): string {
  const bg = active ? "#ff6b00" : ROUTE_COLOR;
  const size = active ? 34 : 28;
  return `<div style="width:${size}px;height:${size}px;border-radius:50%;background:${bg};color:#fff;font-weight:700;font-size:13px;display:flex;align-items:center;justify-content:center;border:3px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.22)">${num}</div>`;
}

type AmapLike = {
  Map: new (el: HTMLElement, opts: Record<string, unknown>) => AmapMap;
  Marker: new (opts: Record<string, unknown>) => unknown;
  Polyline: new (opts: Record<string, unknown>) => unknown;
  Pixel: new (x: number, y: number) => unknown;
};

type AmapMap = {
  add: (o: unknown) => void;
  clearMap: () => void;
  setFitView: (overlays?: unknown, immediately?: boolean, avoid?: number[]) => void;
  setCenter: (center: [number, number]) => void;
  destroy: () => void;
  resize: () => void;
};

const MAP_OPTS = {
  viewMode: "2D",
  dragEnable: true,
  zoomEnable: true,
  touchZoom: true,
  doubleClickZoom: true,
  scrollWheel: true,
  rotateEnable: false,
  pitchEnable: false,
};

function poisSignature(pois: SessionPoi[]): string {
  return pois
    .map((p) => {
      const loc = p.location;
      return `${p.id}:${loc?.lng ?? ""},${loc?.lat ?? ""}`;
    })
    .join("|");
}

function pathSignature(path?: Array<[number, number]>): string {
  if (!path?.length) return "";
  return path.map(([lng, lat]) => `${lng},${lat}`).join("|");
}

function drawRoute(
  AMap: AmapLike,
  map: AmapMap,
  pois: SessionPoi[],
  activeIndex: number | null,
  path?: Array<[number, number]>,
) {
  map.clearMap();
  const linePath =
    path && path.length >= 2
      ? path
      : pois
          .filter((p) => p.location?.lng != null && p.location?.lat != null)
          .map((p) => [p.location!.lng, p.location!.lat] as [number, number]);

  const overlays: unknown[] = [];

  pois.forEach((p, i) => {
    const loc = p.location;
    if (!loc || loc.lng == null || loc.lat == null) return;
    const marker = new AMap.Marker({
      position: [loc.lng, loc.lat],
      content: markerHtml(i + 1, activeIndex === i),
      offset: new AMap.Pixel(-14, -14),
      zIndex: activeIndex === i ? 120 : 100,
    });
    map.add(marker);
    overlays.push(marker);
  });

  if (linePath.length >= 2) {
    const polyline = new AMap.Polyline({
      path: linePath,
      strokeColor: ROUTE_COLOR,
      strokeWeight: 6,
      lineJoin: "round",
      strokeOpacity: 0.92,
    });
    map.add(polyline);
    overlays.push(polyline);
    map.setFitView(overlays, false, [36, 36, 36, 36]);
  }
}

export function useAmapRouteMap(
  containerRef: React.RefObject<HTMLDivElement | null>,
  pois: SessionPoi[],
  options: {
    enabled: boolean;
    activeIndex?: number | null;
    path?: Array<[number, number]>;
    zoom?: number;
  },
) {
  const { enabled, activeIndex = null, path, zoom = 13 } = options;
  const mapRef = useRef<AmapMap | null>(null);
  const amapRef = useRef<AmapLike | null>(null);
  const poisRef = useRef(pois);
  poisRef.current = pois;
  const pathRef = useRef(path);
  pathRef.current = path;
  const [mapError, setMapError] = useState(false);
  const [mapReady, setMapReady] = useState(false);

  const poisKey = poisSignature(pois);
  const pathKey = pathSignature(path);

  useEffect(() => {
    const key = (import.meta.env.VITE_AMAP_JS_KEY as string | undefined)?.trim();
    const el = containerRef.current;
    if (!enabled || !key || !el || pois.length < 2) {
      setMapReady(false);
      return;
    }

    let cancelled = false;
    setMapError(false);

    void loadAmap({ key, version: "2.0" })
      .then((AMap: AmapLike) => {
        if (cancelled || !containerRef.current) return;
        amapRef.current = AMap;

        const currentPois = poisRef.current;
        const first = currentPois.find((p) => p.location?.lng != null && p.location?.lat != null);
        if (!first?.location) return;

        const map = new AMap.Map(containerRef.current, {
          ...MAP_OPTS,
          zoom,
          center: [first.location.lng, first.location.lat],
        });
        mapRef.current = map;
        drawRoute(AMap, map, currentPois, null, pathRef.current);
        setMapReady(true);
      })
      .catch(() => {
        if (!cancelled) setMapError(true);
      });

    return () => {
      cancelled = true;
      mapRef.current?.destroy?.();
      mapRef.current = null;
      amapRef.current = null;
      setMapReady(false);
    };
  }, [enabled, poisKey, zoom]);

  useEffect(() => {
    const map = mapRef.current;
    const AMap = amapRef.current;
    if (!map || !AMap || !mapReady) return;
    const currentPois = poisRef.current;
    drawRoute(AMap, map, currentPois, activeIndex ?? null, pathRef.current);
    if (activeIndex != null && currentPois[activeIndex]?.location) {
      const loc = currentPois[activeIndex]!.location!;
      map.setCenter([loc.lng, loc.lat]);
    }
  }, [activeIndex, poisKey, pathKey, mapReady]);

  const resize = () => {
    mapRef.current?.resize?.();
  };

  return { mapError, mapReady, resize };
}
