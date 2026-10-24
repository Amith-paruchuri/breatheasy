import { useEffect, useRef, useState } from "react";
import { autocomplete, placeDetails } from "../api";
import { pushRecent, readRecents, type RecentPlace } from "../hooks";
import type { Place, SavedPlace, Suggestion } from "../types";
import { Icon } from "./Icon";

interface Props {
  label: string;
  role: "origin" | "destination";
  value: Place | null;
  onChange: (p: Place | null) => void;
  saved?: SavedPlace[];
  onSave?: (label: string) => Promise<void>; // shown when signed in and a place is chosen
  onFocusChange?: (focused: boolean) => void;
}

const newSession = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2) + Date.now().toString(36);

export function PlaceInput({ label, role, value, onChange, saved = [], onSave, onFocusChange }: Props) {
  const [text, setText] = useState(value?.label ?? "");
  const [items, setItems] = useState<Suggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveLabel, setSaveLabel] = useState("");
  const [savedMsg, setSavedMsg] = useState<string | null>(null);
  const [recents, setRecents] = useState<RecentPlace[]>([]);
  const session = useRef(newSession());
  const input = useRef<HTMLInputElement>(null);
  const listId = `sugg-${role}`;

  useEffect(() => {
    setText(value?.label ?? "");
    setSaving(false);
    setSavedMsg(null);
    if (!value || !value.label.startsWith("My location")) setNote(null);
  }, [value]);

  useEffect(() => {
    if (!open || text.trim().length < 2 || text === value?.label) {
      setItems([]);
      return;
    }
    const ctrl = new AbortController();
    const t = setTimeout(async () => {
      try {
        setItems(await autocomplete(text.trim(), session.current, ctrl.signal));
        setErr(null);
      } catch (e) {
        if ((e as Error).name !== "AbortError") setErr((e as Error).message);
      }
    }, 220);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [text, open, value?.label]);

  function choose(p: Place) {
    onChange(p);
    pushRecent({ label: p.label, lat: p.location.lat, lng: p.location.lng });
    setOpen(false);
    input.current?.blur();
  }

  async function pick(s: Suggestion) {
    setBusy(true);
    try {
      const p = await placeDetails(s.place_id, session.current);
      choose(p);
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
      session.current = newSession(); // a billing session ends with the details call
    }
  }

  function useMyLocation() {
    if (!navigator.geolocation) {
      setErr("This browser can't share your location. Type a place instead.");
      return;
    }
    setBusy(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setBusy(false);
        const acc = pos.coords.accuracy;
        // Laptops without GPS often locate by Wi-Fi or IP and can be kilometres off.
        const rough = acc > 500;
        choose({
          label: rough ? "My location (approximate)" : "My location",
          location: { lat: pos.coords.latitude, lng: pos.coords.longitude },
        });
        setNote(
          rough
            ? `Your device could only place you within about ${acc >= 1000 ? `${Math.round(acc / 1000)} km` : `${Math.round(acc)} m`}. Check the start pin on the map, or type your start for accurate routes.`
            : null,
        );
      },
      (e) => {
        setBusy(false);
        setErr(
          e.code === e.PERMISSION_DENIED
            ? "Location access is off for this site. Allow it in your browser settings, or type a place."
            : "Couldn't get your location. Type a place instead.",
        );
      },
      { enableHighAccuracy: true, timeout: 10000 },
    );
  }

  async function save(lbl: string) {
    if (!onSave || !lbl.trim()) return;
    try {
      await onSave(lbl.trim().slice(0, 40));
      setSaving(false);
      setSaveLabel("");
      setSavedMsg(`Saved as ${lbl.trim()}`);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  const typing = text.trim().length >= 2 && text !== value?.label;
  const showQuick = open && !typing;
  const showList = open && (typing ? items.length > 0 : true);

  return (
    <div className={`place place-${role}${open ? " is-open" : ""}`}>
      <span className="place-mark" aria-hidden />
      <div className="place-field">
        <label className="sr-only" htmlFor={`place-${role}`}>
          {label}
        </label>
        <input
          ref={input}
          id={`place-${role}`}
          placeholder={label}
          value={text}
          autoComplete="off"
          enterKeyHint="search"
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          onFocus={() => {
            setRecents(readRecents());
            setOpen(true);
            onFocusChange?.(true);
          }}
          onBlur={() =>
            setTimeout(() => {
              setOpen(false);
              onFocusChange?.(false);
            }, 160)
          }
          onChange={(e) => {
            setText(e.target.value);
            setErr(null);
            if (value) onChange(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && items[0]) pick(items[0]);
            if (e.key === "Escape") input.current?.blur();
          }}
        />
        {busy && <span className="spinner small place-spin" aria-label="Loading" />}
        {value && !busy && (
          <button
            type="button"
            className="place-clear"
            aria-label={`Clear ${label.toLowerCase()}`}
            onClick={() => {
              onChange(null);
              setText("");
              input.current?.focus();
            }}
          >
            <Icon name="x" size={16} />
          </button>
        )}
      </div>
      {onSave && value && !savedMsg && !value.label.startsWith("My location") && (
        <button
          type="button"
          className={`place-action${saving ? " on" : ""}`}
          aria-label="Save this place"
          aria-expanded={saving}
          onClick={() => setSaving((v) => !v)}
        >
          <Icon name="star" size={18} />
        </button>
      )}

      {showList && (
        <ul className="suggestions" id={listId} role="listbox" aria-label={`${label} suggestions`}>
          {showQuick && role === "origin" && (
            <li>
              <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={useMyLocation}>
                <Icon name="locate" />
                <span>
                  <strong>Your location</strong>
                </span>
              </button>
            </li>
          )}
          {showQuick &&
            saved.slice(0, 5).map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => choose({ label: p.label === p.name ? p.name : `${p.label}, ${p.name}`, location: { lat: p.lat, lng: p.lng } })}
                >
                  <Icon name={p.label.toLowerCase() === "home" ? "home" : p.label.toLowerCase() === "work" ? "briefcase" : "star"} />
                  <span>
                    <strong>{p.label}</strong>
                    <em>{p.name}</em>
                  </span>
                </button>
              </li>
            ))}
          {showQuick &&
            recents.map((r) => (
              <li key={`${r.lat},${r.lng}`}>
                <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => choose({ label: r.label, location: { lat: r.lat, lng: r.lng } })}>
                  <Icon name="clock" />
                  <span>
                    <strong>{r.label}</strong>
                  </span>
                </button>
              </li>
            ))}
          {showQuick && role === "destination" && saved.length === 0 && recents.length === 0 && (
            <li className="suggest-hint">Search for a place in Delhi-NCR</li>
          )}
          {typing &&
            items.map((s) => (
              <li key={s.place_id}>
                <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => pick(s)}>
                  <Icon name="pin" />
                  <span>
                    <strong>{s.primary}</strong>
                    {s.secondary && <em>{s.secondary}</em>}
                  </span>
                </button>
              </li>
            ))}
        </ul>
      )}

      {err && <p className="field-error">{err}</p>}
      {note && !err && <p className="place-note">{note}</p>}
      {savedMsg && <p className="field-ok">{savedMsg}</p>}
      {saving && (
        <div className="save-row">
          {["Home", "Work", "College"].map((l) => (
            <button key={l} type="button" className="chip" onClick={() => save(l)}>
              {l}
            </button>
          ))}
          <input
            placeholder="Other name"
            value={saveLabel}
            maxLength={40}
            onChange={(e) => setSaveLabel(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && save(saveLabel)}
            aria-label="Name for this saved place"
          />
          <button type="button" className="chip chip-solid" disabled={!saveLabel.trim()} onClick={() => save(saveLabel)}>
            Save
          </button>
        </div>
      )}
    </div>
  );
}
