import { useMemo, useState } from "react";
import type { ResolvedLocation } from "../location";
import { formatDistanceMeters, haversineMeters } from "../geo/distance";
import type { SessionPoi } from "../types/sessionPoi";

function displayCost(cost: string | null | undefined): string | null {
  if (cost == null) return null;
  const c = String(cost).trim();
  if (!c || c === "[]" || /^[\[\]【】\s]+$/.test(c)) return null;
  if (/待确认|到店确认|未知|暂无/i.test(c)) return null;
  return c;
}

type PoiCardProps = {
  poi: SessionPoi;
  userLocation: ResolvedLocation | null;
};

export function PoiCardSingle({ poi, userLocation }: PoiCardProps) {
  const cover = poi.photo_urls[0];
  const gallery = poi.photo_urls.length >= 2 ? poi.photo_urls.slice(1) : [];

  const distance = useMemo(() => {
    const loc = poi.location;
    if (!loc || userLocation?.lng == null || userLocation?.lat == null) return null;
    return formatDistanceMeters(
      haversineMeters(userLocation.lng, userLocation.lat, loc.lng, loc.lat),
    );
  }, [poi.location, userLocation]);

  const href = poi.amap_place_url || `https://www.amap.com/place/${poi.id}`;
  const costLabel = displayCost(poi.cost);

  return (
    <a className="poi-card" href={href} target="_blank" rel="noopener noreferrer">
      {cover ? (
        <div className="poi-card-cover">
          <img src={cover} alt="" loading="lazy" />
        </div>
      ) : null}
      <div className="poi-card-body">
        <div className="poi-card-name">{poi.name}</div>
        <div className="poi-card-meta">
          {poi.rating != null ? <span className="poi-card-rating">★ {poi.rating}</span> : null}
          {costLabel ? <span className="poi-card-cost">人均 {costLabel}</span> : null}
          {distance ? <span className="poi-card-dist">{distance}</span> : null}
        </div>
        {gallery.length > 0 ? (
          <div className="poi-card-gallery">
            {gallery.map((url) => (
              <img key={url} src={url} alt="" loading="lazy" />
            ))}
          </div>
        ) : null}
      </div>
    </a>
  );
}

type PoiCardListProps = {
  pois: SessionPoi[];
  planText: string;
  userLocation: ResolvedLocation | null;
};

function poiInPlan(poi: SessionPoi, planText: string): boolean {
  const name = poi.name.trim();
  if (!name || name.length < 2) return false;
  return planText.includes(name);
}

export function PoiCardList({ pois, planText, userLocation }: PoiCardListProps) {
  const matched = pois.filter((p) => poiInPlan(p, planText));
  const list = matched.length > 0 ? matched : pois.slice(0, 6);
  if (list.length === 0) return null;

  return (
    <div className="poi-card-list">
      {list.map((p) => (
        <PoiCardSingle key={p.id} poi={p} userLocation={userLocation} />
      ))}
    </div>
  );
}

export function PoiGallerySheet({
  poi,
  open,
  onClose,
}: {
  poi: SessionPoi | null;
  open: boolean;
  onClose: () => void;
}) {
  if (!open || !poi || poi.photo_urls.length < 2) return null;
  const extra = poi.photo_urls.slice(1);
  return (
    <div className="poi-gallery-sheet-root" role="presentation">
      <button type="button" className="poi-gallery-backdrop" aria-label="关闭" onClick={onClose} />
      <div className="poi-gallery-sheet">
        <div className="poi-gallery-head">
          <span>{poi.name}</span>
          <button type="button" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </div>
        <div className="poi-gallery-grid">
          {extra.map((url) => (
            <img key={url} src={url} alt="" loading="lazy" />
          ))}
        </div>
      </div>
    </div>
  );
}

export function usePoiGallery() {
  const [galleryPoi, setGalleryPoi] = useState<SessionPoi | null>(null);
  return {
    galleryPoi,
    galleryOpen: galleryPoi != null,
    openGallery: setGalleryPoi,
    closeGallery: () => setGalleryPoi(null),
  };
}
