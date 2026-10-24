"""Turn a routed polyline into timed segments.

Each segment knows where it is, how long the traveller spends in it, and when
they reach it. Timing comes from the routing engine's per-step durations,
rescaled so the total matches the (traffic-aware) route duration.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass

from ..geo import Point, cumulative_distances, lerp
from ..providers.base import RawRoute


@dataclass
class TimedPath:
    points: list[Point]
    cum_d: list[float]  # metres from start
    cum_t: list[float]  # seconds from start

    @property
    def length_m(self) -> float:
        return self.cum_d[-1] if self.cum_d else 0.0

    def at(self, d: float) -> tuple[Point, float]:
        """Interpolated (point, time) at distance d along the path."""
        d = min(max(d, 0.0), self.length_m)
        j = bisect.bisect_right(self.cum_d, d) - 1
        j = min(max(j, 0), len(self.cum_d) - 2)
        span = self.cum_d[j + 1] - self.cum_d[j]
        f = 0.0 if span <= 0 else (d - self.cum_d[j]) / span
        p = lerp(self.points[j], self.points[j + 1], f)
        t = self.cum_t[j] + (self.cum_t[j + 1] - self.cum_t[j]) * f
        return p, t


@dataclass
class Segment:
    path: list[Point]
    mid: Point
    start_s: float
    duration_s: float

    @property
    def mid_s(self) -> float:
        return self.start_s + self.duration_s / 2


def build_timed_path(route: RawRoute) -> TimedPath:
    points: list[Point] = []
    cum_d: list[float] = []
    cum_t: list[float] = []
    usable_steps = [s for s in route.steps if len(s.points) >= 2]
    step_time = sum(s.duration_s for s in usable_steps)

    if usable_steps and step_time > 0:
        d0 = t0 = 0.0
        for step in usable_steps:
            sd = cumulative_distances(step.points)
            total = sd[-1]
            for k, p in enumerate(step.points):
                if k == 0 and points:
                    continue  # shared boundary point with previous step
                frac = sd[k] / total if total > 0 else 1.0
                points.append(p)
                cum_d.append(d0 + sd[k])
                cum_t.append(t0 + frac * step.duration_s)
            d0 += total
            t0 += step.duration_s
    else:
        points = list(route.points)
        cum_d = cumulative_distances(points)
        total = cum_d[-1] or 1.0
        cum_t = [d / total * route.duration_s for d in cum_d]

    if len(points) < 2:
        points = list(route.points[:1]) * 2
        cum_d, cum_t = [0.0, 0.0], [0.0, route.duration_s]

    # Rescale to the route's overall (traffic-aware) duration.
    if cum_t[-1] > 0 and route.duration_s > 0:
        k = route.duration_s / cum_t[-1]
        cum_t = [t * k for t in cum_t]
    return TimedPath(points, cum_d, cum_t)


def split_segments(tp: TimedPath, spacing_m: float) -> list[Segment]:
    total = tp.length_m
    if total <= 0:
        p = tp.points[0]
        return [Segment(path=[p, p], mid=p, start_s=0.0, duration_s=tp.cum_t[-1])]
    n = max(1, math.ceil(total / spacing_m))
    step = total / n
    segs: list[Segment] = []
    for i in range(n):
        d0, d1 = i * step, (i + 1) * step
        p0, t0 = tp.at(d0)
        p1, t1 = tp.at(d1)
        mid, _ = tp.at((d0 + d1) / 2)
        lo = bisect.bisect_right(tp.cum_d, d0)
        hi = bisect.bisect_left(tp.cum_d, d1)
        path = [p0, *tp.points[lo:hi], p1]
        segs.append(Segment(path=path, mid=mid, start_s=t0, duration_s=max(0.0, t1 - t0)))
    return segs
