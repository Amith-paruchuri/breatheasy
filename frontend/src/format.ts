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

/** PM2.5 (µg/m³) colour scale for the map and the route ribbons. Follows CPCB's PM2.5
 * breakpoints (30 / 60 / 90 / 120 / 250) and splits the wide "very poor" band, where
 * Delhi spends much of the winter, into three shades so differences along a route show. */
export const PM25_BANDS = [
  { max: 30, label: "Good", color: "#2f9e5b" },
  { max: 60, label: "Satisfactory", color: "#8bbf3c" },
  { max: 90, label: "Moderate", color: "#e9b824" },
  { max: 120, label: "Poor", color: "#ec8a2c" },
  { max: 150, label: "Very poor", color: "#e2642c" },
  { max: 200, label: "Very poor", color: "#d23a2f" },
  { max: 250, label: "Very poor", color: "#b02838" },
  { max: Infinity, label: "Severe", color: "#7e1838" },
];
/** India's 24-hour safe limit for PM2.5 (NAAQS), µg/m³. WHO's guideline is 15. */
export const PM25_SAFE_LIMIT = 60;

export function pm25Color(v: number | null | undefined): string {
  if (v == null) return "#9aa3a8";
  return (PM25_BANDS.find((b) => v <= b.max) ?? PM25_BANDS[PM25_BANDS.length - 1]).color;
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

/** Equirectangular distance in metres; plenty accurate within a city. */
function distM(a: LatLng, b: LatLng): number {
  const kx = 111320 * Math.cos((a.lat * Math.PI) / 180);
  return Math.hypot((a.lng - b.lng) * kx, (a.lat - b.lat) * 110574);
}

/** Distance from p to the nearest point on polyline `line` (metres). */
function distToLine(p: LatLng, line: LatLng[]): number {
  const kx = 111320 * Math.cos((p.lat * Math.PI) / 180);
  const X = (q: LatLng) => [(q.lng - p.lng) * kx, (q.lat - p.lat) * 110574];
  let best = Infinity;
  for (let i = 1; i < line.length; i++) {
    const [ax, ay] = X(line[i - 1]);
    const [bx, by] = X(line[i]);
    const dx = bx - ax;
    const dy = by - ay;
    const L = dx * dx + dy * dy;
    const t = L > 0 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / L)) : 0;
    best = Math.min(best, Math.hypot(ax + t * dx, ay + t * dy));
  }
  return line.length === 1 ? distM(p, line[0]) : best;
}

const DEVIATE_M: Record<TravelMode, number> = { WALK: 40, BICYCLE: 60, TWO_WHEELER: 90, DRIVE: 90 };

/**
 * Points that make Google Maps follow this route rather than its own fastest one.
 * Where the route leaves the fastest route, we pin the point that strays furthest
 * (a vertex of our own path, so it sits on a road). Google Maps accepts up to 3
 * waypoints on phones, so the 3 biggest departures are kept, in travel order.
 */
export function routeWaypoints(route: RouteOut, fastest: RouteOut | null, mode: TravelMode): LatLng[] {
  if (!fastest || fastest.id === route.id) return [];
  const path = route.segments.flatMap((s) => s.path);
  const base = fastest.segments.flatMap((s) => s.path);
  if (path.length < 3 || base.length < 2) return [];
  const thr = DEVIATE_M[mode];
  const total = path.reduce((a, p, i) => (i ? a + distM(path[i - 1], p) : 0), 0);
  // keep waypoints off the very start and end, where Google snaps the trip anyway
  const edge = Math.min(150, total * 0.05);
  let along = 0;
  const runs: { idx: number; d: number }[] = [];
  let cur: { idx: number; d: number } | null = null;
  for (let i = 0; i < path.length; i++) {
    const p = path[i];
    if (i) along += distM(path[i - 1], p);
    const d = along < edge || total - along < edge ? 0 : distToLine(p, base);
    if (d > thr) {
      if (!cur || d > cur.d) cur = { idx: i, d };
    } else if (cur) {
      runs.push(cur);
      cur = null;
    }
  }
  if (cur) runs.push(cur);
  return runs
    .sort((a, b) => b.d - a.d)
    .slice(0, 3)
    .sort((a, b) => a.idx - b.idx)
    .map((r) => path[r.idx]);
}

/** Hand the chosen route to Google Maps, pinned so it follows the same streets. */
export function googleMapsUrl(
  route: RouteOut,
  fastest: RouteOut | null,
  origin: LatLng,
  dest: LatLng,
  mode: TravelMode,
): string {
  const ll = (p: LatLng) => `${p.lat.toFixed(6)},${p.lng.toFixed(6)}`;
  const params = new URLSearchParams({
    api: "1",
    origin: ll(origin),
    destination: ll(dest),
    travelmode: GMAPS_MODE[mode],
  });
  const wps = routeWaypoints(route, fastest, mode);
  if (wps.length) params.set("waypoints", wps.map(ll).join("|"));
  return `https://www.google.com/maps/dir/?${params.toString()}`;
}

export function sourceLabel(r: RouteOut): string {
  if (r.source === "green") return r.via ? `Via ${r.via}` : "Through green space";
  if (r.source === "primary") return "Main route";
  if (r.source === "alternative") return "Alternative route";
  return "Side-street route";
}
