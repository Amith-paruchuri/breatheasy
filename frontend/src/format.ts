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

/** Google Maps accepts 3 stops in a phone browser, up to 9 elsewhere (we use 8). */
function maxWaypoints(): number {
  if (typeof navigator === "undefined") return 3;
  const phone = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
  return phone ? 3 : 8;
}

/**
 * Points that make Google Maps follow this route rather than its own choice.
 * The route is cut into equal stretches, one pin per stretch, so the whole trip is
 * held in place (not just the part that differs from the fastest route). Within a
 * stretch, the pin goes where our path strays furthest from the fastest route, which
 * is where Google would otherwise cut across; if it doesn't stray, the stretch's
 * midpoint is used. Pins are vertices of our own path, so they sit on a road.
 */
export function routeWaypoints(
  route: RouteOut,
  fastest: RouteOut | null,
  mode: TravelMode,
  max: number = maxWaypoints(),
): LatLng[] {
  const path = route.segments.flatMap((s) => s.path);
  if (path.length < 3 || max < 1) return [];
  const base = fastest && fastest.id !== route.id ? fastest.segments.flatMap((s) => s.path) : [];
  const thr = DEVIATE_M[mode];
  const cum: number[] = [0];
  for (let i = 1; i < path.length; i++) cum.push(cum[i - 1] + distM(path[i - 1], path[i]));
  const total = cum[cum.length - 1];
  if (total < 800) return []; // short trips: Google takes the same way anyway
  // ~one pin per 1.5 km, never more than the platform allows
  const n = Math.max(1, Math.min(max, Math.round(total / 1500)));
  const edge = Math.min(250, total * 0.05); // keep pins off the very start and end
  const out: LatLng[] = [];
  for (let k = 0; k < n; k++) {
    const lo = Math.max(edge, (total * k) / n);
    const hi = Math.min(total - edge, (total * (k + 1)) / n);
    const mid = (lo + hi) / 2;
    let pick = -1;
    let bestDev = thr;
    let bestMid = Infinity;
    let midIdx = -1;
    for (let i = 1; i < path.length - 1; i++) {
      if (cum[i] < lo || cum[i] > hi) continue;
      if (base.length > 1) {
        const d = distToLine(path[i], base);
        if (d > bestDev) {
          bestDev = d;
          pick = i;
        }
      }
      const m = Math.abs(cum[i] - mid);
      if (m < bestMid) {
        bestMid = m;
        midIdx = i;
      }
    }
    const idx = pick >= 0 ? pick : midIdx;
    if (idx >= 0) out.push(path[idx]);
  }
  return out;
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


/** Minutes of a route spent above a PM2.5 level (µg/m³). */
export function minutesAbove(route: RouteOut, level: number): number {
  return route.segments.reduce((m, s) => m + (s.pm25 != null && s.pm25 > level ? s.duration_s / 60 : 0), 0);
}

/**
 * The PM2.5 level to count "minutes in bad air" against, on India's CPCB bands
 * (above 90 poor, above 120 very poor, above 250 severe). On a very smoggy day every
 * route spends nearly all its time above 90, which tells you nothing, so we step up
 * to the first band the fastest route spends at most 70% of its time above.
 */
export const BAD_AIR_BANDS: { level: number; label: string }[] = [
  { level: 90, label: "poor air" },
  { level: 120, label: "very poor air" },
  { level: 250, label: "severe air" },
];
export function badAirBand(fastest: RouteOut | null): { level: number; label: string } {
  if (!fastest || fastest.duration_s <= 0) return BAD_AIR_BANDS[0];
  const total = fastest.duration_s / 60;
  return BAD_AIR_BANDS.find((b) => minutesAbove(fastest, b.level) <= total * 0.7) ?? BAD_AIR_BANDS[BAD_AIR_BANDS.length - 1];
}
