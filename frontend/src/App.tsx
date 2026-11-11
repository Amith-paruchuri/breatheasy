import { APIProvider } from "@vis.gl/react-google-maps";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AccountProvider, useAccount } from "./account";
import { ApiError, addPlace, getConfig, logTrip, planRoutes, runAgent, type AgentResponse } from "./api";
import { AccountPanel } from "./components/AccountPanel";
import { BottomSheet, heights, type Snap } from "./components/BottomSheet";
import { Icon } from "./components/Icon";
import { LeafletMap } from "./components/LeafletMap";
import { PlaceInput } from "./components/PlaceInput";
import { RouteCard, RouteCardSkeleton } from "./components/RouteCard";
import { RouteMap, type FitPadding } from "./components/RouteMap";
import { SchematicMap } from "./components/SchematicMap";
import { ModePicker, TripSettings, settingsSummary } from "./components/TripControls";
import { MODE_LABEL, PM25_BANDS, PM25_SAFE_LIMIT, aqiLabel, fmtTime, googleMapsUrl } from "./format";
import { useIsDesktop, useOnline } from "./hooks";
import { PrivacyPage, TermsPage } from "./pages/Legal";
import type { AppConfig, Place, Preference, RouteOut, RouteResponse, TravelMode } from "./types";

const ENV_MAPS_KEY = import.meta.env.VITE_GOOGLE_MAPS_BROWSER_KEY as string | undefined;

export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [bootError, setBootError] = useState<string | null>(null);

  const load = useCallback(() => {
    setBootError(null);
    getConfig()
      .then(setConfig)
      .catch(() => setBootError("Breatheasy can't connect right now. Check your internet connection, then try again."));
  }, []);
  useEffect(load, [load]);

  const path = window.location.pathname.replace(/\/+$/, "");
  if (path === "/privacy") return <PrivacyPage />;
  if (path === "/terms") return <TermsPage />;

  if (!config) {
    return (
      <div className="boot">
        <Mark size={56} />
        {bootError ? (
          <>
            <p>{bootError}</p>
            <button type="button" className="btn-secondary" onClick={load}>
              Try again
            </button>
          </>
        ) : (
          <span className="spinner" aria-label="Loading" />
        )}
      </div>
    );
  }

  const mapsKey = config.maps_browser_key || ENV_MAPS_KEY || "";
  const planner = (
    <AccountProvider enabled={config.accounts_enabled}>
      <Planner config={config} mapsKey={mapsKey} />
    </AccountProvider>
  );
  return mapsKey ? (
    <APIProvider apiKey={mapsKey} region="IN" language="en">
      {planner}
    </APIProvider>
  ) : (
    planner
  );
}

export function Mark({ size = 36 }: { size?: number }) {
  return (
    <span className="mark" style={{ width: size, height: size }} aria-hidden>
      <svg viewBox="0 0 32 32" width={size * 0.72} height={size * 0.72}>
        <path d="M5 22c5 0 6-12 11-12s6 8 11 8" fill="none" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" />
        <circle cx="5" cy="22" r="3.2" fill="currentColor" />
        <circle cx="27" cy="18" r="3.2" className="mark-dot" />
      </svg>
    </span>
  );
}

function Legend({ explain = false }: { explain?: boolean }) {
  const n = PM25_BANDS.length;
  return (
    <div className="legend" aria-label="Map colours: PM2.5 in micrograms per cubic metre of air">
      <span className="legend-title">
        PM2.5 <small>µg/m³</small>
      </span>
      <div className="legend-scale">
        <div className="legend-bar">
          {PM25_BANDS.map((b) => (
            <i key={b.max} style={{ background: b.color }} title={b.label} />
          ))}
        </div>
        <div className="legend-ticks" aria-hidden>
          {PM25_BANDS.slice(0, -1).map((b, i) => (
            <span key={b.max} style={{ left: `${((i + 1) / n) * 100}%` }} className={b.max === PM25_SAFE_LIMIT ? "is-limit" : ""}>
              {b.max}
            </span>
          ))}
        </div>
      </div>
      {explain && (
        <p className="legend-note">
          The map is coloured by PM2.5: the weight of fine dust and smoke particles in one cubic metre of air, in
          micrograms (µg/m³). India's safe limit is {PM25_SAFE_LIMIT} (WHO's is 15), so anything orange or red is
          above it. The AQI number on each route is the overall air-quality score built from PM2.5 and other
          pollutants.
        </p>
      )}
    </div>
  );
}

function AgentBox({ onPlan }: { onPlan: (res: AgentResponse) => void }) {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [listening, setListening] = useState(false);
  const ac = useRef<AbortController | null>(null);

  const submit = useCallback(
    async (q: string) => {
      if (!q.trim() || loading) return;
      setLoading(true);
      ac.current?.abort();
      const ctrl = new AbortController();
      ac.current = ctrl;
      const done = () => {
        if (ac.current === ctrl) setLoading(false);
      };

      navigator.geolocation.getCurrentPosition(
        async (pos) => {
          try {
            const res = await runAgent({ query: q, origin: { lat: pos.coords.latitude, lng: pos.coords.longitude } }, ctrl.signal);
            onPlan(res);
          } catch (e) {
            if ((e as Error).name !== "AbortError") alert(e instanceof ApiError ? e.message : "Something didn't work.");
          } finally {
            done();
          }
        },
        async () => {
          // Fallback to Delhi center if geolocation is denied/fails
          try {
            const res = await runAgent({ query: q, origin: { lat: 28.61, lng: 77.23 } }, ctrl.signal);
            onPlan(res);
          } catch (e) {
            if ((e as Error).name !== "AbortError") alert(e instanceof ApiError ? e.message : "Something didn't work.");
          } finally {
            done();
          }
        },
        { timeout: 5000 },
      );
    },
    [loading, onPlan],
  );

  const startListening = () => {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) return;
    const recognition = new SpeechRecognition();
    recognition.lang = "en-IN";
    recognition.onstart = () => setListening(true);
    recognition.onend = () => setListening(false);
    recognition.onresult = (event: any) => {
      const transcript = event.results[0][0].transcript;
      setQuery(transcript);
      submit(transcript);
    };
    recognition.start();
  };

  const hasMic = !!((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition);

  return (
    <div className="agent-wrap">
      <div className="agent-box">
        <input
          type="text"
          placeholder="Ask Breatheasy (e.g. reach Hauz Khas by 9 am)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit(query)}
          disabled={loading}
        />
        {hasMic && (
          <button type="button" className={`mic-btn${listening ? " is-listening" : ""}`} onClick={startListening} aria-label="Speak">
            <Icon name="mic" size={20} />
          </button>
        )}
      </div>
      {loading && <span className="spinner small agent-loading" />}
    </div>
  );
}

function Planner({ config, mapsKey }: { config: AppConfig; mapsKey: string }) {
  const acct = useAccount();
  const online = useOnline();
  const desktop = useIsDesktop();
  const [origin, setOrigin] = useState<Place | null>(null);
  const [destination, setDestination] = useState<Place | null>(null);
  const [mode, setMode] = useState<TravelMode>("WALK");
  const [preference, setPreferenceRaw] = useState<Preference>("cleanest_air");
  const [budget, setBudgetRaw] = useState(config.cleanest_air_default_extra_minutes);
  const [budgetTouched, setBudgetTouched] = useState(false);
  const setBudget = (n: number) => {
    setBudgetTouched(true);
    setBudgetRaw(n);
  };
  // Each preference starts from a sensible time limit until the person picks their own.
  const setPreference = (p: Preference) => {
    setPreferenceRaw(p);
    if (!budgetTouched)
      setBudgetRaw(p === "cleanest_air" ? config.cleanest_air_default_extra_minutes : config.default_max_extra_minutes);
  };
  const [leaveLater, setLeaveLater] = useState(false);
  const [departure, setDeparture] = useState("");
  const [result, setResult] = useState<RouteResponse | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [retry, setRetry] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [showAccount, setShowAccount] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [loggedRoutes, setLoggedRoutes] = useState<Set<string>>(new Set());
  const [snap, setSnap] = useState<Snap>("peek");
  const [searching, setSearching] = useState(false);
  // Phones: once a trip is set, the search collapses to one line until tapped.
  const [editTrip, setEditTrip] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [resultKey, setResultKey] = useState(0);
  const [verdictOverride, setVerdictOverride] = useState<string | null>(null);
  const inflight = useRef<AbortController | null>(null);
  const carousel = useRef<HTMLDivElement>(null);

  // Plan (or re-rank) whenever the inputs change. Re-ranking the same trip is
  // served from the backend's short-lived candidate cache, so it costs no API calls.
  useEffect(() => {
    if (!origin || !destination) {
      setResult(null);
      return;
    }
    const t = setTimeout(async () => {
      inflight.current?.abort();
      const ctrl = new AbortController();
      inflight.current = ctrl;
      setLoading(true);
      setError(null);
      setSnap((s) => (s === "peek" ? "half" : s));
      try {
        const res = await planRoutes(
          {
            origin: origin.location,
            destination: destination.location,
            mode,
            preference,
            max_extra_minutes: budget,
            departure_time: leaveLater && departure ? departure : null,
          },
          ctrl.signal,
        );
        setResult(res);
        setVerdictOverride(null);
        if (res.plan && res.plan.plan !== "anonymous") acct.setPlan({ ...res.plan, street_level: res.plan.used < res.plan.limit });
        setSelectedId(res.recommended_id);
        setLoggedRoutes(new Set());
        setResultKey((k) => k + 1);
        carousel.current?.scrollTo({ left: 0 });
      } catch (e) {
        if ((e as Error).name !== "AbortError") {
          setError(e instanceof ApiError ? e : new ApiError("Something didn't work. Try again.", 0));
          setResult(null);
        }
      } finally {
        if (inflight.current === ctrl) setLoading(false);
      }
    }, 280);
    return () => clearTimeout(t);
  }, [origin, destination, mode, preference, budget, leaveLater, departure, retry]);

  const onAgentPlan = useCallback(
    (res: AgentResponse) => {
      if (res.plan) {
        setResult(res.plan);
        setVerdictOverride(res.verdict);
        setSelectedId(res.plan.recommended_id);
        setLoggedRoutes(new Set());
        setResultKey((k) => k + 1);
        setSnap("half");
        carousel.current?.scrollTo({ left: 0 });
      } else {
        setToast(res.verdict);
      }
    },
    [acct],
  );

  // Seconds since the current search started, for the progress text.
  useEffect(() => {
    if (!loading) {
      setElapsed(0);
      return;
    }
    const start = Date.now();
    const iv = setInterval(() => setElapsed((Date.now() - start) / 1000), 250);
    return () => clearInterval(iv);
  }, [loading]);
  const progressText =
    elapsed < 1.5
      ? "Finding routes"
      : elapsed < 4
        ? "Checking the air along each route"
        : elapsed < 9
          ? "Comparing exposure on each route"
          : "Long trip, still checking. Almost there";

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3200);
    return () => clearTimeout(t);
  }, [toast]);

  const fastestRoute = useMemo(() => result?.routes.find((r) => r.id === result.fastest_id) ?? null, [result]);

  const savePlace = useCallback(
    async (p: Place, label: string) => {
      await addPlace({ label, name: p.label, lat: p.location.lat, lng: p.location.lng });
      await acct.refreshPlaces();
    },
    [acct],
  );

  function select(id: string) {
    setSelectedId(id);
    if (!desktop) {
      const el = carousel.current?.querySelector<HTMLElement>(`[data-route="${id}"]`);
      el?.scrollIntoView({ behavior: "smooth", inline: "start", block: "nearest" });
    }
  }

  function onNavigate(r: RouteOut) {
    if (!acct.me || !result || !origin || !destination || loggedRoutes.has(r.id)) return;
    setLoggedRoutes((s) => new Set(s).add(r.id));
    logTrip({
      departure_time: result.data.departure_time,
      mode,
      preference,
      origin: { name: origin.label.slice(0, 200), lat: origin.location.lat, lng: origin.location.lng },
      destination: { name: destination.label.slice(0, 200), lat: destination.location.lat, lng: destination.location.lng },
      route_source: r.source,
      duration_s: r.duration_s,
      distance_m: r.distance_m,
      exposure_pm25: r.exposure_pm25,
      fastest_exposure_pm25: fastestRoute?.exposure_pm25 ?? null,
      fastest_duration_s: fastestRoute?.duration_s ?? null,
      mean_pm25: r.mean_pm25,
      data_source: (result.data.aq_source ?? result.data.provider).slice(0, 32),
    })
      .then(() => setToast("Trip added to your log"))
      .catch(() => setToast("This trip couldn't be added to your log"));
  }

  function downloadTripData() {
    if (!result) return;
    const blob = new Blob([JSON.stringify({ ...result, origin, destination, mode }, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `breatheasy-trip-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "")}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  const pickOrigin = (p: Place | null) => {
    setOrigin(p);
    if (p && destination) setEditTrip(false);
  };
  const pickDestination = (p: Place | null) => {
    setDestination(p);
    if (p && origin) setEditTrip(false);
  };
  const tripSet = !!origin && !!destination;
  const collapsed = !desktop && tripSet && !editTrip && !searching;

  const me = acct.me;
  const fitPadding: FitPadding = desktop
    ? { top: 56, right: 56, bottom: 56, left: 470 }
    : { top: collapsed ? 128 : 250, right: 28, bottom: 28, left: 28 };
  // On phones the map ends where the sheet begins, so the whole route (and the
  // map providers' required attribution) stays visible above it.
  const stageBottom = desktop || searching ? 0 : Math.min(heights()[snap], heights().half);

  const mapProps = {
    routes: result?.routes ?? [],
    selectedId,
    onSelect: select,
    origin: origin?.location ?? null,
    destination: destination?.location ?? null,
    mapId: config.map_id,
    fitPadding,
  };

  const accountButton = config.accounts_enabled && (
    <button type="button" className="avatar-btn" onClick={() => setShowAccount(true)} aria-label={me ? "Your account" : "Sign in"}>
      {me?.picture ? (
        <img src={me.picture} alt="" referrerPolicy="no-referrer" />
      ) : me ? (
        <span className="avatar-letter">{(me.name || me.email)[0]}</span>
      ) : (
        <span className="avatar-signin">Sign in</span>
      )}
    </button>
  );

  const search = (
    <div className="search">
      <PlaceInput
        label="Start"
        role="origin"
        value={origin}
        onChange={pickOrigin}
        saved={acct.places}
        onSave={me && origin ? (l) => savePlace(origin, l) : undefined}
        onFocusChange={setSearching}
      />
      <PlaceInput
        label="Where to?"
        role="destination"
        value={destination}
        onChange={pickDestination}
        saved={acct.places}
        onSave={me && destination ? (l) => savePlace(destination, l) : undefined}
        onFocusChange={setSearching}
      />
      <button
        type="button"
        className="swap"
        onClick={() => {
          setOrigin(destination);
          setDestination(origin);
        }}
        aria-label="Swap start and destination"
      >
        <Icon name="swap" size={18} />
      </button>
    </div>
  );

  const banners = (
    <>
      {!online && (
        <p className="banner warn" role="status">
          <Icon name="wifiOff" size={16} /> You're offline. Planning will resume when you reconnect.
        </p>
      )}
      {config.mock && (
        <p className="banner warn" role="status">
          Demo mode: routes and air quality are made up.
        </p>
      )}
    </>
  );

  const c = result?.comparison;
  const rec = result?.routes.find((r) => r.id === result.recommended_id);
  const mins = c ? Math.round(c.extra_minutes) : 0;
  let headline = "";
  let subline = "";
  if (c && c.basis === "aqi") {
    if (c.meaningful) {
      headline = mins > 0 ? `Cleaner air, ${mins} min longer` : "Cleaner air, no extra time";
      subline = `Average AQI ${c.recommended_aqi} (${aqiLabel(c.recommended_aqi).toLowerCase()}) instead of ${c.fastest_aqi} on the fastest route.`;
      if (rec?.via) subline += ` It goes via ${rec.via}.`;
    } else {
      headline = c.fastest_aqi != null ? `Air is similar on every route` : "Fastest route";
      subline =
        c.fastest_aqi != null
          ? `Around AQI ${c.fastest_aqi} (${aqiLabel(c.fastest_aqi).toLowerCase()}) whichever way you go, so take the quickest.`
          : c.message;
    }
  } else if (c) {
    headline = c.meaningful
      ? mins > 0
        ? `Worth ${mins} extra minute${mins === 1 ? "" : "s"}`
        : "Less pollution, no extra time"
      : result!.preference === "fastest"
        ? "Fastest route"
        : "Take the fastest route";
    subline =
      c.meaningful && c.reduction_pct != null
        ? `You'd breathe about ${Math.round(c.reduction_pct)}% less pollution than on the fastest route.`
        : c.message;
  }
  const verdict = result && (
    <div className="verdict">
      {verdictOverride ? (
        <p style={{ fontSize: "16px", fontWeight: 500, lineHeight: 1.4 }}>{verdictOverride}</p>
      ) : (
        <>
          <p>{headline}</p>
          <p className="verdict-sub">{subline}</p>
        </>
      )}
      {c && c.meaningful && c.shared_cells_pct != null && c.shared_cells_pct > 60 && (
        <p className="verdict-sub">These routes share most of their air-quality areas, so treat the difference as approximate.</p>
      )}
    </div>
  );

  const cards = result && (
    <div className={`cards${desktop ? "" : " carousel"}`} ref={carousel} key={resultKey}>
      {result.routes.map((r) => (
        <div className="card-slot" data-route={r.id} key={r.id}>
          <RouteCard
            route={r}
            fastestRoute={fastestRoute}
            selected={r.id === selectedId}
            recommended={r.id === result.recommended_id}
            fastest={r.id === result.fastest_id}
            departure={result.data.departure_time}
            onSelect={() => select(r.id)}
            navigateUrl={googleMapsUrl(r, fastestRoute, origin!.location, destination!.location, mode)}
            onNavigate={() => onNavigate(r)}
            navigateHint={me ? (loggedRoutes.has(r.id) ? "Added to your trip log." : "We'll add this trip to your log.") : undefined}
            compact={!desktop}
          />
        </div>
      ))}
    </div>
  );

  const emptyState = !result && !loading && !error && (
    <div className="empty">
      <h2>Where are you heading?</h2>
      <p>Enter a start and destination. We'll compare the routes and show which one has cleaner air, and how much time it costs.</p>
      {me && acct.places.length > 0 && (
        <div className="quick-chips">
          {acct.places.slice(0, 6).map((p) => (
            <button
              key={p.id}
              type="button"
              className="chip"
              onClick={() => {
                const place = { label: p.label === p.name ? p.name : `${p.label}, ${p.name}`, location: { lat: p.lat, lng: p.lng } };
                if (!origin) setOrigin(place);
                else setDestination(place);
              }}
            >
              <Icon name={p.label.toLowerCase() === "home" ? "home" : p.label.toLowerCase() === "work" ? "briefcase" : "star"} size={15} />
              {p.label}
            </button>
          ))}
        </div>
      )}
      {config.accounts_enabled && !me && (
        <button type="button" className="text-btn" onClick={() => setShowAccount(true)}>
          Sign in to save places and keep a trip log
        </button>
      )}
    </div>
  );

  const loadingState = loading && !result && (
    <div className={`cards${desktop ? "" : " carousel"}`}>
      <p className="loading-line" aria-live="polite">
        <span className="spinner small" /> {progressText}
      </p>
      {[0, 1, 2].map((i) => (
        <div className="card-slot" key={i}>
          <RouteCardSkeleton />
        </div>
      ))}
    </div>
  );

  const warnings =
    result &&
    result.warnings.length > 0 &&
    result.warnings.map((w, i) => (
      <p key={i} className="banner warn">
        {w}
      </p>
    ));

  const footer = result && (
    <footer className="data-foot">
      <p>
        {result.data.resolution_note}
        {result.data.oldest_observation && ` Current conditions as of ${fmtTime(result.data.oldest_observation)}.`}
        {result.data.uses_forecast && " Later parts of the trip use the hourly forecast."}
      </p>
      <p>Exposure is PM2.5 multiplied by the minutes you spend in it: a way to compare routes, not a measure of what you breathe, and not medical advice.</p>
      <details>
        <summary>Data sources and cost</summary>
        <p>
          Routes from {result.data.routes_source ?? result.data.provider}, air quality from {result.data.aq_source ?? result.data.provider}.
          {" "}Routes calls {result.usage.routes_calls}, air-quality calls {result.usage.aq_current_calls + result.usage.aq_forecast_calls}
          {" "}(cached {result.usage.aq_cache_hits})
          {result.usage.estimated_cost_usd != null && `, about $${result.usage.estimated_cost_usd.toFixed(4)}`}.
        </p>
        <button type="button" className="text-btn" onClick={downloadTripData}>
          Download trip data
        </button>
      </details>
    </footer>
  );

  const legal = (
    <p className="legal-links">
      <a href="/privacy">Privacy</a>
      <a href="/terms">Terms</a>
      <span>v{config.version}</span>
    </p>
  );

  const errorBox = error && (
    <div className="problem" role="alert">
      <p>{error.message}</p>
      <div className="problem-actions">
        {error.code === "too_far" &&
          error.suggestModes.map((m, i) => (
            <button key={m} type="button" className={`chip${i === error.suggestModes.length - 1 ? " chip-solid" : ""}`} onClick={() => setMode(m)}>
              Go by {MODE_LABEL[m].toLowerCase()}
            </button>
          ))}
        {error.code === "too_far" && (
          <button
            type="button"
            className="chip"
            onClick={() => {
              setOrigin(null);
              setError(null);
              setTimeout(() => document.getElementById("place-origin")?.focus(), 50);
            }}
          >
            Change start point
          </button>
        )}
        {error.code !== "too_far" && error.status !== 400 && error.status !== 422 && (
          <button type="button" className="chip chip-solid" onClick={() => setRetry((n) => n + 1)}>
            Try again
          </button>
        )}
      </div>
    </div>
  );

  const settings = (
    <TripSettings
      preference={preference}
      onPreference={setPreference}
      budget={budget}
      onBudget={setBudget}
      leaveLater={leaveLater}
      onLeaveLater={setLeaveLater}
      departure={departure}
      onDeparture={setDeparture}
    />
  );

  const map = mapsKey ? (
    <RouteMap {...mapProps} />
  ) : config.provider === "google" ? (
    // Google route data must be shown on a Google map: set GOOGLE_MAPS_BROWSER_KEY.
    <SchematicMap {...mapProps} />
  ) : (
    <LeafletMap {...mapProps} />
  );

  let layout: ReactNode;
  if (desktop) {
    layout = (
      <aside className="dpanel">
        <header className="brand">
          <Mark />
          <div className="brand-name">
            <h1>Breatheasy</h1>
            <p>Cleaner-air routes across {config.region.name}</p>
          </div>
          {accountButton}
        </header>
        {banners}
        <AgentBox onPlan={onAgentPlan} />
        {search}
        <ModePicker mode={mode} onMode={setMode} />
        {settings}
        <div className="dresults" aria-live="polite">
          {errorBox}
          {emptyState}
          {loadingState}
          {verdict}
          {cards}
          {warnings}
          {footer}
          {legal}
        </div>
      </aside>
    );
  } else {
    const short = (p: Place | null) => (p?.label ?? "").split(",")[0];
    layout = (
      <>
        <div className={`mtop${searching ? " is-searching" : ""}${collapsed ? " is-collapsed" : ""}`}>
          {collapsed ? (
            <div className="tripbar">
              <button type="button" className="tripbar-main" onClick={() => setEditTrip(true)} aria-label={`Change trip: from ${origin!.label} to ${destination!.label}`}>
                <span className="tripbar-route">
                  <span className="tripbar-from">{short(origin)}</span>
                  <Icon name="chevron" size={14} />
                  <span className="tripbar-to">{short(destination)}</span>
                </span>
                <span className="tripbar-edit">Edit</span>
              </button>
              {accountButton}
            </div>
          ) : (
            <>
              {!searching && (
                <div className="mtop-bar">
                  {tripSet ? (
                    <button type="button" className="chip chip-float" onClick={() => setEditTrip(false)}>
                      Done
                    </button>
                  ) : (
                    <span className="brand-inline">
                      <Mark size={30} />
                      <b>Breatheasy</b>
                    </span>
                  )}
                  {accountButton}
                </div>
              )}
              <AgentBox onPlan={onAgentPlan} />
              {search}
              {!searching && !tripSet && <ModePicker mode={mode} onMode={setMode} />}
            </>
          )}
          {banners}
        </div>
        {!searching && (
          <BottomSheet snap={snap} onSnap={setSnap} label="Routes">
            <div aria-live="polite">
              {tripSet && (
                <div className="mcontrols">
                  <ModePicker mode={mode} onMode={setMode} compact />
                  <button
                    type="button"
                    className={`pref-chip${showSettings ? " on" : ""}`}
                    aria-expanded={showSettings}
                    onClick={() => {
                      setShowSettings((v) => !v);
                      if (snap === "peek") setSnap("half");
                    }}
                  >
                    <span>{settingsSummary(preference, budget, leaveLater, departure)}</span>
                  </button>
                </div>
              )}
              {tripSet && showSettings && settings}
              {errorBox}
              {emptyState}
              {loadingState}
              {verdict}
              {cards}
              {warnings}
              {result ? (
                <details className="about-data">
                  <summary>
                    <Icon name="info" size={16} /> About this data
                  </summary>
                  <Legend explain />
                  {footer}
                  {legal}
                </details>
              ) : (
                legal
              )}
            </div>
          </BottomSheet>
        )}
      </>
    );
  }

  return (
    <div className={`shell${desktop ? " is-desktop" : " is-mobile"}`}>
      <main className="stage" style={{ bottom: stageBottom }}>
        {map}
        <Legend />
        {loading && result && (
          <div className="map-busy">
            <span className="spinner small" /> {progressText}
          </div>
        )}
      </main>
      {layout}
      {showAccount && config.accounts_enabled && (
        <AccountPanel
          clientId={config.google_oauth_client_id}
          plans={config.plans}
          onClose={() => setShowAccount(false)}
          onUsePlace={(p, as) => {
            const place = { label: p.label, location: { lat: p.lat, lng: p.lng } };
            if (as === "origin") setOrigin(place);
            else setDestination(place);
            setShowAccount(false);
          }}
        />
      )}
      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}
    </div>
  );
}
