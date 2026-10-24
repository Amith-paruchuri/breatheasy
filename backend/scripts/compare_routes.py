"""Batch feasibility study (Key Questions 1, 2, 3 and 5 in the proposal).

Runs a list of origin-destination pairs through the planner for each travel mode
and records, per trip: how much cleaner the best in-budget route is than the
fastest, how often that best route came from detour exploration rather than
Google's own alternatives, how many API calls it took, and estimated cost.

Usage (from backend/):
    python -m scripts.compare_routes scripts/od_pairs_delhi.csv --modes WALK TWO_WHEELER \
        --budget 10 --out results.csv

Uses whatever PROVIDER is set in .env. With PROVIDER=google every row costs
real API calls: check the call counts on a few rows before running a big batch.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import statistics
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.models import LatLng, Preference, RouteRequest, TravelMode
from app.providers import build_providers
from app.services.airquality import AQCache, AQService
from app.services.planner import plan_routes

IST = timezone(timedelta(hours=5, minutes=30))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pairs_csv", help="CSV with columns name,o_lat,o_lng,d_lat,d_lng")
    ap.add_argument("--modes", nargs="+", default=["WALK"], choices=[m.value for m in TravelMode])
    ap.add_argument("--budget", type=float, default=10.0, help="max extra minutes")
    ap.add_argument("--depart", default=None, help="ISO time in IST, e.g. 2026-10-23T08:30 (default: now)")
    ap.add_argument("--no-detours", action="store_true")
    ap.add_argument("--out", default="results.csv")
    args = ap.parse_args()

    s = get_settings()
    providers = build_providers(s)
    aq = AQService(providers.air, s, AQCache(s.aq_cache_ttl_s))
    depart = datetime.fromisoformat(args.depart).replace(tzinfo=IST) if args.depart else None

    with open(args.pairs_csv, newline="", encoding="utf-8") as f:
        pairs = list(csv.DictReader(f))

    rows = []
    try:
        for p in pairs:
            for mode in args.modes:
                req = RouteRequest(
                    origin=LatLng(lat=float(p["o_lat"]), lng=float(p["o_lng"])),
                    destination=LatLng(lat=float(p["d_lat"]), lng=float(p["d_lng"])),
                    mode=TravelMode(mode),
                    preference=Preference.CLEANEST,
                    max_extra_minutes=args.budget,
                    departure_time=depart,
                    explore_detours=not args.no_detours,
                )
                try:
                    resp = await plan_routes(req, providers, aq, s)
                except Exception as exc:  # keep the batch going
                    print(f"{p['name']} {mode}: FAILED {exc}")
                    continue
                fast = next(r for r in resp.routes if r.id == resp.fastest_id)
                in_budget = [r for r in resp.routes if r.within_budget and r.exposure_pm25 is not None]
                best = min(in_budget, key=lambda r: r.exposure_pm25) if in_budget else fast
                red = (
                    (fast.exposure_pm25 - best.exposure_pm25) / fast.exposure_pm25 * 100
                    if fast.exposure_pm25 and best.exposure_pm25 is not None
                    else None
                )
                u = resp.usage
                row = {
                    "name": p["name"],
                    "mode": mode,
                    "candidates": len(resp.routes),
                    "detours": sum(r.source == "detour" for r in resp.routes),
                    "fastest_min": round(fast.duration_s / 60, 1),
                    "fastest_exposure": fast.exposure_pm25,
                    "fastest_mean_pm25": fast.mean_pm25,
                    "best_min": round(best.duration_s / 60, 1),
                    "best_exposure": best.exposure_pm25,
                    "best_source": best.source,
                    "best_reduction_pct": round(red, 1) if red is not None else None,
                    "extra_min": round((best.duration_s - fast.duration_s) / 60, 1),
                    "meaningful": resp.comparison.meaningful,
                    "distinct_cells_best": best.distinct_cells,
                    "coverage_min": min(r.coverage for r in resp.routes),
                    "routes_calls": u.routes_calls,
                    "aq_calls": u.aq_current_calls + u.aq_forecast_calls,
                    "aq_cache_hits": u.aq_cache_hits,
                    "est_cost_usd": u.estimated_cost_usd,
                }
                rows.append(row)
                print(
                    f"{p['name']:<28} {mode:<11} best -{row['best_reduction_pct']}% "
                    f"(+{row['extra_min']} min, {row['best_source']}) calls R{u.routes_calls}/AQ{row['aq_calls']}"
                )
    finally:
        await providers.aclose()

    if not rows:
        print("No results.")
        return
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    reds = [r["best_reduction_pct"] for r in rows if r["best_reduction_pct"] is not None]
    print("\n--- Summary ---")
    print(f"trips: {len(rows)}")
    if reds:
        print(f"median best reduction within {args.budget:g} min: {statistics.median(reds):.1f}%")
        print(f"trips with a meaningful (>= {s.meaningful_diff_pct:g}%) option: "
              f"{sum(r['meaningful'] for r in rows)}/{len(rows)}")
        print(f"best route came from detour exploration: {sum(r['best_source'] == 'detour' for r in rows)}/{len(rows)}")
    print(f"mean calls per trip: routes {statistics.mean(r['routes_calls'] for r in rows):.1f}, "
          f"AQ {statistics.mean(r['aq_calls'] for r in rows):.1f}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
