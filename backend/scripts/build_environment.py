"""Build the street-level environment layer from OpenStreetMap (Overpass API).

Run once before deploying (deploy.sh does it automatically when the file is missing),
and again every month or two to pick up map changes:

    cd backend && python3 scripts/build_environment.py

Writes backend/app/data/environment.json.gz (a few MB). Uses only the Python
standard library so it runs in Cloud Shell as-is. Respects Overpass fair use:
one request at a time, small tiles, pauses and retries.

Map data © OpenStreetMap contributors, ODbL 1.0.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ENDPOINTS = [  # public Overpass servers, tried in turn (the main one is often overloaded)
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
OUT = Path(__file__).resolve().parents[1] / "app" / "data" / "environment.json.gz"

GREEN = {("leisure", "park"), ("leisure", "garden"), ("leisure", "nature_reserve"), ("landuse", "forest"),
         ("landuse", "recreation_ground"), ("landuse", "village_green"), ("natural", "wood")}
WATER = {("natural", "water"), ("natural", "wetland"), ("landuse", "reservoir"), ("landuse", "basin")}
MIN_AREA = {"green": 10_000, "water": 10_000, "industrial": 20_000, "construction": 2_000}
ROADS = ("motorway", "trunk", "primary")


def area_query(s, w, n, e) -> str:
    b = f"({s},{w},{n},{e})"
    parts = []
    for k, v in sorted(GREEN | WATER | {("landuse", "industrial"), ("landuse", "construction")}):
        parts.append(f'way["{k}"="{v}"]{b};relation["{k}"="{v}"]{b};')
    return f"[out:json][timeout:180];({''.join(parts)});out tags geom;"


def road_query(s, w, n, e) -> str:
    b = f"({s},{w},{n},{e})"
    return f'[out:json][timeout:180];way["highway"~"^({"|".join(ROADS)})$"]{b};out tags geom;'


def fetch(query: str, ua: str) -> dict:
    last = None
    for attempt in range(10):
        url = ENDPOINTS[attempt % len(ENDPOINTS)]
        try:
            req = urllib.request.Request(
                url, data=urllib.parse.urlencode({"data": query}).encode(), headers={"User-Agent": ua}
            )
            with urllib.request.urlopen(req, timeout=240) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            wait = min(60, 10 * (attempt + 1))
            print(f"    {url} failed ({exc}); retrying in {wait}s", flush=True)
            time.sleep(wait)
    raise SystemExit(f"Overpass unavailable after retries: {last}")


def kind_of(tags: dict) -> str | None:
    pairs = set(tags.items())
    if pairs & WATER or tags.get("water"):
        return "water"
    if pairs & GREEN:
        return "green"
    if tags.get("landuse") == "industrial":
        return "industrial"
    if tags.get("landuse") == "construction":
        return "construction"
    return None


def name_of(tags: dict) -> str:
    return (tags.get("name:en") or tags.get("name") or "").strip()[:80]


def proj(lat0: float):
    kx = 111_320 * math.cos(math.radians(lat0))
    return lambda p: (p[1] * kx, p[0] * 110_574)


def ring_area(ring, xy) -> float:
    pts = [xy(p) for p in ring]
    return abs(sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1] for i in range(len(pts)))) / 2


def simplify(pts, tol_m, xy):
    """Douglas-Peucker in metres."""
    if len(pts) < 3:
        return pts
    P = [xy(p) for p in pts]
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = P[a]
        bx, by = P[b]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy)
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            # closed rings start and end on the same point: measure from that point instead
            d = (abs(dy * (P[i][0] - ax) - dx * (P[i][1] - ay)) / L) if L > 1e-6 else math.hypot(P[i][0] - ax, P[i][1] - ay)
            if d > best:
                best, idx = d, i
        if best > tol_m:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def stitch(lines):
    """Join open way pieces of a multipolygon outer boundary into closed rings."""
    lines = [list(l) for l in lines if len(l) >= 2]
    rings = []
    while lines:
        cur = lines.pop()
        changed = True
        while cur[0] != cur[-1] and changed:
            changed = False
            for i, l in enumerate(lines):
                if l[0] == cur[-1]:
                    cur += l[1:]
                elif l[-1] == cur[-1]:
                    cur += l[::-1][1:]
                elif l[-1] == cur[0]:
                    cur = l[:-1] + cur
                elif l[0] == cur[0]:
                    cur = l[::-1][:-1] + cur
                else:
                    continue
                lines.pop(i)
                changed = True
                break
        if len(cur) >= 4:
            rings.append(cur)
    return rings


CITIES = {
    "Delhi-NCR": (28.20, 76.80, 28.95, 77.75, 4),
    "Mumbai": (18.88, 72.77, 19.30, 73.10, 3),
    "Kolkata": (22.40, 88.20, 22.70, 88.50, 3),
    "Bengaluru": (12.80, 77.45, 13.15, 77.80, 3),
    "Hyderabad": (17.25, 78.30, 17.60, 78.65, 3),
}


def build_city(s: float, w: float, n: float, e: float, T: int, ua: str) -> dict:
    xy = proj((s + n) / 2)
    areas: dict[str, dict] = {}
    roads: dict[int, dict] = {}
    dlat, dlng = (n - s) / T, (e - w) / T
    total = T * T
    for ti in range(T):
        for tj in range(T):
            ts, tw = s + ti * dlat, w + tj * dlng
            tn, te = ts + dlat, tw + dlng
            k = ti * T + tj + 1
            print(f"[{k}/{total}] tile {ts:.3f},{tw:.3f} .. {tn:.3f},{te:.3f}", flush=True)

            data = fetch(area_query(ts, tw, tn, te), ua)
            for el in data.get("elements", []):
                key = f"{el['type']}/{el['id']}"
                if key in areas:
                    continue
                tags = el.get("tags", {})
                kind = kind_of(tags)
                if not kind:
                    continue
                if el["type"] == "way":
                    geom = [(g["lat"], g["lon"]) for g in el.get("geometry", []) if g]
                    rings = [geom] if len(geom) >= 4 and geom[0] == geom[-1] else []
                else:
                    outer = [
                        [(g["lat"], g["lon"]) for g in m.get("geometry", []) if g]
                        for m in el.get("members", [])
                        if m.get("type") == "way" and m.get("role", "outer") in ("outer", "")
                    ]
                    rings = stitch(outer)
                if not rings:
                    continue
                area = sum(ring_area(r, xy) for r in rings)
                if area < MIN_AREA[kind]:
                    continue
                rings = [simplify(r, 10.0, xy) for r in rings]
                areas[key] = {
                    "kind": kind,
                    "name": name_of(tags),
                    "area_m2": round(area),
                    "rings": [[[round(p[0], 5), round(p[1], 5)] for p in r] for r in rings if len(r) >= 4],
                }
            time.sleep(3)

            data = fetch(road_query(ts, tw, tn, te), ua)
            for el in data.get("elements", []):
                if el["id"] in roads or el["type"] != "way":
                    continue
                tags = el.get("tags", {})
                pts = [(g["lat"], g["lon"]) for g in el.get("geometry", []) if g]
                if len(pts) < 2:
                    continue
                pts = simplify(pts, 8.0, xy)
                roads[el["id"]] = {
                    "name": name_of(tags) or tags.get("ref", ""),
                    "cls": tags.get("highway", ""),
                    "pts": [[round(p[0], 5), round(p[1], 5)] for p in pts],
                }
            time.sleep(3)

    return {
        "bbox": [s, w, n, e],
        "areas": [a for a in areas.values() if a["rings"]],
        "roads": list(roads.values()),
    }


def _write(path: str, cities: list[dict]) -> None:
    out = {
        "version": 2,
        "generated": datetime.now(timezone.utc).isoformat(),
        "source": "© OpenStreetMap contributors, ODbL 1.0",
        "cities": cities,
    }
    tmp = Path(path).with_suffix(".tmp")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    tmp.replace(path)  # atomic: a timeout mid-city never leaves a broken file


def _existing(path: str) -> list[dict]:
    p = Path(path)
    if not p.is_file():
        return []
    with gzip.open(p, "rt", encoding="utf-8") as f:
        data = json.load(f)
    if "cities" in data:
        return data["cities"]
    # version 1 file: one Delhi-NCR layer
    return [{"name": "Delhi-NCR", "bbox": data.get("bbox"), "areas": data.get("areas", []), "roads": data.get("roads", [])}]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cities", default=",".join(CITIES), help="comma-separated: " + ", ".join(CITIES))
    ap.add_argument("--contact", default="", help="email for the Overpass User-Agent")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--rebuild", action="store_true", help="rebuild cities already in the file")
    ap.add_argument("--tiles", type=int, default=0, help="override tiles per side (default: per city)")
    args = ap.parse_args()
    ua = f"Breatheasy-environment-builder/1.0 ({args.contact or 'no contact given'})"
    have = {c["name"]: c for c in ([] if args.rebuild else _existing(args.out))}
    wanted = [c.strip() for c in args.cities.split(",") if c.strip()]
    for name in wanted:
        if name in have:
            print(f"{name}: already built, keeping it", flush=True)
            continue
        if name not in CITIES:
            sys.exit(f"Unknown city {name!r}; known: {', '.join(CITIES)}")
        s, w, n, e, T = CITIES[name]
        T = args.tiles or T
        print(f"== {name}", flush=True)
        have[name] = {"name": name, **build_city(s, w, n, e, T, ua)}
        _write(args.out, list(have.values()))  # save after every city
        c = have[name]
        print(f"{name}: {len(c['areas'])} areas, {len(c['roads'])} main-road segments", flush=True)
    _write(args.out, list(have.values()))
    size = Path(args.out).stat().st_size / 1e6
    print(f"Wrote {args.out} ({size:.1f} MB): {', '.join(have)}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
