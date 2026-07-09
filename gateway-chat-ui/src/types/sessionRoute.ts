export type RouteLegMode = "walking" | "driving" | "transit" | "taxi" | "bicycling" | "unknown";

export type SessionRouteLeg = {
  from_poi_id: string;
  to_poi_id: string;
  mode: RouteLegMode;
  distance_m: number;
  duration_s: number;
  label?: string;
  source: "plan_text" | "tool" | "estimated";
};

export type SessionRoute = {
  ordered_poi_ids: string[];
  legs: SessionRouteLeg[];
  total_distance_m: number;
  total_duration_s: number;
  path?: Array<{ lng: number; lat: number }>;
};
