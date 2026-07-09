import type { SessionPoi } from "../types/sessionPoi";
import type { SessionRouteLeg } from "../types/sessionRoute";
import { formatRouteLegDisplay } from "../planRouteLegs";

type RouteSheetListProps = {
  pois: SessionPoi[];
  legs: SessionRouteLeg[];
  summary: string;
  activeIndex: number | null;
  onSelectStop: (index: number) => void;
};

function poiMeta(poi: SessionPoi): string {
  const parts: string[] = [];
  if (poi.rating != null) parts.push(`★ ${poi.rating}`);
  if (poi.poi_type) parts.push(poi.poi_type);
  if (poi.cost) parts.push(`人均 ${poi.cost}`);
  return parts.join(" · ");
}

export function RouteSheetList({
  pois,
  legs,
  summary,
  activeIndex,
  onSelectStop,
}: RouteSheetListProps) {
  const legByTo = new Map(legs.map((l) => [l.to_poi_id, l]));

  return (
    <div className="route-sheet-list">
      <h2 className="route-sheet-title">行程路线</h2>
      <p className="route-sheet-summary">{summary}</p>
      <div className="route-sheet-timeline">
        {pois.map((poi, i) => {
          const leg = legByTo.get(poi.id);
          const cover = poi.photo_urls[0];
          return (
            <div key={poi.id} className="route-sheet-stop-block">
              {leg ? (
                <div className="route-sheet-leg">
                  <span className="route-sheet-leg-text">{formatRouteLegDisplay(leg)}</span>
                </div>
              ) : null}
              <div className="route-sheet-item">
                <span className="route-sheet-num">{i + 1}</span>
                <button
                  type="button"
                  className={`route-sheet-card${activeIndex === i ? " active" : ""}`}
                  onClick={() => onSelectStop(i)}
                >
                  {cover ? (
                    <img className="route-sheet-thumb" src={cover} alt="" loading="lazy" />
                  ) : (
                    <div className="route-sheet-thumb route-sheet-thumb-ph" />
                  )}
                  <div className="route-sheet-card-body">
                    <div className="route-sheet-name">{poi.name}</div>
                    <div className="route-sheet-meta">{poiMeta(poi)}</div>
                  </div>
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
