"""Field validation against a portable PM2.5 monitor (Challenge 6 in the proposal).

1. Plan a trip in the app and press "Save trip data" (downloads trip JSON).
2. Travel the recommended route (and ideally the fastest route too) carrying a
   portable PM2.5 sensor that logs GPS + PM2.5 (export as CSV with columns
   timestamp,lat,lng,pm25; timestamp in ISO format).
3. Run:
     python -m scripts.validate_with_sensor trip.json sensor_walk.csv --route r0

Outputs, for the chosen route: measured vs predicted exposure (µg/m³·min),
segment-level Spearman correlation between predicted and measured PM2.5, and a
per-segment CSV for plotting. Low-cost sensors need co-location calibration
against a reference monitor before absolute values are trusted; rankings and
correlations are more robust than absolute numbers.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime

from app.geo import haversine_m


def rank(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3:
        return None
    ra, rb = rank(a), rank(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((y - mb) ** 2 for y in rb) ** 0.5
    return cov / (va * vb) if va and vb else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("trip_json")
    ap.add_argument("sensor_csv")
    ap.add_argument("--route", help="route id in the trip JSON (default: recommended)")
    ap.add_argument("--max-dist", type=float, default=150, help="max metres from route to accept a reading")
    ap.add_argument("--out", default="validation_segments.csv")
    args = ap.parse_args()

    trip = json.load(open(args.trip_json, encoding="utf-8"))
    rid = args.route or trip["recommended_id"]
    route = next(r for r in trip["routes"] if r["id"] == rid)
    segs = route["segments"]
    seg_pts = [[(p["lat"], p["lng"]) for p in s["path"]] for s in segs]

    readings = []
    with open(args.sensor_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            readings.append(
                (datetime.fromisoformat(row["timestamp"]), float(row["lat"]), float(row["lng"]), float(row["pm25"]))
            )
    readings.sort()
    if len(readings) < 2:
        raise SystemExit("Need at least two sensor readings.")

    buckets: dict[int, list[float]] = {}
    measured_exposure = 0.0
    off_route = 0
    for (t0, la, ln, pm), (t1, *_rest) in zip(readings, readings[1:]):
        dists = [min(haversine_m((la, ln), q) for q in pts) for pts in seg_pts]
        i = min(range(len(seg_pts)), key=dists.__getitem__)
        if dists[i] > args.max_dist:
            off_route += 1
            continue
        buckets.setdefault(i, []).append(pm)
        measured_exposure += pm * (t1 - t0).total_seconds() / 60

    pred, meas, out_rows = [], [], []
    for i, s in enumerate(segs):
        m = sum(buckets[i]) / len(buckets[i]) if i in buckets else None
        out_rows.append({"segment": i, "predicted_pm25": s["pm25"], "measured_pm25": m, "n_readings": len(buckets.get(i, []))})
        if m is not None and s["pm25"] is not None:
            pred.append(s["pm25"])
            meas.append(m)

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0]))
        w.writeheader()
        w.writerows(out_rows)

    rho = spearman(pred, meas)
    print(f"route {rid} ({route['source']}), {len(segs)} segments, {len(pred)} with sensor data")
    print(f"predicted exposure: {route['exposure_pm25']} µg/m³·min")
    print(f"measured exposure:  {measured_exposure:.1f} µg/m³·min  (readings off-route: {off_route})")
    print(f"segment Spearman rho (predicted vs measured PM2.5): {rho:.2f}" if rho is not None else "too few segments for correlation")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
