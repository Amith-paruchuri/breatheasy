/**
 * Public evidence pages: how Breatheasy's air estimates compare with official CPCB
 * monitoring stations (/validation), and anonymous usage counts (/stats).
 */
import { useEffect, useState } from "react";

type Err = { mae: number; median_abs_error: number; bias: number; within_25pct: number | null; r: number | null } | null;
type Order = { pairs: number; agree_pct: number | null };
interface Summary {
  samples: number;
  stations?: number;
  runs?: number;
  first?: string;
  last?: string;
  google?: Err;
  adjusted?: Err;
  order_google?: Order;
  order_adjusted?: Order;
  street?: { near_road: { n: number; google: Err; adjusted: Err }; near_green: { n: number; google: Err; adjusted: Err } };
  cities?: Record<string, { samples: number; stations: number; google: Err; adjusted: Err; order_adjusted: Order }>;
  scatter?: { s: number; m: number }[];
  benchmark?: Bench;
}
interface Bench {
  trips: number;
  cleaner_found_pct?: number;
  median_cleaner_pct?: number | null;
  best_cleaner_pct?: number | null;
  median_cleaner_ugm3?: number | null;
  median_extra_min?: number | null;
  median_bad_min_avoided?: number | null;
  median_busy_road_min_avoided?: number | null;
  fidelity_phone_median_pct?: number | null;
  fidelity_computer_median_pct?: number | null;
  fidelity_computer_90_pct?: number | null;
  by_city?: Record<string, { trips: number; cleaner_found_pct: number; median_cleaner_pct: number | null; median_extra_min: number | null }>;
}

function BenchSection({ b }: { b: Bench }) {
  const n = (v?: number | null, suf = "") => (v == null ? "–" : `${Math.round(v)}${suf}`);
  return (
    <>
      <h2>On real commutes</h2>
      <p>
        Breatheasy is also run on {b.trips} realistic trips between well-known places (metro stations, hospitals,
        colleges, markets) in Delhi-NCR, Mumbai, Kolkata, Bengaluru and Hyderabad, on foot, by cycle and by two-wheeler.
      </p>
      <div className="ev-tiles">
        <div>
          <b>{n(b.cleaner_found_pct, "%")}</b>
          <span>of trips have a cleaner route than the fastest one</span>
        </div>
        <div>
          <b>{n(b.median_cleaner_pct, "%")}</b>
          <span>cleaner air on those routes (median), for {n(b.median_extra_min)} extra min</span>
        </div>
        <div>
          <b>{n(b.median_busy_road_min_avoided)} min</b>
          <span>less beside busy main roads (median, where street data exists)</span>
        </div>
      </div>
      <h2>Does Google Maps follow the chosen route?</h2>
      <p>
        "Start in Google Maps" sends the route with pins along it. We send the same pins to Google's routing service and
        measure how much of Google's path stays on our route (within 40 m).
      </p>
      <div className="ev-tiles">
        <div>
          <b>{n(b.fidelity_computer_median_pct, "%")}</b>
          <span>of the path matches on a computer (up to 8 pins, median)</span>
        </div>
        <div>
          <b>{n(b.fidelity_phone_median_pct, "%")}</b>
          <span>on a phone (Google allows 3 pins, median)</span>
        </div>
      </div>
      {b.by_city && (
        <table className="ev-table">
          <thead>
            <tr>
              <th>City</th>
              <th>Trips</th>
              <th>Cleaner route found</th>
              <th>Median cleaner</th>
              <th>Extra time</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(b.by_city).map(([c, v]) => (
              <tr key={c}>
                <td>{c}</td>
                <td>{v.trips}</td>
                <td>{Math.round(v.cleaner_found_pct)}%</td>
                <td>{n(v.median_cleaner_pct, "%")}</td>
                <td>{v.median_extra_min == null ? "–" : `${Math.round(v.median_extra_min)} min`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

function Shell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <main className="legal evidence">
      <a className="back" href="/">
        ← Back to Breatheasy
      </a>
      <h1>{title}</h1>
      {children}
    </main>
  );
}

const day = (iso?: string) =>
  iso ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "";

function Scatter({ pts }: { pts: { s: number; m: number }[] }) {
  const max = Math.max(100, ...pts.flatMap((p) => [p.s, p.m])) * 1.05;
  const W = 320;
  const x = (v: number) => 34 + (v / max) * (W - 44);
  const y = (v: number) => W - 28 - (v / max) * (W - 44);
  const ticks = [0, Math.round(max / 3 / 10) * 10, Math.round((2 * max) / 3 / 10) * 10];
  return (
    <svg viewBox={`0 0 ${W} ${W}`} className="scatter" role="img" aria-label="Breatheasy estimate against station reading">
      <line x1={x(0)} y1={y(0)} x2={x(max)} y2={y(max)} className="sc-diag" />
      {ticks.map((t) => (
        <g key={t}>
          <text x={x(t)} y={W - 10} textAnchor="middle">{t}</text>
          <text x={26} y={y(t) + 4} textAnchor="end">{t}</text>
        </g>
      ))}
      {pts.map((p, i) => (
        <circle key={i} cx={x(p.s)} cy={y(p.m)} r={2.6} className="sc-pt" />
      ))}
      <text x={W / 2 + 10} y={W} textAnchor="middle" className="sc-axis">Station PM2.5 (µg/m³)</text>
      <text x={8} y={W / 2} textAnchor="middle" transform={`rotate(-90 8 ${W / 2})`} className="sc-axis">Breatheasy</text>
    </svg>
  );
}

export function ValidationPage() {
  const [d, setD] = useState<Summary | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    fetch("/api/validation/summary")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setD)
      .catch(() => setErr(true));
  }, []);
  const a = d?.adjusted;
  const o = d?.order_adjusted;
  return (
    <Shell title="How accurate is Breatheasy?">
      <p>
        Every few hours, Breatheasy checks itself against India's official air-quality monitoring stations (CPCB,
        published on data.gov.in). For each station we compare its 24-hour average PM2.5 with the estimate Breatheasy
        would have shown for that exact spot over the same 24 hours. These results update automatically and nothing is
        filtered out.
      </p>
      {err && <p className="muted">The results could not be loaded. Try again in a minute.</p>}
      {d && d.samples === 0 && <p className="muted">The first comparisons are being collected. Check back in a few hours.</p>}
      {d && d.samples > 0 && a && (
        <>
          <div className="ev-tiles">
            <div>
              <b>{o?.agree_pct != null ? `${Math.round(o.agree_pct)}%` : "–"}</b>
              <span>of the time it correctly says which of two places in a city has dirtier air</span>
            </div>
            <div>
              <b>±{Math.round(a.median_abs_error)}</b>
              <span>µg/m³ typical difference from the station reading</span>
            </div>
            <div>
              <b>{a.r != null ? a.r.toFixed(2) : "–"}</b>
              <span>correlation with station readings (1 = perfect)</span>
            </div>
          </div>
          <p className="muted">
            {d.samples.toLocaleString("en-IN")} comparisons at {d.stations} stations, {day(d.first)} to {day(d.last)}.
            {o && ` Ordering is checked on ${o.pairs.toLocaleString("en-IN")} pairs of stations in the same city whose readings differ by at least 10 µg/m³.`}
          </p>

          <h2>Why ordering matters most</h2>
          <p>
            Breatheasy's job is to tell you which way has cleaner air, not to measure your lungs. So the key question is
            whether it ranks places in the right order. A constant offset (reading everything a bit high or low) does not
            change which route is cleaner.
          </p>

          <h2>Estimate vs station</h2>
          {d.scatter && d.scatter.length > 0 && <Scatter pts={d.scatter} />}
          <p className="muted">Each dot is one station at one time. Dots on the line would be a perfect match.</p>

          <table className="ev-table">
            <thead>
              <tr>
                <th />
                <th>Typical error</th>
                <th>Average bias</th>
                <th>Within 25%</th>
                <th>Correlation</th>
              </tr>
            </thead>
            <tbody>
              {[
                ["Google model alone", d.google],
                ["With Breatheasy's street adjustment", d.adjusted],
              ].map(([label, e]) => {
                const x = e as Err;
                return (
                  <tr key={label as string}>
                    <td>{label as string}</td>
                    <td>±{x ? Math.round(x.median_abs_error) : "–"}</td>
                    <td>{x ? `${x.bias > 0 ? "+" : ""}${Math.round(x.bias)}` : "–"}</td>
                    <td>{x?.within_25pct != null ? `${Math.round(x.within_25pct)}%` : "–"}</td>
                    <td>{x?.r != null ? x.r.toFixed(2) : "–"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {d.street && (d.street.near_road.n > 0 || d.street.near_green.n > 0) && (
            <>
              <h2>Does the street adjustment help?</h2>
              <p>
                Breatheasy raises its estimate beside busy main roads and lowers it beside parks and lakes, using
                OpenStreetMap. Stations next to those places test whether that is right (average bias, µg/m³; closer to
                0 is better):
              </p>
              <table className="ev-table">
                <thead>
                  <tr>
                    <th>Stations</th>
                    <th>Count</th>
                    <th>Google alone</th>
                    <th>Adjusted</th>
                  </tr>
                </thead>
                <tbody>
                  {(
                    [
                      ["Beside a busy road", d.street.near_road],
                      ["Beside a park or lake", d.street.near_green],
                    ] as const
                  ).map(([label, g]) => (
                    <tr key={label}>
                      <td>{label}</td>
                      <td>{g.n}</td>
                      <td>{g.google ? `${g.google.bias > 0 ? "+" : ""}${Math.round(g.google.bias)}` : "–"}</td>
                      <td>{g.adjusted ? `${g.adjusted.bias > 0 ? "+" : ""}${Math.round(g.adjusted.bias)}` : "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          {d.cities && Object.keys(d.cities).length > 0 && (
            <>
              <h2>By city</h2>
              <table className="ev-table">
                <thead>
                  <tr>
                    <th>City</th>
                    <th>Stations</th>
                    <th>Typical error</th>
                    <th>Right order</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(d.cities).map(([c, v]) => (
                    <tr key={c}>
                      <td>{c}</td>
                      <td>{v.stations}</td>
                      <td>±{v.adjusted ? Math.round(v.adjusted.median_abs_error) : "–"}</td>
                      <td>
                        {v.order_adjusted.agree_pct != null
                          ? `${Math.round(v.order_adjusted.agree_pct)}% of ${v.order_adjusted.pairs}`
                          : "–"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}

      {d?.benchmark && d.benchmark.trips > 0 && <BenchSection b={d.benchmark} />}

      <h2>Limits, stated plainly</h2>
      <ul>
        <li>Stations are fixed points, often on rooftops; a route is a moving line at street level. Good agreement at stations is necessary, not proof for every street.</li>
        <li>Google's model works on a grid of roughly 500 m, so differences between nearby streets come partly from Breatheasy's street adjustment, which is checked above.</li>
        <li>Station data on data.gov.in is provisional and sometimes delayed or missing; those readings are skipped, not guessed.</li>
      </ul>
      <p className="muted">
        Raw numbers: <a href="/api/validation/summary">/api/validation/summary</a>. Usage counts: <a href="/stats">/stats</a>.
      </p>
    </Shell>
  );
}

interface Stats {
  totals: Record<string, number>;
  by_city: Record<string, Record<string, number>>;
  by_day: Record<string, Record<string, number>>;
  since: string | null;
  note: string;
}
const EV: [string, string][] = [
  ["search", "Route searches"],
  ["agent", "Commute agent questions"],
  ["maps_open", "Trips started in Google Maps"],
  ["share", "Routes shared"],
  ["shared_open", "Shared links opened"],
];

export function StatsPage() {
  const [d, setD] = useState<Stats | null>(null);
  useEffect(() => {
    fetch("/api/stats")
      .then((r) => r.json())
      .then(setD)
      .catch(() => undefined);
  }, []);
  const days = d ? Object.entries(d.by_day).slice(-14) : [];
  const maxDay = Math.max(1, ...days.map(([, v]) => v.search ?? 0));
  return (
    <Shell title="Breatheasy in numbers">
      <p className="muted">{d?.note}</p>
      {d && (
        <>
          <div className="ev-tiles">
            {EV.map(([k, label]) => (
              <div key={k}>
                <b>{(d.totals[k] ?? 0).toLocaleString("en-IN")}</b>
                <span>{label}</span>
              </div>
            ))}
          </div>
          {d.since && <p className="muted">Counting since {d.since}.</p>}
          {days.length > 0 && (
            <>
              <h2>Searches per day</h2>
              <div className="ev-bars">
                {days.map(([dd, v]) => (
                  <div key={dd} title={`${dd}: ${v.search ?? 0}`}>
                    <i style={{ height: `${((v.search ?? 0) / maxDay) * 100}%` }} />
                    <span>{dd.slice(8)}</span>
                  </div>
                ))}
              </div>
            </>
          )}
          <h2>By city</h2>
          <table className="ev-table">
            <thead>
              <tr>
                <th>Area</th>
                <th>Searches</th>
                <th>Google Maps</th>
                <th>Shares</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(d.by_city)
                .sort((a, b) => (b[1].search ?? 0) - (a[1].search ?? 0))
                .map(([c, v]) => (
                  <tr key={c}>
                    <td>{c}</td>
                    <td>{v.search ?? 0}</td>
                    <td>{v.maps_open ?? 0}</td>
                    <td>{v.share ?? 0}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </>
      )}
      <p className="muted">
        How accurate the air estimates are: <a href="/validation">/validation</a>.
      </p>
    </Shell>
  );
}
