import { useCallback, useEffect, useState } from "react";
import * as api from "../api";
import { GoogleSignInButton, useAccount } from "../account";
import { MODE_LABEL, fmtDistance, fmtDuration } from "../format";
import type { Summary, TravelMode, TripOut } from "../types";

interface Props {
  clientId: string;
  onClose: () => void;
  onUsePlace: (p: { label: string; lat: number; lng: number }, as: "origin" | "destination") => void;
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function AccountPanel({ clientId, onClose, onUsePlace }: Props) {
  const acct = useAccount();
  const { me, places } = acct;
  const [trips, setTrips] = useState<TripOut[] | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState("");

  const load = useCallback(async () => {
    if (!me) return;
    try {
      const [t, s] = await Promise.all([api.listTrips(), api.getSummary()]);
      setTrips(t);
      setSummary(s);
    } catch (e) {
      setMsg((e as Error).message);
    }
  }, [me]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function run(fn: () => Promise<unknown>, done?: string) {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      if (done) setMsg(done);
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function download() {
    await run(async () => {
      const data = await api.exportData();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "breatheasy-my-data.json";
      a.click();
      URL.revokeObjectURL(a.href);
    });
  }

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <section className="sheet" role="dialog" aria-modal="true" aria-label="Your account" onClick={(e) => e.stopPropagation()}>
        <header className="sheet-head">
          <h2>{me ? "Your account" : "Sign in"}</h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden>
              <path d="M6 6l12 12M18 6 6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </header>

        {!me && (
          <div className="signin-block">
            <p>Sign in to save places like Home and Work, and keep a log of the trips you take with the PM2.5 exposure you avoided.</p>
            <GoogleSignInButton clientId={clientId} />
            {acct.error && <p className="field-error">{acct.error}</p>}
            <p className="fine">
              We store your name, email, saved places and the trips you choose to log. Nothing else. See the{" "}
              <a href="/privacy">privacy policy</a>.
            </p>
          </div>
        )}

        {me && (
          <>
            <div className="profile">
              {me.picture ? <img src={me.picture} alt="" referrerPolicy="no-referrer" /> : <span className="avatar-fallback">{(me.name || me.email)[0]}</span>}
              <div>
                <strong>{me.name || me.email}</strong>
                <span>{me.email}</span>
              </div>
            </div>

            {summary && (
              <div className="summary-grid">
                <div>
                  <span className="k">{summary.trips}</span>
                  <span className="l">trips logged</span>
                </div>
                <div>
                  <span className="k">{Math.round(summary.minutes_travelled)}</span>
                  <span className="l">minutes travelled</span>
                </div>
                <div>
                  <span className="k">{summary.avoided_pct != null ? `${Math.max(0, summary.avoided_pct).toFixed(0)}%` : "—"}</span>
                  <span className="l">less PM2.5 than the fastest routes</span>
                </div>
              </div>
            )}

            <h3>Saved places</h3>
            {places.length === 0 && <p className="muted">Save a place from the search box with the star button.</p>}
            <ul className="list">
              {places.map((p) => (
                <li key={p.id}>
                  <div>
                    <strong>{p.label}</strong>
                    <span>{p.name}</span>
                  </div>
                  <div className="row-actions">
                    <button type="button" className="chip-btn" onClick={() => onUsePlace(p, "origin")}>From</button>
                    <button type="button" className="chip-btn" onClick={() => onUsePlace(p, "destination")}>To</button>
                    <button
                      type="button"
                      className="chip-btn danger"
                      disabled={busy}
                      onClick={() => run(async () => { await api.removePlace(p.id); await acct.refreshPlaces(); })}
                    >
                      Remove
                    </button>
                  </div>
                </li>
              ))}
            </ul>

            <h3>Trip log</h3>
            {trips === null && <p className="muted">Loading…</p>}
            {trips?.length === 0 && (
              <p className="muted">Trips appear here when you start a route in Google Maps.</p>
            )}
            <ul className="list trips">
              {trips?.map((t) => {
                const red =
                  t.exposure_pm25 != null && t.fastest_exposure_pm25
                    ? ((t.fastest_exposure_pm25 - t.exposure_pm25) / t.fastest_exposure_pm25) * 100
                    : null;
                return (
                  <li key={t.id}>
                    <div>
                      <strong>
                        {t.origin.name} to {t.destination.name}
                      </strong>
                      <span className="trip-meta">
                        <span>{fmtDate(t.departure_time)}</span>
                        <span>{MODE_LABEL[t.mode as TravelMode] ?? t.mode}, {fmtDuration(t.duration_s)}, {fmtDistance(t.distance_m)}</span>
                        {red != null && red > 0.5 && <b className="good-text">{red.toFixed(0)}% less PM2.5 than the fastest route</b>}
                      </span>
                    </div>
                    <div className="row-actions">
                      <button
                        type="button"
                        className="chip-btn danger"
                        disabled={busy}
                        onClick={() => run(async () => { await api.removeTrip(t.id); await load(); })}
                      >
                        Delete
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>

            <h3>Your data</h3>
            <div className="data-actions">
              <button type="button" className="secondary-btn" disabled={busy} onClick={download}>Download my data</button>
              <button
                type="button"
                className="secondary-btn"
                disabled={busy || !trips?.length}
                onClick={() => run(async () => { await api.clearTrips(); await load(); }, "Trip log cleared.")}
              >
                Clear trip log
              </button>
              <button type="button" className="secondary-btn" disabled={busy} onClick={() => run(acct.signOut)}>Sign out</button>
              <button
                type="button"
                className="secondary-btn"
                disabled={busy}
                onClick={() => run(async () => { await api.signOutEverywhere(); await acct.reload(); })}
              >
                Sign out on all devices
              </button>
            </div>

            <details className="danger-zone">
              <summary>Delete account</summary>
              <p>This permanently deletes your account, saved places and trip log. Type DELETE to confirm.</p>
              <input value={confirmDelete} onChange={(e) => setConfirmDelete(e.target.value)} aria-label="Type DELETE to confirm" />
              <button
                type="button"
                className="danger-btn"
                disabled={busy || confirmDelete !== "DELETE"}
                onClick={() => run(async () => { await api.deleteAccount(); await acct.reload(); onClose(); })}
              >
                Delete my account
              </button>
            </details>
          </>
        )}

        {msg && <p className="sheet-msg" role="status">{msg}</p>}
        <footer className="sheet-foot">
          <a href="/privacy">Privacy</a>
          <a href="/terms">Terms</a>
        </footer>
      </section>
    </div>
  );
}
