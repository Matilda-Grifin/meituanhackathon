import type { ReactNode } from "react";
import { BubbleMarkdown } from "../BubbleMarkdown";
import { splitPlanWithPois } from "../planPoiEmbed";
import { PoiCardSingle } from "./PoiCard";
import type { ResolvedLocation } from "../location";
import type { SessionPoi } from "../types/sessionPoi";

type PlanMessageBodyProps = {
  text: string;
  pois: SessionPoi[];
  userLocation: ResolvedLocation | null;
};

export function PlanMessageBody({ text, pois, userLocation }: PlanMessageBodyProps) {
  const segments = splitPlanWithPois(text, pois);
  const nodes: ReactNode[] = [];

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

  return <div className="plan-message-body">{nodes}</div>;
}
