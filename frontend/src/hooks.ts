import { useEffect, useState } from "react";

export function useMediaQuery(q: string): boolean {
  const [match, setMatch] = useState(() => typeof window !== "undefined" && window.matchMedia(q).matches);
  useEffect(() => {
    const m = window.matchMedia(q);
    const on = () => setMatch(m.matches);
    on();
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, [q]);
  return match;
}

export const useIsDesktop = () => useMediaQuery("(min-width: 900px)");

export function useOnline(): boolean {
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);
  return online;
}

// ---------- recent searches: kept on this device only ----------
export interface RecentPlace {
  label: string;
  lat: number;
  lng: number;
}
const RECENTS_KEY = "br.recents.v1";

export function readRecents(): RecentPlace[] {
  try {
    const v = JSON.parse(localStorage.getItem(RECENTS_KEY) || "[]");
    return Array.isArray(v) ? v.slice(0, 6) : [];
  } catch {
    return [];
  }
}

export function pushRecent(p: RecentPlace): void {
  if (p.label.startsWith("My location")) return;
  try {
    const list = readRecents().filter((r) => !(Math.abs(r.lat - p.lat) < 1e-5 && Math.abs(r.lng - p.lng) < 1e-5));
    localStorage.setItem(RECENTS_KEY, JSON.stringify([p, ...list].slice(0, 6)));
  } catch {
    /* storage blocked: recents are a convenience only */
  }
}

export function clearRecents(): void {
  try {
    localStorage.removeItem(RECENTS_KEY);
  } catch {
    /* ignore */
  }
}
