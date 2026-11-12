import {
  aqiColor,
  aqiInk,
  pm25Color,
  aqiLabel,
  fmtDistance,
  fmtDuration,
  sourceLabel,
} from "../format";
import type { Highlight, RouteOut } from "../types";
import { Icon } from "./Icon";

/** PM2.5 along the journey: colour at each point is the air there, laid out by
 * minutes travelled, blended so it reads as one continuous ribbon. */
export function AirRibbon({
  route,
  ghost = false,
  scaleTo,
}: {
  route: RouteOut;
  ghost?: boolean;
  scaleTo?: number;
}) {
  const total = route.segments.reduce((a, s) => a + s.duration_s, 0) || 1;
  const width = scaleTo ? Math.min(100, (total / scaleTo) * 100) : 100;
  let t = 0;
  const stops: string[] = [];
  for (const s of route.segments) {
    const mid = ((t + s.duration_s / 2) / total) * 100;
    stops.push(`${pm25Color(s.pm25)} ${mid.toFixed(1)}%`);
    t += s.duration_s;
  }
  const bg =
    stops.length > 1
      ? `linear-gradient(90deg, ${stops.join(", ")})`
      : pm25Color(route.segments[0]?.pm25 ?? null);
  return (
    <div
      className={`ribbon${ghost ? " ghost" : ""}`}
      style={{ width: `${width}%`, background: bg }}
      role="img"
      aria-label={`PM2.5 along this route: average ${route.mean_pm25 ?? "unknown"} µg/m³, worst ${route.peak_pm25 ?? "unknown"}`}
    />
  );
}

const HL_ICON: Record<Highlight["kind"], string> = {
  green: "leaf",
  water: "drop",
  road: "road",
  quiet: "check",
  industrial: "factory",
  construction: "cone",
};

interface Props {
  route: RouteOut;
  fastestRoute: RouteOut | null;
  selected: boolean;
  recommended: boolean;
  fastest: boolean;
  departure: string;
  onSelect: () => void;
  navigateUrl: string;
  onNavigate?: () => void;
  navigateHint?: string;
  compact?: boolean; // phones: tighter spacing
  onShare?: () => void;
}

function arrival(departure: string, seconds: number) {
  const t = new Date(new Date(departure).getTime() + seconds * 1000);
  return t.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
}

export function RouteCard({
  route,
  fastestRoute,
  selected,
  recommended,
  fastest,
  departure,
  onSelect,
  navigateUrl,
  onNavigate,
  navigateHint,
  compact = false,
  onShare,
}: Props) {
  const pm = route.mean_pm25 != null ? Math.round(route.mean_pm25) : null;
  const aqi = route.mean_aqi;
  const spots = route.hotspots;
  const worst = spots.length ? Math.round(Math.max(...spots.map((h) => h.pm25))) : null;
  const fpm = fastestRoute?.mean_pm25 != null ? Math.round(fastestRoute.mean_pm25) : null;
  const vsFastest =
    fastest || pm == null || fpm == null
      ? null
      : Math.abs(pm - fpm) < 2
        ? "About the same air as the fastest route"
        : pm < fpm
          ? `${fpm - pm} µg/m³ cleaner than the fastest route`
          : `${pm - fpm} µg/m³ dirtier than the fastest route`;
  const vsCls = vsFastest && pm != null && fpm != null && Math.abs(pm - fpm) >= 2 ? (pm < fpm ? " better" : " worse") : "";

  return (
    <article
      className={`rcard rcard2${compact ? " is-compact" : ""}${selected ? " is-selected" : ""}${recommended ? " is-rec" : ""}${route.within_budget ? "" : " is-over"}`}
      onClick={onSelect}
      aria-pressed={selected}
      role="button"
      tabIndex={0}
      onKeyDown={(e) =>
        (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect())
      }
    >
      <header className="rcard-top">
        {recommended ? (
          <span className="tag tag-rec">Recommended</span>
        ) : fastest ? (
          <span className="tag">Fastest</span>
        ) : (
          <span className="rcard-src">{sourceLabel(route)}</span>
        )}
        {!route.within_budget && <span className="rcard-src">Longer than your limit</span>}
      </header>

      <div className="rcard-time">
        <strong>{fmtDuration(route.duration_s)}</strong>
        <span>
          Arrive {arrival(departure, route.duration_s)} · {fmtDistance(route.distance_m)}
          {route.extra_minutes > 0.5 && <> · +{Math.round(route.extra_minutes)} min</>}
        </span>
      </div>

      {vsFastest && <p className={`vs-fast${vsCls}`}>{vsFastest}</p>}

      <div className="air-boxes">
        <div
          className="air-box"
          style={{ background: pm25Color(route.mean_pm25), color: pm != null && pm > 120 ? "#fff" : "#1b1b1b" }}
        >
          <b>{pm ?? "–"}</b>
          <span>Avg PM2.5 · µg/m³</span>
        </div>
        <div className="air-box" style={{ background: aqiColor(aqi), color: aqiInk(aqi) }}>
          <b>{aqi ?? "–"}</b>
          <span>Avg AQI · {aqiLabel(aqi)}</span>
        </div>
      </div>

      {route.highlights.length > 0 && (
        <div className="passes">
          <span className="passes-title">You pass through</span>
          <ul className="highlights">
            {route.highlights.slice(0, 3).map((h, i) => (
              <li key={i} className={`hl hl-${h.kind}`}>
                <Icon name={HL_ICON[h.kind]} size={17} />
                <span>{h.text}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {selected && worst != null && (
        <p className="spots">
          <span className="spot-dot" aria-hidden />
          {spots.length} pollution spot{spots.length === 1 ? "" : "s"} on the way, worst {worst} µg/m³ (marked on the map)
        </p>
      )}
      {selected && route.coverage < 0.9 && (
        <p className="rcard-note">Air-quality data covered {Math.round(route.coverage * 100)}% of this route.</p>
      )}

      {selected && (
        <div className="rcard-go">
          <a
            className="btn-primary"
            href={navigateUrl}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => {
              e.stopPropagation();
              onNavigate?.();
            }}
          >
            <Icon name="navigate" size={18} />
            Start in Google Maps
          </a>
          {onShare && (
            <button
              type="button"
              className="btn-share"
              onClick={(e) => {
                e.stopPropagation();
                onShare();
              }}
              aria-label="Share this route"
            >
              <Icon name="share" size={18} />
              Share
            </button>
          )}
          {navigateHint && <p className="rcard-hint">{navigateHint}</p>}
        </div>
      )}
    </article>
  );
}

export function RouteCardSkeleton() {
  return (
    <div className="rcard skeleton" aria-hidden>
      <span className="sk sk-tag" />
      <span className="sk sk-time" />
      <span className="sk sk-line" />
      <span className="sk sk-ribbon" />
    </div>
  );
}
