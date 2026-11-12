import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef } from "react";
import { pm25Color } from "../format";
import type { MapProps } from "./RouteMap";

/**
 * OpenStreetMap basemap for the keyless open-data provider (and demo mode).
 * Do not draw Google route data on this map: Google's terms require a Google map.
 */
export function LeafletMap({ routes, selectedId, onSelect, origin, destination, fitPadding }: MapProps) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const lastFitKey = useRef("");

  useEffect(() => {
    if (!el.current || map.current) return;
    const m = L.map(el.current, { zoomControl: false, attributionControl: true }).setView([28.6139, 77.209], 11);
    if (window.innerWidth >= 900) L.control.zoom({ position: "bottomright" }).addTo(m);
    L.tileLayer(window.matchMedia("(prefers-color-scheme: dark)").matches ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" : "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
      maxZoom: 19,
      subdomains: "abcd",
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    }).addTo(m);
    layer.current = L.layerGroup().addTo(m);
    map.current = m;
    const ro = new ResizeObserver(() => m.invalidateSize());
    ro.observe(el.current);
    return () => {
      ro.disconnect();
      m.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    const m = map.current;
    const g = layer.current;
    if (!m || !g) return;
    g.clearLayers();

    for (const r of routes) {
      if (r.id === selectedId) continue;
      const line = L.polyline(
        r.segments.flatMap((s) => s.path.map((p) => [p.lat, p.lng] as [number, number])),
        { color: "#7f8f9b", opacity: 0.6, weight: 6 },
      );
      line.on("click", () => onSelect(r.id));
      line.addTo(g);
    }

    const sel = routes.find((r) => r.id === selectedId);
    if (sel) {
      const all = sel.segments.flatMap((s) => s.path.map((p) => [p.lat, p.lng] as [number, number]));
      L.polyline(all, { color: "#0f2a3a", opacity: 0.7, weight: 12, interactive: false }).addTo(g);
      for (const s of sel.segments) {
        L.polyline(
          s.path.map((p) => [p.lat, p.lng] as [number, number]),
          { color: pm25Color(s.pm25), opacity: 1, weight: 7 },
        )
          .bindTooltip(`AQI ${s.aqi ?? "no data"} (${s.aqi_category ?? "unknown"}), ${Math.max(1, Math.round(s.duration_s / 60))} min`, { sticky: true })
          .addTo(g);
      }
      for (const h of sel.hotspots) {
        L.marker([h.location.lat, h.location.lng], {
          icon: L.divIcon({
            className: "",
            html: `<div class="spot-marker"><span>!</span>${Math.round(h.pm25)}</div>`,
            iconSize: [56, 26],
            iconAnchor: [28, 13],
          }),
          zIndexOffset: 500,
        })
          .bindTooltip(`Pollution spot: PM2.5 ${Math.round(h.pm25)} µg/m³`)
          .addTo(g);
      }
    }

    // Start: white dot with an ink ring. Destination: solid ink. Same marks as the search box.
    if (origin)
      L.circleMarker([origin.lat, origin.lng], { radius: 7, color: "#0f2a3a", weight: 3.5, fillColor: "#ffffff", fillOpacity: 1 }).addTo(g);
    if (destination)
      L.circleMarker([destination.lat, destination.lng], { radius: 9, color: "#ffffff", weight: 3, fillColor: "#0f2a3a", fillOpacity: 1 }).addTo(g);

    // Refit only when the trip changes, not when the user picks another route.
    const key = JSON.stringify([origin, destination, routes.map((r) => r.id + r.distance_m)]);
    if (key !== lastFitKey.current) {
      lastFitKey.current = key;
      const pts: [number, number][] = routes.flatMap((r) => r.segments.flatMap((s) => s.path.map((p) => [p.lat, p.lng] as [number, number])));
      for (const p of [origin, destination]) if (p) pts.push([p.lat, p.lng]);
      const pad = fitPadding ?? { top: 36, right: 36, bottom: 36, left: 36 };
      if (pts.length > 1)
        m.fitBounds(L.latLngBounds(pts), {
          paddingTopLeft: [pad.left, pad.top],
          paddingBottomRight: [pad.right, pad.bottom],
          maxZoom: 16,
        });
      else if (pts.length === 1) m.setView(pts[0], 14);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routes, selectedId, onSelect, origin, destination]);

  return <div ref={el} className="map leaflet-host" />;
}
