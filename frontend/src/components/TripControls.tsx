import { useState } from "react";
import { MODE_LABEL } from "../format";
import type { Preference, TravelMode } from "../types";
import { Icon } from "./Icon";

const MODES: { id: TravelMode; icon: string; short: string }[] = [
  { id: "WALK", icon: "walk", short: "Walk" },
  { id: "BICYCLE", icon: "bike", short: "Cycle" },
  { id: "TWO_WHEELER", icon: "scooter", short: "2-wheeler" },
  { id: "DRIVE", icon: "car", short: "Car" },
];

export const ANY_TIME = 180; // minutes; "any extra time"

export const PREFS: { id: Preference; label: string; hint: string }[] = [
  { id: "cleanest_air", label: "Cleanest air", hint: "The route with the cleanest air, even if it takes longer. Good for runs and unhurried walks." },
  { id: "balanced", label: "Balanced", hint: "Cleaner air, but only a few minutes out of your way." },
  { id: "fastest", label: "Fastest", hint: "The quickest route, with its air quality shown." },
];

export function ModePicker({ mode, onMode, compact = false }: { mode: TravelMode; onMode: (m: TravelMode) => void; compact?: boolean }) {
  return (
    <div className={`modes${compact ? " modes-compact" : ""}`} role="radiogroup" aria-label="How are you travelling?">
      {MODES.map((m) => (
        <button
          key={m.id}
          type="button"
          role="radio"
          aria-checked={mode === m.id}
          className={`mode${mode === m.id ? " on" : ""}`}
          onClick={() => onMode(m.id)}
          aria-label={compact ? MODE_LABEL[m.id] : undefined}
          title={compact ? MODE_LABEL[m.id] : undefined}
        >
          <Icon name={m.icon} size={19} />
          <span className="mode-long">{MODE_LABEL[m.id]}</span>
          <span className="mode-short" aria-hidden>
            {m.short}
          </span>
        </button>
      ))}
    </div>
  );
}

interface SettingsProps {
  preference: Preference;
  onPreference: (p: Preference) => void;
  budget: number;
  onBudget: (n: number) => void;
  leaveLater: boolean;
  onLeaveLater: (b: boolean) => void;
  departure: string;
  onDeparture: (s: string) => void;
  sensitive: boolean;
  onSensitive: (b: boolean) => void;
}

export function TripSettings(p: SettingsProps) {
  const [open, setOpen] = useState<null | "budget" | "time">(null);
  const departLabel =
    p.leaveLater && p.departure
      ? new Date(p.departure).toLocaleString("en-IN", { weekday: "short", hour: "numeric", minute: "2-digit" })
      : "Leave now";

  return (
    <div className="settings">
      <div className="prefs" role="radiogroup" aria-label="Route preference">
        {PREFS.map((x) => (
          <button
            key={x.id}
            type="button"
            role="radio"
            aria-checked={p.preference === x.id}
            className={`pref${p.preference === x.id ? " on" : ""}`}
            onClick={() => p.onPreference(x.id)}
          >
            {x.label}
          </button>
        ))}
      </div>
      <p className="pref-hint">{PREFS.find((x) => x.id === p.preference)?.hint}</p>

      <label className="toggle sensitive-toggle">
        <input type="checkbox" checked={p.sensitive} onChange={(e) => p.onSensitive(e.target.checked)} />
        <span>
          <b>I'm sensitive to pollution</b>
          <small>Asthma, pregnancy, older age, or travelling with children: stays further from busy roads and pollution spots, and reminds you about masks sooner.</small>
        </span>
      </label>

      <div className="setting-chips">
        <button
          type="button"
          className={`chip${open === "budget" ? " on" : ""}`}
          aria-expanded={open === "budget"}
          onClick={() => setOpen(open === "budget" ? null : "budget")}
        >
          {p.budget >= ANY_TIME ? "Any extra time" : p.budget === 0 ? "No extra time" : `Up to ${p.budget} min longer`}
        </button>
        <button
          type="button"
          className={`chip${open === "time" ? " on" : ""}`}
          aria-expanded={open === "time"}
          onClick={() => setOpen(open === "time" ? null : "time")}
        >
          {departLabel}
        </button>
      </div>

      {open === "budget" && (
        <div className="popover budget">
          <label htmlFor="budget-range">How much longer would you travel for cleaner air?</label>
          <input
            id="budget-range"
            type="range"
            min={0}
            max={60}
            step={5}
            value={Math.min(p.budget, 60)}
            disabled={p.budget >= ANY_TIME}
            onChange={(e) => p.onBudget(Number(e.target.value))}
          />
          <span className="budget-scale" aria-hidden>
            <i>0 min</i>
            <i>30</i>
            <i>60 min</i>
          </span>
          <label className="toggle">
            <input
              type="checkbox"
              checked={p.budget >= ANY_TIME}
              onChange={(e) => p.onBudget(e.target.checked ? ANY_TIME : 45)}
            />
            <span>Any extra time: show me the cleanest air, however long</span>
          </label>
        </div>
      )}
      {open === "time" && (
        <div className="popover">
          <div className="seg">
            <button type="button" className={!p.leaveLater ? "on" : ""} onClick={() => p.onLeaveLater(false)}>
              Leave now
            </button>
            <button type="button" className={p.leaveLater ? "on" : ""} onClick={() => p.onLeaveLater(true)}>
              Leave later
            </button>
          </div>
          {p.leaveLater && (
            <input
              type="datetime-local"
              value={p.departure}
              onChange={(e) => p.onDeparture(e.target.value)}
              aria-label="Departure time"
            />
          )}
          <p className="pref-hint">Later departures use the hourly air-quality forecast.</p>
        </div>
      )}
    </div>
  );
}

/** One-line summary of the trip settings, for the compact phone controls. */
export function settingsSummary(preference: Preference, budget: number, leaveLater: boolean, departure: string) {
  const pref = PREFS.find((x) => x.id === preference)?.label ?? "";
  const time =
    preference === "fastest" ? "" : budget >= ANY_TIME ? " · any time" : budget === 0 ? " · no extra time" : ` · +${budget} min`;
  const when =
    leaveLater && departure
      ? ` · ${new Date(departure).toLocaleString("en-IN", { weekday: "short", hour: "numeric", minute: "2-digit" })}`
      : "";
  return `${pref}${time}${when}`;
}
