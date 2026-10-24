import { useMemo } from "react";
import { aqiColor } from "../format";
import type { MapProps } from "./RouteMap";

/**
 * Used when no Maps JavaScript API key is configured (e.g. mock mode).
 * A plain projection of the routes, not a map. Never use it to display Google
 * route data in production: Google's terms require a Google map for that.
 */
export function SchematicMap({ routes, selectedId, onSelect, origin, destination }: MapProps) {
  const W = 1000;
  const H = 1000;
  const proj = useMemo(() => {
    const pts = routes.flatMap((r) => r.segments.flatMap((s) => s.path));
    if (origin) pts.push(origin);
    if (destination) pts.push(destination);
    if (!pts.length) return null;
    let s = Math.min(...pts.map((p) => p.lat));
    let n = Math.max(...pts.map((p) => p.lat));
    let w = Math.min(...pts.map((p) => p.lng));
    let e = Math.max(...pts.map((p) => p.lng));
    const k = Math.cos(((s + n) / 2) * (Math.PI / 180));
    const spanX = Math.max((e - w) * k, 0.005);
    const spanY = Math.max(n - s, 0.005);
    const span = Math.max(spanX, spanY) * 1.18;
    const cx = ((w + e) / 2) * k;
    const cy = (s + n) / 2;
    return (p: { lat: number; lng: number }) => [
      ((p.lng * k - cx) / span + 0.5) * W,
      (0.5 - (p.lat - cy) / span) * H,
    ];
  }, [routes, origin, destination]);

  const selected = routes.find((r) => r.id === selectedId);

  if (!proj) {
    return (
      <div className="map schematic empty">
        <p>Pick a start and destination to see routes.</p>
      </div>
    );
  }
  const line = (path: { lat: number; lng: number }[]) => path.map((p) => proj(p).join(",")).join(" ");

  return (
    <div className="map schematic">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label="Schematic route preview">
        <defs>
          <pattern id="grid" width="50" height="50" patternUnits="userSpaceOnUse">
            <path d="M50 0H0V50" fill="none" stroke="var(--grid)" strokeWidth="1" />
          </pattern>
        </defs>
        <rect width={W} height={H} fill="url(#grid)" />
        {routes
          .filter((r) => r.id !== selectedId)
          .map((r) => (
            <polyline
              key={r.id}
              points={line(r.segments.flatMap((s) => s.path))}
              fill="none"
              stroke="var(--route-muted)"
              strokeWidth={9}
              strokeLinejoin="round"
              strokeLinecap="round"
              style={{ cursor: "pointer" }}
              onClick={() => onSelect(r.id)}
            />
          ))}
        {selected && (
          <>
            <polyline
              points={line(selected.segments.flatMap((s) => s.path))}
              fill="none"
              stroke="var(--ink)"
              strokeOpacity={0.6}
              strokeWidth={20}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            {selected.segments.map((s, i) => (
              <polyline
                key={i}
                points={line(s.path)}
                fill="none"
                stroke={aqiColor(s.aqi)}
                strokeWidth={12}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            ))}
            {selected.hotspots.map((h, i) => {
              const [x, y] = proj(h.location);
              return <circle key={i} cx={x} cy={y} r={30} fill="#d9452f" fillOpacity={0.18} stroke="#8e1f3d" strokeWidth={3} />;
            })}
          </>
        )}
        {origin && (() => {
          const [x, y] = proj(origin);
          return <circle cx={x} cy={y} r={16} fill="var(--ink)" stroke="var(--surface)" strokeWidth={5} />;
        })()}
        {destination && (() => {
          const [x, y] = proj(destination);
          return <circle cx={x} cy={y} r={18} fill="var(--accent)" stroke="var(--surface)" strokeWidth={5} />;
        })()}
      </svg>
      <span className="schematic-tag">Schematic preview · add a Maps key for the real map</span>
    </div>
  );
}
