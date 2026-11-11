import { useState } from "react";
import {
  aqiColor,
  pm25Color,
  PM25_SAFE_LIMIT,
  aqiInk,
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
  compact?: boolean; // phones: the essentials first, details on demand
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
}: Props) {
  const [showDetails, setShowDetails] = useState(false);
  const details = !compact || showDetails;
  const d = route.delta_aqi;
  const compare = fastest
    ? "Fastest route"
    : d == null
      ? "Air quality unknown"
      : Math.abs(d) < 3
        ? "Similar air to the fastest route"
        : d < 0
          ? `AQI ${Math.abs(d)} lower than the fastest route`
          : `AQI ${d} higher than the fastest route`;
  const pms = route.segments.map((x) => x.pm25).filter((v): v is number => v != null);
  const lo = pms.length ? Math.round(Math.min(...pms)) : null;
  const hi = pms.length ? Math.round(Math.max(...pms)) : null;
  const pmRange = lo == null ? null : lo === hi ? `${lo}` : `${lo}–${hi}`;
  const scaleTo = Math.max(route.duration_s, fastestRoute?.duration_s ?? 0);
  const longer =
    !fastest &&
    route.delta_exposure_pct != null &&
    route.delta_exposure_pct > 5 &&
    d != null &&
    d < -2;

  return (
    <article
      className={`rcard${compact ? " is-compact" : ""}${selected ? " is-selected" : ""}${recommended ? " is-rec" : ""}${route.within_budget ? "" : " is-over"}`}
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
        {!route.within_budget && (
          <span className="rcard-src">Longer than your limit</span>
        )}
      </header>

      <div className="rcard-head">
        <div className="rcard-time">
          <strong>{fmtDuration(route.duration_s)}</strong>
          {compact && !showDetails ? (
            <span className="rcard-meta-1">
              {fmtDistance(route.distance_m)}
              {route.extra_minutes > 0.5 && (
                <> · +{Math.round(route.extra_minutes)} min</>
              )}{" "}
              · arrive {arrival(departure, route.duration_s)}
            </span>
          ) : (
            <span>
              Arrive {arrival(departure, route.duration_s)}
              <i aria-hidden className="sep" />
              {fmtDistance(route.distance_m)}
              {route.extra_minutes > 0.5 && (
                <>
                  <i aria-hidden className="sep" />+
                  {Math.round(route.extra_minutes)} min
                </>
              )}
            </span>
          )}
        </div>
        <div
          className="aqi-chip"
          style={{
            background: aqiColor(route.mean_aqi),
            color: aqiInk(route.mean_aqi),
          }}
          aria-label={`Average AQI ${route.mean_aqi ?? "unknown"}, ${aqiLabel(route.mean_aqi)}`}
        >
          <b>{route.mean_aqi ?? "–"}</b>
          <span>{compact ? aqiLabel(route.mean_aqi) : "AQI"}</span>
        </div>
      </div>

      <p
        className={`rcard-compare${d != null && d <= -3 ? " better" : d != null && d >= 3 ? " worse" : ""}`}
      >
        {compare}
        {!compact && (
          <span className="rcard-cat">
            Average air: {aqiLabel(route.mean_aqi).toLowerCase()}
          </span>
        )}
      </p>

      <div className="ribbons">
        <AirRibbon route={route} scaleTo={scaleTo} />
        {pmRange && (
          <p className="rcard-pm">
            PM2.5 {pmRange} µg/m³
            {route.mean_pm25 != null && route.mean_pm25 > PM25_SAFE_LIMIT && (
              <span> · {(route.mean_pm25 / PM25_SAFE_LIMIT).toFixed(1)}× safe limit</span>
            )}
          </p>
        )}
        {!fastest && fastestRoute && selected && details && (
          <div className="ribbon-row">
            <AirRibbon route={fastestRoute} ghost scaleTo={scaleTo} />
            <span className="ribbon-cap">Fastest route, for comparison</span>
          </div>
        )}
      </div>

      {route.highlights.length > 0 && (
        <ul className="highlights">
          {route.highlights.slice(0, details ? 5 : 2).map((h, i) => (
            <li key={i} className={`hl hl-${h.kind}`}>
              <Icon name={HL_ICON[h.kind]} size={17} />
              <span>{h.text}</span>
            </li>
          ))}
        </ul>
      )}

      {selected && details && (
        <dl className="rcard-stats">
          <div>
            <dt>Worst stretch</dt>
            <dd>
              AQI {route.peak_aqi ?? "–"}{" "}
              <span>{aqiLabel(route.peak_aqi)}</span>
            </dd>
          </div>
          <div>
            <dt>Average PM2.5</dt>
            <dd>
              {route.mean_pm25 ?? "–"} µg/m³ <span>Fine particles</span>
            </dd>
          </div>
        </dl>
      )}

      {selected && longer && details && (
        <p className="rcard-note">
          Cleaner air, but you're outside about{" "}
          {Math.round(route.extra_minutes)} min longer, so total exposure is ~
          {Math.round(route.delta_exposure_pct!)}% higher. Great for a run or
          walk; for a commute, compare with Balanced.
        </p>
      )}
      {route.coverage < 0.999 && details && (
        <p className="rcard-note">
          Air-quality data covered {Math.round(route.coverage * 100)}% of this
          route.
        </p>
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
          {details && (
            <p className="rcard-hint">
              Google Maps follows these same streets, using a few pins it shows as stops (just pass through them). Its time can differ by a few minutes because it uses live traffic.
              {navigateHint ? ` ${navigateHint}` : ""}
            </p>
          )}
        </div>
      )}
      {compact && (
        <button
          type="button"
          className="rcard-more"
          aria-expanded={showDetails}
          onClick={(e) => {
            e.stopPropagation();
            setShowDetails((v) => !v);
          }}
        >
          {showDetails ? "Fewer details" : "More details"}
        </button>
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
