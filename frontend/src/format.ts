import type { LatLng, RouteOut, TravelMode } from "./types";

/** India's National AQI (CPCB) categories. Colours follow CPCB's green-to-maroon order,
 * adjusted so each step also differs in lightness (readable for colour-blind users). */
export const AQI_BANDS = [
  { max: 50, label: "Good", color: "#2f9e5b" },
  { max: 100, label: "Satisfactory", color: "#8bbf3c" },
  { max: 200, label: "Moderate", color: "#e9b824" },
  { max: 300, label: "Poor", color: "#ec8a2c" },
  { max: 400, label: "Very poor", color: "#d9452f" },
  { max: Infinity, label: "Severe", color: "#8e1f3d" },
];

export function aqiColor(v: number | null | undefined): string {
  if (v == null) return "#9aa3a8";
  return (AQI_BANDS.find((b) => v <= b.max) ?? AQI_BANDS[AQI_BANDS.length - 1]).color;
}

export function aqiLabel(v: number | null | undefined): string {
  if (v == null) return "No data";
  return (AQI_BANDS.find((b) => v <= b.max) ?? AQI_BANDS[AQI_BANDS.length - 1]).label;
}

/** Text colour that stays readable on an AQI swatch. */
export function aqiInk(v: number | null | undefined): string {
  return v != null && v > 50 && v <= 300 ? "#1d1a06" : "#ffffff";
}

export function fmtDuration(s: number): string {
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

export function fmtDistance(m: number): string {
  return m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(m < 10000 ? 1 : 0)} km`;
}

export function fmtTime(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
}

export const MODE_LABEL: Record<TravelMode, string> = {
  WALK: "Walk",
  BICYCLE: "Cycle",
  TWO_WHEELER: "Two-wheeler",
  DRIVE: "Car",
};

const GMAPS_MODE: Record<TravelMode, string> = {
  WALK: "walking",
  BICYCLE: "bicycling",
  TWO_WHEELER: "two-wheeler",
  DRIVE: "driving",
};

/**
 * Hand the chosen route to Google Maps for turn-by-turn navigation. A few points
 * along our route are passed as waypoints so Google Maps follows the same corridor.
 */
export function googleMapsUrl(route: RouteOut, origin: LatLng, dest: LatLng, mode: TravelMode): string {
  const pts = route.segments.map((s) => s.path[Math.floor(s.path.length / 2)]);
  const picks: LatLng[] = [];
  if (pts.length > 4) {
    for (const f of [0.25, 0.5, 0.75]) picks.push(pts[Math.floor(pts.length * f)]);
  }
  const ll = (p: LatLng) => `${p.lat.toFixed(5)},${p.lng.toFixed(5)}`;
  const params = new URLSearchParams({
    api: "1",
    origin: ll(origin),
    destination: ll(dest),
    travelmode: GMAPS_MODE[mode],
  });
  if (picks.length) params.set("waypoints", picks.map(ll).join("|"));
  return `https://www.google.com/maps/dir/?${params.toString()}`;
}

export function sourceLabel(r: RouteOut): string {
  if (r.source === "green") return r.via ? `Via ${r.via}` : "Through green space";
  if (r.source === "primary") return "Main route";
  if (r.source === "alternative") return "Alternative route";
  return "Side-street route";
}
