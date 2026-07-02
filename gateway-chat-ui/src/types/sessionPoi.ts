export type SessionPoi = {
  id: string;
  name: string;
  amap_place_url: string;
  poi_type?: string;
  photo_urls: string[];
  location?: { lng: number; lat: number } | null;
  rating?: number | null;
  cost?: string | null;
};
