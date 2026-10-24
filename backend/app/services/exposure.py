"""Exposure model (Challenge 4): E = Σ Cᵢ × tᵢ.

E is in µg/m³·min. It is a RELATIVE indicator for comparing routes of the same
trip and mode. It is not an inhaled dose: it ignores breathing rate, vehicle
ventilation, and the gap between a ~500 m grid value and the air at road level.
Segments with no data are filled with the route's time-weighted mean so routes
remain comparable; `coverage` reports how much of the trip was actually covered.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..providers.base import AQReading
from .sampling import Segment


@dataclass
class ExposureResult:
    exposure_pm25: float | None
    exposure_pm10: float | None
    mean_pm25: float | None
    peak_pm25: float | None
    minutes_above_reference: float | None
    coverage: float


def _integrate(values: list[float | None], minutes: list[float]) -> tuple[float | None, float | None]:
    covered_t = sum(m for v, m in zip(values, minutes) if v is not None)
    total_t = sum(minutes)
    if covered_t <= 0:
        return None, None
    s = sum(v * m for v, m in zip(values, minutes) if v is not None)
    mean = s / covered_t
    return s + mean * (total_t - covered_t), mean


def compute_exposure(
    segments: list[Segment], readings: list[AQReading | None], reference_pm25: float
) -> ExposureResult:
    minutes = [seg.duration_s / 60 for seg in segments]
    pm25 = [r.pm25 if r else None for r in readings]
    pm10 = [r.pm10 if r else None for r in readings]
    e25, mean25 = _integrate(pm25, minutes)
    e10, _ = _integrate(pm10, minutes)
    total = sum(minutes)
    covered = sum(m for v, m in zip(pm25, minutes) if v is not None)
    known = [v for v in pm25 if v is not None]
    above = sum(m for v, m in zip(pm25, minutes) if v is not None and v > reference_pm25) if known else None
    return ExposureResult(
        exposure_pm25=round(e25, 1) if e25 is not None else None,
        exposure_pm10=round(e10, 1) if e10 is not None else None,
        mean_pm25=round(mean25, 1) if mean25 is not None else None,
        peak_pm25=max(known) if known else None,
        minutes_above_reference=round(above, 1) if above is not None else None,
        coverage=round(covered / total, 3) if total > 0 else 0.0,
    )
