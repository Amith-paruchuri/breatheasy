/**
 * "Best time to leave": the selected route, leaving now or in 30 to 120 minutes.
 * One compact row of five times; the cleanest is highlighted. Tapping a later time
 * re-plans the trip for that departure.
 */
import { useEffect, useState } from "react";
import { bestTime, type BestTimeResult } from "../api";
import { pm25Color } from "../format";
import type { RouteOut, TravelMode } from "../types";

function timedPoints(route: RouteOut, max = 60) {
  const segs = route.segments.filter((s) => s.path.length);
  const step = Math.max(1, Math.ceil(segs.length / max));
  const out = [];
  for (let i = 0; i < segs.length; i += step) {
    const group = segs.slice(i, i + step);
    const mid = group[Math.floor(group.length / 2)];
    const p = mid.path[Math.floor(mid.path.length / 2)];
    out.push({
      lat: p.lat,
      lng: p.lng,
      offset_s: group[0].arrival_offset_s,
      duration_s: group.reduce((t, g) => t + g.duration_s, 0),
    });
  }
  return out;
}

const cache = new Map<string, BestTimeResult | null>();

export function BestTime({
  route,
  mode,
  cacheKey,
  onPick,
}: {
  route: RouteOut | null | undefined;
  mode: TravelMode;
  cacheKey: string; // changes with each new search
  onPick: (offsetMin: number) => void;
}) {
  const key = route ? `${cacheKey}|${route.id}` : "";
  const [data, setData] = useState<BestTimeResult | null>(key ? (cache.get(key) ?? null) : null);

  useEffect(() => {
    if (!route || !key) return;
    if (cache.has(key)) {
      setData(cache.get(key) ?? null);
      return;
    }
    setData(null);
    const ctrl = new AbortController();
    const t = window.setTimeout(() => {
      bestTime({ mode, points: timedPoints(route) }, ctrl.signal)
        .then((r) => {
          cache.set(key, r);
          setData(r);
        })
        .catch(() => {
          if (!ctrl.signal.aborted) cache.set(key, null);
        });
    }, 400); // wait until the user settles on a route
    return () => {
      window.clearTimeout(t);
      ctrl.abort();
    };
  }, [key, route, mode]);

  if (!data || data.best_offset_min == null) return null;
  const slots = data.slots.filter((s) => s.mean_pm25 != null);
  if (slots.length < 2) return null;
  const best = data.slots.find((s) => s.offset_min === data.best_offset_min)!;
  const pct = data.cleaner_pct ?? 0;
  const msg =
    data.best_offset_min === 0 || pct < 5
      ? "Leaving now is about as clean as it gets in the next 2 hours."
      : `Leave at ${fmt(best.depart)} for about ${Math.round(pct)}% cleaner air on this route.`;

  return (
    <div className="besttime" aria-label="Best time to leave">
      <div className="bt-head">
        <span className="bt-title">Best time to leave</span>
        <span className={`bt-msg${data.best_offset_min !== 0 && pct >= 5 ? " good" : ""}`}>{msg}</span>
      </div>
      <div className="bt-row" role="list">
        {data.slots.map((s) => {
          const isBest = s.offset_min === data.best_offset_min && (s.offset_min === 0 || pct >= 5);
          return (
            <button
              key={s.offset_min}
              type="button"
              role="listitem"
              className={`bt-slot${isBest ? " best" : ""}`}
              disabled={s.mean_pm25 == null || s.offset_min === 0}
              onClick={() => onPick(s.offset_min)}
              title={s.offset_min === 0 ? "Leaving now" : `Plan this trip leaving at ${fmt(s.depart)}`}
            >
              <span className="bt-time">{s.offset_min === 0 ? "Now" : fmt(s.depart)}</span>
              <span className="bt-val" style={{ borderColor: pm25Color(s.mean_pm25) }}>
                {s.mean_pm25 == null ? "–" : Math.round(s.mean_pm25)}
              </span>
            </button>
          );
        })}
      </div>
      <span className="bt-note">Average PM2.5 (µg/m³) on this route by departure time, from the hourly forecast</span>
    </div>
  );
}

function fmt(hhmm: string) {
  const [h, m] = hhmm.split(":").map(Number);
  const d = new Date();
  d.setHours(h, m, 0, 0);
  return d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
}
