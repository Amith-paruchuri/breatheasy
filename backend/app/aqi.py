"""India's National Air Quality Index (CPCB) from pollutant concentrations.

Breakpoints are the CPCB National AQI table (PM and gases in µg/m³, CO in mg/m³).
AQI = the highest pollutant sub-index. The official index uses 24-hour averages for
PM10, PM2.5, NO2 and SO2 and 8-hour averages for O3 and CO; Breatheasy applies the
same scale to hourly modelled concentrations along a route, so its numbers are an
hourly estimate on the CPCB scale, not an official station reading.

The Severe band (401-500) is open-ended in the table; above the last breakpoint we
extend with the slope of the Very Poor band and cap at 500.
"""

from __future__ import annotations

from dataclasses import dataclass

# (concentration low, high) for AQI bands 0-50, 51-100, 101-200, 201-300, 301-400
_AQI_BANDS = [(0, 50), (51, 100), (101, 200), (201, 300), (301, 400)]
BREAKPOINTS: dict[str, list[tuple[float, float]]] = {
    "pm10": [(0, 50), (51, 100), (101, 250), (251, 350), (351, 430)],
    "pm25": [(0, 30), (31, 60), (61, 90), (91, 120), (121, 250)],
    "no2": [(0, 40), (41, 80), (81, 180), (181, 280), (281, 400)],
    "o3": [(0, 50), (51, 100), (101, 168), (169, 208), (209, 748)],
    "co": [(0, 1.0), (1.1, 2.0), (2.1, 10), (10.1, 17), (17.1, 34)],  # mg/m³
    "so2": [(0, 40), (41, 80), (81, 380), (381, 800), (801, 1600)],
}

CATEGORIES = [
    (50, "Good"),
    (100, "Satisfactory"),
    (200, "Moderate"),
    (300, "Poor"),
    (400, "Very poor"),
    (500, "Severe"),
]

# ppb -> µg/m³ at 25 °C and 1 atm: × molecular weight / 24.45
_MW = {"no2": 46.0055, "o3": 47.997, "so2": 64.066, "co": 28.01}


def ppb_to_ugm3(code: str, ppb: float) -> float:
    return ppb * _MW[code] / 24.45


def sub_index(code: str, conc: float | None) -> float | None:
    if conc is None or conc < 0:
        return None
    bands = BREAKPOINTS[code]
    for n, ((c_lo, c_hi), (i_lo, i_hi)) in enumerate(zip(bands, _AQI_BANDS)):
        if conc <= c_hi:
            # standard CPCB/EPA linear interpolation within the band
            return i_lo + (i_hi - i_lo) * max(0.0, conc - c_lo) / ((c_hi - c_lo) or 1)
        nxt = bands[n + 1][0] if n + 1 < len(bands) else None
        if nxt is not None and conc < nxt:
            return float(i_hi)  # the small gap between table rows (e.g. 60 < x < 61)
    # Severe: extend with the Very Poor slope, cap at 500
    c_lo, c_hi = bands[-1]
    slope = (400 - 301) / ((c_hi - c_lo) or 1)
    return min(500.0, 400 + (conc - c_hi) * slope)


@dataclass
class AQIResult:
    aqi: int
    category: str
    dominant: str | None


def category(aqi: float | None) -> str | None:
    if aqi is None:
        return None
    for top, name in CATEGORIES:
        if aqi <= top:
            return name
    return "Severe"


def compute_aqi(
    pm25: float | None = None,
    pm10: float | None = None,
    no2: float | None = None,
    o3: float | None = None,
    co_mg: float | None = None,
    so2: float | None = None,
) -> AQIResult | None:
    """All concentrations in µg/m³ except CO in mg/m³."""
    subs = {
        "pm25": sub_index("pm25", pm25),
        "pm10": sub_index("pm10", pm10),
        "no2": sub_index("no2", no2),
        "o3": sub_index("o3", o3),
        "co": sub_index("co", co_mg),
        "so2": sub_index("so2", so2),
    }
    known = {k: v for k, v in subs.items() if v is not None}
    # CPCB needs a particulate value; without PM there's no meaningful AQI for a route.
    if "pm25" not in known and "pm10" not in known:
        return None
    dom = max(known, key=known.get)
    val = round(known[dom])
    return AQIResult(aqi=val, category=category(val) or "Severe", dominant=dom)
