import { useEffect, useRef, useState } from "react";
import { useAmapRouteMap } from "../hooks/useAmapRouteMap";
import type { SessionPoi } from "../types/sessionPoi";

type RouteMapMiniProps = {
  pois: SessionPoi[];
  path?: Array<[number, number]>;
  onExpand: () => void;
};

export function RouteMapMini({ pois, path, onExpand }: RouteMapMiniProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) setVisible(true);
      },
      { rootMargin: "80px", threshold: 0.05 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  const { mapError, mapReady } = useAmapRouteMap(canvasRef, pois, {
    enabled: visible,
    path,
    zoom: 13,
  });

  return (
    <div className="plan-route-mini" ref={wrapRef}>
      <div
        className="plan-route-mini-canvas-wrap"
        role="presentation"
        onClick={(e) => {
          if ((e.target as HTMLElement).closest(".plan-route-expand-btn")) return;
          if (!mapReady) onExpand();
        }}
      >
        <div ref={canvasRef} className="plan-route-mini-canvas" aria-label="行程路线预览" />
        {!mapReady && !mapError ? (
          <div className="plan-route-mini-skeleton">加载路线…</div>
        ) : null}
        <button
          type="button"
          className="plan-route-expand-btn"
          aria-label="展开完整路线"
          onClick={(e) => {
            e.stopPropagation();
            onExpand();
          }}
        >
          ⤢
        </button>
      </div>
      {mapError ? (
        <p className="plan-route-mini-fallback">地图加载失败，仍可查看下方路线列表</p>
      ) : (
          <p className="plan-route-mini-hint">点击 ⤢ 查看完整路线</p>
      )}
    </div>
  );
}
