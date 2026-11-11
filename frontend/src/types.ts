export type LatLng = { lat: number; lng: number };
export type TravelMode = "WALK" | "BICYCLE" | "TWO_WHEELER" | "DRIVE";
export type Preference = "cleanest_air" | "cleanest" | "balanced" | "fastest";

export interface Segment {
  path: LatLng[];
  duration_s: number;
  arrival_offset_s: number;
  pm25: number | null;
  pm10: number | null;
  no2_ppb: number | null;
  uaqi: number | null;
  aqi: number | null;
  aqi_category: string | null;
  dominant_pollutant: string | null;
  beside_green: number;
  beside_busy_road: number;
  data_kind: "current" | "forecast" | null;
}

export interface Hotspot {
  location: LatLng;
  pm25: number;
  minutes: number;
}

export interface Highlight {
  kind: "green" | "water" | "road" | "quiet" | "industrial" | "construction";
  text: string;
}

export interface RouteOut {
  id: string;
  source: "primary" | "alternative" | "detour" | "green";
  via: string | null;
  labels: string[];
  duration_s: number;
  distance_m: number;
  encoded_polyline: string;
  exposure_pm25: number | null;
  exposure_pm10: number | null;
  mean_pm25: number | null;
  peak_pm25: number | null;
  minutes_above_reference: number | null;
  delta_exposure_pct: number | null;
  extra_minutes: number;
  within_budget: boolean;
  coverage: number;
  distinct_cells: number;
  mean_aqi: number | null;
  peak_aqi: number | null;
  aqi_category: string | null;
  delta_aqi: number | null;
  minutes_green: number;
  minutes_busy_road: number;
  highlights: Highlight[];
  segments: Segment[];
  hotspots: Hotspot[];
}

export interface RouteResponse {
  plan?: PlanStatus | null;
  routes: RouteOut[];
  recommended_id: string;
  fastest_id: string;
  preference: Preference;
  max_extra_minutes: number;
  comparison: {
    meaningful: boolean;
    basis: "aqi" | "exposure";
    recommended_aqi: number | null;
    fastest_aqi: number | null;
    reduction_pct: number | null;
    extra_minutes: number;
    shared_cells_pct: number | null;
    message: string;
  };
  data: {
    provider: string;
    routes_source: string | null;
    aq_source: string | null;
    mock: boolean;
    departure_time: string;
    computed_at: string;
    oldest_observation: string | null;
    uses_forecast: boolean;
    resolution_note: string;
  };
  usage: {
    routes_calls: number;
    aq_current_calls: number;
    aq_forecast_calls: number;
    aq_cache_hits: number;
    estimated_cost_usd: number | null;
  };
  warnings: string[];
}

export interface AgentResponse {
  verdict: string;
  plan: RouteResponse | null;
}

export interface Place {
  label: string;
  location: LatLng;
}

export interface Suggestion {
  place_id: string;
  primary: string;
  secondary: string;
}

export interface AppConfig {
  provider: string;
  mock: boolean;
  data_note: string;
  region: { name: string; service_name?: string; south: number; west: number; north: number; east: number };
  default_max_extra_minutes: number;
  meaningful_diff_pct: number;
  pm25_reference_ugm3: number;
  cleanest_air_default_extra_minutes: number;
  street_context: boolean;
  maps_browser_key: string;
  map_id: string;
  google_oauth_client_id: string;
  accounts_enabled: boolean;
  plans?: PlansConfig;
  version: string;
}

export interface PlansConfig {
  enabled: boolean;
  payments: boolean;
  free_street_searches: number;
  plus_street_searches: number;
  monthly_inr: number | null;
  yearly_inr: number | null;
  razorpay_key_id: string;
}

export interface PlanStatus {
  plan: "anonymous" | "free" | "plus";
  street_level: boolean;
  used: number;
  limit: number;
  plus_until: string | null;
}

export interface Me {
  id: string;
  email: string;
  name: string;
  picture: string;
  created_at: string;
}

export interface SavedPlace {
  id: string;
  label: string;
  name: string;
  lat: number;
  lng: number;
  created_at: string;
}

export interface TripPoint {
  name: string;
  lat: number;
  lng: number;
}

export interface TripIn {
  departure_time: string;
  mode: TravelMode;
  preference: Preference;
  origin: TripPoint;
  destination: TripPoint;
  route_source: "primary" | "alternative" | "detour" | "green";
  duration_s: number;
  distance_m: number;
  exposure_pm25: number | null;
  fastest_exposure_pm25: number | null;
  fastest_duration_s: number | null;
  mean_pm25: number | null;
  data_source: string;
}

export interface TripOut extends Omit<TripIn, "mode" | "preference" | "route_source"> {
  id: string;
  created_at: string;
  mode: string;
  preference: string;
  route_source: string;
}

export interface Summary {
  trips: number;
  minutes_travelled: number;
  exposure_total: number;
  exposure_avoided: number;
  avoided_pct: number | null;
  trips_last_30_days: number;
}
