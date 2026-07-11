import { useMemo, type ReactNode } from "react";
import { orderedPlanPois } from "../orderedPlanPois";
import { BubbleMarkdown } from "../BubbleMarkdown";
import { splitPlanWithPois } from "../planPoiEmbed";
import type { ResolvedLocation } from "../location";
import type { SessionPoi } from "../types/sessionPoi";
import { RouteMapMini } from "./RouteMapMini";
import { PoiCardSingle } from "./PoiCard";

type PlanMessageBodyProps = {
  text: string;
  pois: SessionPoi[];
  userLocation: ResolvedLocation | null;
  onOpenRouteSheet?: () => void;
};

export function PlanMessageBody({
  text,
  pois,
  userLocation,
  onOpenRouteSheet,
}: PlanMessageBodyProps) {
  const segments = splitPlanWithPois(text, pois);
  const nodes: ReactNode[] = [];
  const ordered = useMemo(() => orderedPlanPois(text, pois), [text, pois]);
  const showMap = Boolean(onOpenRouteSheet) && ordered.length >= 2;

  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i]!;
    if (seg.kind === "text") {
      if (!seg.text.trim()) continue;
      nodes.push(<BubbleMarkdown key={`t-${i}`} text={seg.text} variant="app-light" />);
    } else {
      nodes.push(
        <div key={`p-${seg.poi.id}-${i}`} className="plan-inline-poi">
          <PoiCardSingle poi={seg.poi} userLocation={userLocation} />
        </div>,
      );
    }
  }

  if (showMap) {
    nodes.push(
      <RouteMapMini
        key="route-mini"
        pois={ordered}
        onExpand={() => onOpenRouteSheet?.()}
      />,
    );
  }

  return <div className="plan-message-body">{nodes}</div>;
}
