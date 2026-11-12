"""Route selection (Step 5 in the proposal).

- cleanest_air: lowest time-weighted average PM2.5 (µg/m³) within a
            generous time budget: for people who want the cleanest air and will
            take a longer way for it (runs, walks, unhurried trips). Note this can
            mean MORE total exposure than the fastest route if the trip is much
            longer; the response reports both.
- fastest:  shortest duration.
- cleanest: lowest PM2.5 exposure among routes within the extra-time budget.
- balanced: within budget, maximise  reduction% - k * extra_minutes,
            i.e. an extra minute is only worth it if it buys >= k% less exposure.
If the best reduction is below the "meaningful" threshold, the app says so and
recommends the fastest route instead of over-claiming a difference that sits
inside the data's noise.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Preference


@dataclass
class Scored:
    id: str
    duration_s: float
    exposure: float | None
    cells: set
    mean_aqi: float | None = None
    mean_pm25: float | None = None
    penalty: float = 0.0  # sensitive mode: extra µg/m³-equivalents for busy roads and peaks


def pick_cleanest_air(routes: list[Scored], max_extra_min: float, meaningful_ugm3: float) -> tuple[str, str, dict]:
    """Lowest average PM2.5 within the time budget. PM2.5 varies far more from street to
    street than the AQI number (which flattens within each band), so it ranks routes;
    the AQI is still reported alongside."""
    fastest = min(routes, key=lambda r: r.duration_s)
    budget_s = fastest.duration_s + max_extra_min * 60
    eligible = [r for r in routes if r.duration_s <= budget_s + 1e-6 and r.mean_pm25 is not None]
    key = lambda r: r.mean_pm25 + r.penalty  # noqa: E731
    rnd = lambda v: round(v) if v is not None else None  # noqa: E731
    base = {"basis": "pm25", "fastest_aqi": rnd(fastest.mean_aqi), "fastest_pm25": rnd(fastest.mean_pm25)}
    if not eligible or fastest.mean_pm25 is None:
        return fastest.id, fastest.id, {
            **base, "meaningful": False, "reduction_pct": None, "extra_minutes": 0.0, "shared_cells_pct": None,
            "recommended_aqi": base["fastest_aqi"], "recommended_pm25": base["fastest_pm25"],
            "message": "No air-quality data was available for this trip, so routes are ranked by time only.",
        }
    # Lowest average PM2.5; routes within 2 µg/m³ count as a tie and the quicker one wins.
    best = min(key(r) for r in eligible)
    chosen = min((r for r in eligible if key(r) <= best + 2), key=lambda r: r.duration_s)
    gain = key(fastest) - key(chosen)
    meaningful = chosen is not fastest and gain >= meaningful_ugm3
    if chosen is not fastest and not meaningful:
        chosen = fastest
    extra = (chosen.duration_s - fastest.duration_s) / 60
    pct = gain / fastest.mean_pm25 * 100 if fastest.mean_pm25 else None
    if chosen is fastest:
        if gain > 0.5:
            msg = (f"Air is about the same on every route (average PM2.5 within {round(gain)} \u00b5g/m\u00b3), "
                   "so the fastest route is recommended.")
        else:
            msg = "The fastest route also has the cleanest air."
    else:
        msg = (f"Cleanest air: average PM2.5 {round(chosen.mean_pm25)} \u00b5g/m\u00b3 instead of "
               f"{round(fastest.mean_pm25)} on the fastest route, for {extra:+.0f} min.")
    shared = None
    if chosen is not fastest and fastest.cells and chosen.cells:
        shared = len(fastest.cells & chosen.cells) / len(chosen.cells) * 100
    return chosen.id, fastest.id, {
        **base,
        "meaningful": meaningful,
        "recommended_aqi": rnd(chosen.mean_aqi),
        "recommended_pm25": round(chosen.mean_pm25),
        "reduction_pct": round(pct, 1) if pct is not None and meaningful else (0.0 if pct is not None else None),
        "extra_minutes": round(extra, 1),
        "shared_cells_pct": round(shared, 0) if shared is not None else None,
        "message": msg,
    }


def pick(
    routes: list[Scored],
    preference: Preference,
    max_extra_min: float,
    pct_per_min: float,
    meaningful_pct: float,
    meaningful_pm25_ugm3: float = 5.0,
) -> tuple[str, str, dict]:
    if preference == Preference.CLEANEST_AIR:
        return pick_cleanest_air(routes, max_extra_min, meaningful_pm25_ugm3)
    fastest = min(routes, key=lambda r: r.duration_s)
    budget_s = fastest.duration_s + max_extra_min * 60

    def reduction(r: Scored) -> float | None:
        if r.exposure is None or not fastest.exposure:
            return None
        return (fastest.exposure - r.exposure) / fastest.exposure * 100

    eligible = [r for r in routes if r.duration_s <= budget_s + 1e-6 and r.exposure is not None]

    if preference == Preference.FASTEST or not eligible or fastest.exposure is None:
        chosen = fastest
    elif preference == Preference.CLEANEST:
        chosen = min(eligible, key=lambda r: (r.exposure, r.duration_s))
    else:

        def score(r: Scored) -> float:
            extra = (r.duration_s - fastest.duration_s) / 60
            return (reduction(r) or 0.0) - pct_per_min * extra

        chosen = max(eligible, key=lambda r: (score(r), -r.duration_s))

    red = reduction(chosen)
    cleanest_any = min((r for r in eligible), key=lambda r: r.exposure, default=None)
    best_red = reduction(cleanest_any) if cleanest_any else None

    meaningful = red is not None and red >= meaningful_pct
    if preference != Preference.FASTEST and chosen is not fastest and not meaningful:
        chosen, red = fastest, 0.0  # don't trade time for noise

    shared = None
    if chosen is not fastest and fastest.cells and chosen.cells:
        shared = len(fastest.cells & chosen.cells) / len(chosen.cells) * 100

    extra_min = (chosen.duration_s - fastest.duration_s) / 60
    if fastest.exposure is None:
        msg = "No air-quality data was available for this trip, so routes are ranked by time only."
    elif preference == Preference.FASTEST:
        if best_red is not None and best_red >= meaningful_pct:
            msg = f"A route within your time budget has about {best_red:.0f}% lower estimated PM2.5 exposure."
        else:
            msg = "Showing the fastest route. No alternative is meaningfully cleaner."
    elif chosen is fastest:
        if best_red is not None and best_red >= meaningful_pct and cleanest_any is not None:
            cost = (cleanest_any.duration_s - fastest.duration_s) / 60
            msg = (
                f"A route with ~{best_red:.0f}% lower exposure exists but costs {cost:.0f} extra min, "
                "more than the balanced trade-off allows. Choose 'Cleanest' to take it."
            )
        elif best_red is not None and best_red > 0:
            msg = (
                f"The cleanest option is only ~{best_red:.1f}% lower, below the {meaningful_pct:.0f}% "
                "threshold set for a meaningful difference at ~500 m data resolution, so the fastest route is recommended."
            )
        else:
            msg = "The fastest route is also the lowest-exposure option."
    else:
        msg = f"About {red:.0f}% lower estimated PM2.5 exposure for {extra_min:+.0f} min compared with the fastest route."

    return chosen.id, fastest.id, {
        "basis": "exposure",
        "recommended_aqi": round(chosen.mean_aqi) if chosen.mean_aqi is not None else None,
        "fastest_aqi": round(fastest.mean_aqi) if fastest.mean_aqi is not None else None,
        "meaningful": bool(meaningful and chosen is not fastest),
        "reduction_pct": round(red, 1) if red is not None else None,
        "extra_minutes": round(extra_min, 1),
        "shared_cells_pct": round(shared, 0) if shared is not None else None,
        "message": msg,
    }
