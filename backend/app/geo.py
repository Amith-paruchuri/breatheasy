"""Small geometry helpers (no heavy GIS dependency needed for the prototype)."""

from __future__ import annotations

import math
from typing import Iterable, Sequence

Point = tuple[float, float]  # (lat, lng)

EARTH_R_M = 6_371_008.8


def haversine_m(a: Point, b: Point) -> float:
    lat1, lng1 = map(math.radians, a)
    lat2, lng2 = map(math.radians, b)
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_R_M * math.asin(min(1.0, math.sqrt(h)))


def cumulative_distances(points: Sequence[Point]) -> list[float]:
    out = [0.0]
    for i in range(1, len(points)):
        out.append(out[-1] + haversine_m(points[i - 1], points[i]))
    return out


def lerp(a: Point, b: Point, f: float) -> Point:
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


def bearing_deg(a: Point, b: Point) -> float:
    lat1, lng1 = map(math.radians, a)
    lat2, lng2 = map(math.radians, b)
    dlng = lng2 - lng1
    x = math.sin(dlng) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlng)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def destination_point(origin: Point, bearing: float, distance_m: float) -> Point:
    lat1, lng1 = map(math.radians, origin)
    brg = math.radians(bearing)
    d = distance_m / EARTH_R_M
    lat2 = math.asin(math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(brg))
    lng2 = lng1 + math.atan2(
        math.sin(brg) * math.sin(d) * math.cos(lat1), math.cos(d) - math.sin(lat1) * math.sin(lat2)
    )
    return (math.degrees(lat2), (math.degrees(lng2) + 540) % 360 - 180)


def decode_polyline(encoded: str, precision: int = 5) -> list[Point]:
    """Decode a Google encoded polyline."""
    coords: list[Point] = []
    index = lat = lng = 0
    factor = 10**precision
    length = len(encoded)
    while index < length:
        for which in (0, 1):
            result = shift = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if which == 0:
                lat += delta
            else:
                lng += delta
        coords.append((lat / factor, lng / factor))
    return coords


def encode_polyline(points: Iterable[Point], precision: int = 5) -> str:
    factor = 10**precision
    out: list[str] = []
    prev_lat = prev_lng = 0
    for lat, lng in points:
        ilat, ilng = round(lat * factor), round(lng * factor)
        for delta in (ilat - prev_lat, ilng - prev_lng):
            v = ~(delta << 1) if delta < 0 else delta << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        prev_lat, prev_lng = ilat, ilng
    return "".join(out)


def resample(points: Sequence[Point], step_m: float) -> list[Point]:
    """Points spaced roughly every step_m along a polyline (used for overlap checks)."""
    if len(points) < 2:
        return list(points)
    cum = cumulative_distances(points)
    total = cum[-1]
    if total == 0:
        return [points[0]]
    out: list[Point] = []
    j = 0
    d = 0.0
    while d <= total:
        while j < len(cum) - 2 and cum[j + 1] < d:
            j += 1
        span = cum[j + 1] - cum[j]
        f = 0.0 if span == 0 else (d - cum[j]) / span
        out.append(lerp(points[j], points[j + 1], min(1.0, max(0.0, f))))
        d += step_m
    return out


def overlap_fraction(a: Sequence[Point], b: Sequence[Point], tol_m: float = 60.0) -> float:
    """Fraction of route a (sampled) lying within tol_m of route b."""
    sa = resample(a, tol_m)
    sb = resample(b, tol_m / 2)
    if not sa or not sb:
        return 0.0
    cell = tol_m / 111_000.0
    grid: dict[tuple[int, int], list[Point]] = {}
    for p in sb:
        grid.setdefault((int(p[0] // cell), int(p[1] // cell)), []).append(p)
    hit = 0
    for p in sa:
        ci, cj = int(p[0] // cell), int(p[1] // cell)
        found = False
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for q in grid.get((ci + di, cj + dj), ()):
                    if haversine_m(p, q) <= tol_m:
                        found = True
                        break
                if found:
                    break
            if found:
                break
        hit += found
    return hit / len(sa)
