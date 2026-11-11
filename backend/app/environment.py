"""Street-level surroundings of a route, from OpenStreetMap.

The air-quality models are gridded (Google ~500 m, Open-Meteo much coarser), so
they cannot see what is right beside the path: a park, a lake, a six-lane road,
an industrial estate. This layer adds that context from a pre-built extract of
OpenStreetMap (scripts/build_environment.py, run once at deploy time):

- green: parks, gardens, nature reserves, forests, woods
- water: lakes, ponds, wetlands, river banks
- road: motorway / trunk / primary roads (busy traffic)
- industrial: industrial land use
- construction: land mapped as under construction (often out of date)

It is used three ways:
1. route descriptions ("Passes Lodhi Garden; 6 min along Ring Road"),
2. a small, configurable street-level adjustment to modelled concentrations
   (busy roads up, green space slightly down), and
3. finding extra candidate routes that pass parks and lakes near the trip.

Map data © OpenStreetMap contributors, available under the ODbL.
"""

from __future__ import annotations

import gzip
import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

from .geo import Point, haversine_m

log = logging.getLogger("breatheasy.env")

CELL_DEG = 0.003  # ~330 m grid for the spatial index
_M_PER_DEG_LAT = 110_574.0

# Distance thresholds (metres) for "beside" a feature
NEAR = {"green": 50.0, "water": 60.0, "road": 25.0, "industrial": 100.0, "construction": 120.0}


@dataclass
class Area:
    id: int
    kind: str  # green | water | industrial | construction
    name: str
    area_m2: float
    rings: list[list[Point]]
    bbox: tuple[float, float, float, float]  # s, w, n, e
    id_index: int = -1


@dataclass
class Road:
    id: int
    name: str
    cls: str
    pts: list[Point]


@dataclass
class SegmentContext:
    frac_green: float = 0.0  # share of the segment beside green space or water
    frac_road: float = 0.0  # share beside a busy road


@dataclass
class RouteContext:
    minutes_green: float = 0.0
    minutes_water: float = 0.0
    minutes_busy_road: float = 0.0
    total_minutes: float = 0.0
    green_by_name: dict[str, float] = field(default_factory=dict)
    water_by_name: dict[str, float] = field(default_factory=dict)
    roads_by_name: dict[str, float] = field(default_factory=dict)
    industrial: set[str] = field(default_factory=set)
    construction: int = 0


class _Proj:
    """Local equirectangular projection in metres, good to <0.5% across a city."""

    def __init__(self, lat0: float):
        self.kx = _M_PER_DEG_LAT * math.cos(math.radians(lat0))

    def xy(self, p: Point) -> tuple[float, float]:
        return p[1] * self.kx, p[0] * _M_PER_DEG_LAT


def _seg_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    qx, qy = ax + t * dx, ay + t * dy
    return math.hypot(px - qx, py - qy)


def _inside(p: Point, ring: list[Point]) -> bool:
    lat, lng = p
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        yi, xi = ring[i]
        yj, xj = ring[j]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _cells(s: float, w: float, n: float, e: float):
    for i in range(math.floor(s / CELL_DEG), math.floor(n / CELL_DEG) + 1):
        for j in range(math.floor(w / CELL_DEG), math.floor(e / CELL_DEG) + 1):
            yield (i, j)


class EnvironmentLayer:
    def __init__(self, areas: list[Area], roads: list[Road], source: str = ""):
        self.areas = areas
        self.roads = roads
        for k, a in enumerate(areas):
            a.id_index = k
        self.source = source
        lat0 = (sum(a.bbox[0] for a in areas) / len(areas)) if areas else 28.6
        self.proj = _Proj(lat0)
        self._area_idx: dict[tuple[int, int], list[int]] = {}
        self._road_idx: dict[tuple[int, int], list[tuple[int, int]]] = {}
        # Pre-project geometry to metres once, so point queries are cheap.
        self._area_xy = [[[self.proj.xy(q) for q in ring] for ring in a.rings] for a in areas]
        self._road_xy = [[self.proj.xy(q) for q in r.pts] for r in roads]
        pad = 150 / _M_PER_DEG_LAT
        for k, a in enumerate(areas):
            s, w, n, e = a.bbox
            for c in _cells(s - pad, w - pad, n + pad, e + pad):
                self._area_idx.setdefault(c, []).append(k)
        for k, r in enumerate(roads):
            for i in range(len(r.pts) - 1):
                (a_lat, a_lng), (b_lat, b_lng) = r.pts[i], r.pts[i + 1]
                for c in _cells(min(a_lat, b_lat), min(a_lng, b_lng), max(a_lat, b_lat), max(a_lng, b_lng)):
                    self._road_idx.setdefault(c, []).append((k, i))

    @property
    def empty(self) -> bool:
        return not self.areas and not self.roads

    def at(self, p: Point) -> "EnvironmentLayer":
        return self

    @property
    def cities(self) -> list[str]:
        return [] if self.empty else ["Delhi-NCR"]

    # ---------- loading ----------
    @staticmethod
    def _parse(data: dict) -> tuple[list[Area], list[Road]]:
        areas = []
        for i, a in enumerate(data.get("areas", [])):
            rings = [[(pt[0], pt[1]) for pt in ring] for ring in a["rings"] if len(ring) >= 3]
            if not rings:
                continue
            lats = [pt[0] for ring in rings for pt in ring]
            lngs = [pt[1] for ring in rings for pt in ring]
            areas.append(Area(i, a["kind"], a.get("name", ""), float(a.get("area_m2", 0)), rings,
                              (min(lats), min(lngs), max(lats), max(lngs))))
        roads = [
            Road(i, r.get("name", ""), r.get("cls", ""), [(pt[0], pt[1]) for pt in r["pts"]])
            for i, r in enumerate(data.get("roads", []))
            if len(r.get("pts", [])) >= 2
        ]
        return areas, roads

    @classmethod
    def load(cls, path: str | Path):
        """One city (version 1 file) or several (version 2: {"cities": [...]})."""
        p = Path(path)
        if not p.is_file():
            log.info("environment layer not found at %s; street-level context is off", p)
            return cls([], [])
        opener = gzip.open if p.suffix == ".gz" else open
        with opener(p, "rt", encoding="utf-8") as f:
            data = json.load(f)
        source = data.get("source", "© OpenStreetMap contributors")
        if "cities" in data:
            layers = []
            for c in data["cities"]:
                areas, roads = cls._parse(c)
                layers.append((c.get("name", ""), tuple(c["bbox"]), cls(areas, roads, source)))
                log.info("environment layer %s: %d areas, %d roads", c.get("name"), len(areas), len(roads))
            return MultiCityLayer(layers, source)
        areas, roads = cls._parse(data)
        log.info("environment layer loaded: %d areas, %d roads", len(areas), len(roads))
        return cls(areas, roads, source)

    # ---------- point queries ----------
    def _cell_keys(self, p: Point):
        i, j = math.floor(p[0] / CELL_DEG), math.floor(p[1] / CELL_DEG)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                yield (i + di, j + dj)

    def area_distance(self, p: Point, a: Area) -> float:
        if any(_inside(p, ring) for ring in a.rings):
            return 0.0
        px, py = self.proj.xy(p)
        best = math.inf
        for pts in self._area_xy[a.id_index]:
            for k in range(len(pts) - 1):
                d = _seg_dist(px, py, *pts[k], *pts[k + 1])
                if d < best:
                    best = d
        return best

    def near(self, p: Point) -> tuple[list[Area], list[Road]]:
        """Areas and roads beside point p, using per-kind thresholds."""
        seen_a: set[int] = set()
        out_a: list[Area] = []
        for key in self._cell_keys(p):
            for k in self._area_idx.get(key, ()):
                if k in seen_a:
                    continue
                seen_a.add(k)
                a = self.areas[k]
                s, w, n, e = a.bbox
                pad = NEAR[a.kind] / _M_PER_DEG_LAT * 1.3
                if not (s - pad <= p[0] <= n + pad and w - pad <= p[1] <= e + pad):
                    continue
                if self.area_distance(p, a) <= NEAR[a.kind]:
                    out_a.append(a)
        px, py = self.proj.xy(p)
        out_r: dict[int, Road] = {}
        for key in self._cell_keys(p):
            for k, i in self._road_idx.get(key, ()):
                if k in out_r:
                    continue
                xy = self._road_xy[k]
                if _seg_dist(px, py, *xy[i], *xy[i + 1]) <= NEAR["road"]:
                    out_r[k] = self.roads[k]
        return out_a, list(out_r.values())

    # ---------- routes ----------
    def describe_segments(self, segments) -> tuple[list[SegmentContext], RouteContext]:
        """segments: objects with .path (list of points) and .duration_s."""
        ctxs: list[SegmentContext] = []
        rc = RouteContext()
        # ~40 m sampling on city trips; at most ~500 samples on long ones (keeps a search fast)
        length = sum(haversine_m(a, b) for seg in segments for a, b in zip(seg.path, seg.path[1:]))
        step = max(40.0, length / 500)
        for seg in segments:
            samples = _resample(seg.path, step)
            if not samples:
                ctxs.append(SegmentContext())
                continue
            w = seg.duration_s / 60 / len(samples)
            g = r = 0
            for pt in samples:
                areas, roads = self.near(pt)
                kinds = {a.kind for a in areas}
                if "green" in kinds or "water" in kinds:
                    g += 1
                if roads:
                    r += 1
                for a in areas:
                    if a.kind == "green":
                        rc.green_by_name[a.name] = rc.green_by_name.get(a.name, 0) + w
                    elif a.kind == "water":
                        rc.water_by_name[a.name] = rc.water_by_name.get(a.name, 0) + w
                    elif a.kind == "industrial":
                        rc.industrial.add(a.name)
                    elif a.kind == "construction":
                        rc.construction += 1
                for rd in roads[:1]:
                    label = rd.name or "a main road"
                    rc.roads_by_name[label] = rc.roads_by_name.get(label, 0) + w
                if "green" in kinds:
                    rc.minutes_green += w
                if "water" in kinds:
                    rc.minutes_water += w
                if roads:
                    rc.minutes_busy_road += w
            rc.total_minutes += seg.duration_s / 60
            ctxs.append(SegmentContext(frac_green=g / len(samples), frac_road=r / len(samples)))
        return ctxs, rc

    # ---------- green-corridor route discovery ----------
    def green_waypoints(
        self,
        origin: Point,
        dest: Point,
        max_extra_m: float,
        avoid: list[Point],
        count: int = 3,
        min_area_m2: float = 30_000,
    ) -> list[tuple[Point, str]]:
        """Points on parks/lakes near the trip that a route could pass, best first.

        Score favours big green or blue spaces that cost little extra distance and
        that the fastest route does not already pass."""
        od = haversine_m(origin, dest)
        reach = od / 2 + max_extra_m  # an ellipse-ish search box around the trip
        mid = ((origin[0] + dest[0]) / 2, (origin[1] + dest[1]) / 2)
        dlat = reach / _M_PER_DEG_LAT
        dlng = reach / self.proj.kx
        box = (mid[0] - dlat, mid[1] - dlng, mid[0] + dlat, mid[1] + dlng)
        # Parks/lakes the fastest route already passes: found via the spatial index.
        avoid_len = sum(haversine_m(a, b) for a, b in zip(avoid, avoid[1:]))
        already: set[int] = set()
        for q in _resample(avoid, max(60.0, avoid_len / 400)):
            for key in self._cell_keys(q):
                for k in self._area_idx.get(key, ()):
                    if k not in already and self.areas[k].kind in ("green", "water"):
                        s_, w_, n_, e_ = self.areas[k].bbox
                        if s_ - 0.001 <= q[0] <= n_ + 0.001 and w_ - 0.001 <= q[1] <= e_ + 0.001:
                            if self.area_distance(q, self.areas[k]) <= 80:
                                already.add(k)
        scored: list[tuple[float, Point, str]] = []
        for a in self.areas:
            if a.kind not in ("green", "water") or a.area_m2 < min_area_m2 or a.id_index in already:
                continue
            s, w, n, e = a.bbox
            if n < box[0] or s > box[2] or e < box[1] or w > box[3]:
                continue
            # cheap reject before looking at vertices
            c0 = ((s + n) / 2, (w + e) / 2)
            half_diag = haversine_m((s, w), (n, e)) / 2
            if haversine_m(origin, c0) + haversine_m(c0, dest) - od - 2 * half_diag > max_extra_m:
                continue
            # Where to steer the route: through the middle of small and medium parks (their
            # paths), and a little inside the nearest edge of big forests and lakes, so the
            # route actually passes along the green space instead of grazing a corner.
            ring0 = max(a.rings, key=len)
            cen = (sum(p[0] for p in ring0) / len(ring0), sum(p[1] for p in ring0) / len(ring0))
            edge, edge_extra = None, math.inf
            for ring in a.rings:
                for v in ring[:: max(1, len(ring) // 60)]:
                    extra = haversine_m(origin, v) + haversine_m(v, dest) - od
                    if extra < edge_extra:
                        edge, edge_extra = v, extra
            if edge is None:
                continue
            if a.area_m2 <= 500_000 and a.kind == "green":
                best_pt = cen
            else:
                f = 0.0 if a.kind == "water" else 0.35  # don't route into a lake
                best_pt = (edge[0] + (cen[0] - edge[0]) * f, edge[1] + (cen[1] - edge[1]) * f)
            best = haversine_m(origin, best_pt) + haversine_m(best_pt, dest) - od
            if best * 1.3 > max_extra_m:  # 1.3: streets are not straight lines
                continue
            score = math.log10(a.area_m2) / (1 + best / 1000)
            scored.append((score, best_pt, a.name))
        scored.sort(key=lambda x: -x[0])
        picked: list[tuple[Point, str]] = []
        for _, pt, name in scored:
            if all(haversine_m(pt, q) > 800 for q, _ in picked):
                picked.append((pt, name))
            if len(picked) >= count:
                break
        return picked


def _resample(points, step_m: float) -> list[Point]:
    pts = list(points)
    if len(pts) < 2:
        return pts
    out = [pts[0]]
    carry = 0.0
    for a, b in zip(pts, pts[1:]):
        d = haversine_m(a, b)
        if d == 0:
            continue
        pos = step_m - carry
        while pos <= d:
            f = pos / d
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
            pos += step_m
        carry = d - (pos - step_m)
    if out[-1] != pts[-1]:
        out.append(pts[-1])
    return out


def highlights(rc: RouteContext, mode: str) -> list[dict]:
    """Plain-language notes for a route card. Most informative first."""
    out: list[dict] = []
    total = max(rc.total_minutes, 1e-6)

    def top(d: dict[str, float], n: int = 2, min_min: float = 1.0) -> list[str]:
        named = [(k, v) for k, v in d.items() if k and v >= min_min]
        named.sort(key=lambda kv: -kv[1])
        return [k for k, _ in named[:n]]

    def join(names: list[str]) -> str:
        return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"

    if rc.minutes_green >= 1:
        names = top(rc.green_by_name)
        place = join(names) if names else "parks and green spaces"
        out.append({"kind": "green", "text": f"Passes {place}, about {round(rc.minutes_green)} min beside greenery"})
    if rc.minutes_water >= 1:
        names = top(rc.water_by_name, 1)
        place = names[0] if names else "a lake or pond"
        out.append({"kind": "water", "text": f"Along {place} for about {round(rc.minutes_water)} min"})
    busy_share = rc.minutes_busy_road / total
    if rc.minutes_busy_road >= max(2.0, 0.05 * total):
        names = [n for n in top(rc.roads_by_name) if n != "a main road"]
        where = f" ({join(names)})" if names else ""
        verb = "on" if mode in ("DRIVE", "TWO_WHEELER") else "beside"
        out.append({"kind": "road", "text": f"{round(rc.minutes_busy_road)} min {verb} busy main roads{where}"})
    elif mode in ("WALK", "BICYCLE") and total >= 5:
        out.append({"kind": "quiet", "text": "Keeps off busy main roads" if rc.minutes_busy_road < 1 else "Mostly away from busy main roads"})
    if rc.industrial:
        names = sorted(n for n in rc.industrial if n)
        out.append({"kind": "industrial", "text": f"Passes near {names[0] if names else 'an industrial area'}"})
    if rc.construction:
        out.append({"kind": "construction", "text": "Near a mapped construction site (map data may be out of date)"})
    if busy_share >= 0.5 and mode in ("WALK", "BICYCLE"):
        out.sort(key=lambda h: h["kind"] != "road")  # warn first when most of the walk is on busy roads
    return out


class MultiCityLayer:
    """Several city layers, each with its own local projection. A trip uses the layer
    of the city its origin is in; elsewhere street context is simply off."""

    def __init__(self, layers: list[tuple[str, tuple[float, float, float, float], EnvironmentLayer]], source: str = ""):
        self.layers = layers
        self.source = source
        self._none = EnvironmentLayer([], [], source)

    @property
    def empty(self) -> bool:
        return all(layer.empty for _, _, layer in self.layers)

    @property
    def cities(self) -> list[str]:
        return [name for name, _, layer in self.layers if not layer.empty]

    def at(self, p: Point) -> EnvironmentLayer:
        for _, (s, w, n, e), layer in self.layers:
            if s <= p[0] <= n and w <= p[1] <= e:
                return layer
        return self._none
