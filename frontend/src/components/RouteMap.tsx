import { AdvancedMarker, Circle, Map, Pin, Polyline, useMap } from "@vis.gl/react-google-maps";
import { useEffect } from "react";
import { pm25Color } from "../format";
import type { LatLng, RouteOut } from "../types";

export interface MapProps {
  routes: RouteOut[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  origin: LatLng | null;
  destination: LatLng | null;
  mapId?: string;
  fitPadding?: FitPadding;
}

export interface FitPadding {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

const DELHI = { lat: 28.6139, lng: 77.209 };
const ENV_MAP_ID = import.meta.env.VITE_GOOGLE_MAP_ID as string | undefined;

function FitBounds({ routes, origin, destination, fitPadding }: Pick<MapProps, "routes" | "origin" | "destination" | "fitPadding">) {
  const map = useMap();
  useEffect(() => {
    if (!map) return;
    const b = new google.maps.LatLngBounds();
    let n = 0;
    for (const r of routes)
      for (const s of r.segments)
        for (const p of s.path) {
          b.extend(p);
          n++;
        }
    for (const p of [origin, destination]) if (p) (b.extend(p), n++);
    if (n === 0) return;
    if (n === 1) {
      map.setCenter(b.getCenter());
      map.setZoom(14);
      return;
    }
    map.fitBounds(b, fitPadding ?? 60);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, routes, origin, destination]);
  return null;
}

export function RouteMap({ routes, selectedId, onSelect, origin, destination, mapId, fitPadding }: MapProps) {
  const selected = routes.find((r) => r.id === selectedId) ?? null;
  return (
    <Map
      className="map"
      mapId={mapId || ENV_MAP_ID || "DEMO_MAP_ID"}
      defaultCenter={DELHI}
      defaultZoom={11}
      gestureHandling="greedy"
      disableDefaultUI
      zoomControl={window.innerWidth >= 900}
      colorScheme={window.matchMedia("(prefers-color-scheme: dark)").matches ? "DARK" : "LIGHT"}
      clickableIcons={false}
    >
      <FitBounds routes={routes} origin={origin} destination={destination} fitPadding={fitPadding} />

      {routes
        .filter((r) => r.id !== selectedId)
        .map((r) => (
          <Polyline
            key={r.id}
            encodedPath={r.encoded_polyline}
            strokeColor="#7f8f9b"
            strokeOpacity={0.55}
            strokeWeight={5}
            zIndex={1}
            onClick={() => onSelect(r.id)}
          />
        ))}

      {selected && (
        <>
          <Polyline encodedPath={selected.encoded_polyline} strokeColor="#0f2a3a" strokeOpacity={0.7} strokeWeight={12} zIndex={2} />
          {selected.segments.map((s, i) => (
            <Polyline key={`${selected.id}-${i}`} path={s.path} strokeColor={pm25Color(s.pm25)} strokeOpacity={1} strokeWeight={7} zIndex={3} />
          ))}
          {selected.hotspots.map((h, i) => (
            <Circle
              key={`h-${i}`}
              center={h.location}
              radius={180}
              strokeColor="#8e1f3d"
              strokeWeight={2}
              fillColor="#d9452f"
              fillOpacity={0.18}
              zIndex={4}
            />
          ))}
        </>
      )}

      {origin && (
        <AdvancedMarker position={origin} title="Start">
          <Pin background="#ffffff" borderColor="#0f2a3a" glyphColor="#0f2a3a" scale={0.9} />
        </AdvancedMarker>
      )}
      {destination && (
        <AdvancedMarker position={destination} title="Destination">
          <Pin background="#0f2a3a" borderColor="#ffffff" glyphColor="#ffffff" />
        </AdvancedMarker>
      )}
    </Map>
  );
}
