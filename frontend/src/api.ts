import type {
  AppConfig,
  LatLng,
  Me,
  PlanStatus,
  Place,
  Preference,
  RouteResponse,
  SavedPlace,
  Suggestion,
  Summary,
  TravelMode,
  TripIn,
  TripOut,
} from "./types";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export class ApiError extends Error {
  status: number;
  code: string | null;
  suggestModes: TravelMode[];
  constructor(message: string, status: number, code: string | null = null, suggestModes: TravelMode[] = []) {
    super(message);
    this.status = status;
    this.code = code;
    this.suggestModes = suggestModes;
  }
}

/** Plain-language messages for failures the server didn't explain. Never show a bare status code. */
function friendly(status: number): string {
  if (status === 429) return "Lots of searches in a short time. Wait a minute, then try again.";
  if (status === 401) return "Please sign in again.";
  if (status === 404) return "That couldn't be found.";
  if (status === 504 || status === 408) return "That search took too long. Try again, or choose a closer destination.";
  if (status >= 500) return "Breatheasy is having trouble right now. Try again in a minute.";
  return "Something didn't work. Check the start and destination, then try again.";
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, {
      credentials: "include",
      ...init,
      // Required by the server's CSRF guard on POST/DELETE; harmless on GET.
      headers: { "X-Requested-With": "breatheasy", ...(init.headers ?? {}) },
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(navigator.onLine ? "Can't reach Breatheasy right now." : "You're offline.", 0);
  }
  if (!res.ok) {
    let detail = friendly(res.status);
    let code: string | null = null;
    let suggest: TravelMode[] = [];
    try {
      const j = await res.json();
      // Only show server text written for people (our own messages carry a code or are plain strings
      // from our API); validation dumps and proxy pages fall back to the friendly text.
      if (typeof j.detail === "string" && res.status < 500) detail = j.detail;
      if (typeof j.detail === "string" && j.code) detail = j.detail;
      code = typeof j.code === "string" ? j.code : null;
      if (Array.isArray(j.suggest_modes)) suggest = j.suggest_modes;
    } catch {
      /* not JSON, e.g. a load balancer timeout page */
    }
    throw new ApiError(detail, res.status, code, suggest);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const json = (method: string, body?: unknown, extra: RequestInit = {}): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
  ...extra,
});

export const getConfig = () => req<AppConfig>("/api/config");

export const autocomplete = (q: string, session: string, signal?: AbortSignal) =>
  req<Suggestion[]>(`/api/places/autocomplete?q=${encodeURIComponent(q)}&session=${session}`, { signal });

export const placeDetails = async (id: string, session: string, label?: string): Promise<Place> => {
  const d = await req<{ name: string; location: LatLng }>(
    `/api/places/${encodeURIComponent(id)}?session=${session}`,
  );
  // Prefer the suggestion text the person tapped (the server asks Google only for
  // the cheaper location fields).
  return { label: label || d.name, location: d.location };
};

export interface RouteQuery {
  origin: LatLng;
  destination: LatLng;
  mode: TravelMode;
  preference: Preference;
  max_extra_minutes: number;
  departure_time?: string | null;
  sensitive?: boolean;
}

/** Route search with a hard client-side limit so the app never hangs on a spinner. */
export async function planRoutes(q: RouteQuery, signal?: AbortSignal, timeoutMs = 30000): Promise<RouteResponse> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(new DOMException("timeout", "TimeoutError")), timeoutMs);
  const onAbort = () => ctrl.abort(signal?.reason);
  signal?.addEventListener("abort", onAbort);
  try {
    return await req<RouteResponse>("/api/routes", { ...json("POST", q), signal: ctrl.signal });
  } catch (e) {
    if (ctrl.signal.aborted && !signal?.aborted) throw new ApiError(friendly(504), 504, "slow");
    throw e;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

export interface AgentRequest {
  query: string;
  origin: LatLng;
  sensitive?: boolean;
}

export interface AgentResponse {
  verdict: string;
  plan: RouteResponse | null;
  mode?: import("./types").TravelMode | null;
}

export async function runAgent(q: AgentRequest, signal?: AbortSignal, timeoutMs = 60000): Promise<AgentResponse> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(new DOMException("timeout", "TimeoutError")), timeoutMs);
  const onAbort = () => ctrl.abort(signal?.reason);
  signal?.addEventListener("abort", onAbort);
  try {
    return await req<AgentResponse>("/api/agent", { ...json("POST", q), signal: ctrl.signal });
  } catch (e) {
    if (ctrl.signal.aborted && !signal?.aborted) throw new ApiError(friendly(504), 504, "slow");
    throw e;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

// ---------- account ----------
export const getMe = () => req<{ user: Me | null; accounts_enabled: boolean; plan?: PlanStatus | null }>("/api/me");
export const signInWithGoogle = (credential: string) =>
  req<{ user: Me }>("/api/auth/google", json("POST", { credential }));
export const signOut = () => req<void>("/api/auth/logout", json("POST"));
export const signOutEverywhere = () => req<void>("/api/auth/logout-all", json("POST"));
export const deleteAccount = () => req<void>("/api/me", json("DELETE"));
export const exportData = () => req<unknown>("/api/me/export");

export const listPlaces = () => req<SavedPlace[]>("/api/me/places");
export const addPlace = (p: { label: string; name: string; lat: number; lng: number }) =>
  req<SavedPlace>("/api/me/places", json("POST", p));
export const removePlace = (id: string) => req<void>(`/api/me/places/${encodeURIComponent(id)}`, json("DELETE"));

export const listTrips = () => req<TripOut[]>("/api/me/trips?limit=100");
// keepalive lets the request finish even though the page is navigating to Google Maps.
export const logTrip = (t: TripIn) => req<TripOut>("/api/me/trips", json("POST", t, { keepalive: true }));
export const removeTrip = (id: string) => req<void>(`/api/me/trips/${encodeURIComponent(id)}`, json("DELETE"));
export const clearTrips = () => req<void>("/api/me/trips", json("DELETE"));
export const getSummary = () => req<Summary>("/api/me/summary");

// ---------- Breatheasy Plus (Razorpay) ----------
export interface Subscription {
  subscription_id: string;
  key_id: string;
  amount_inr: number;
  name: string;
  email: string;
}
export const subscribe = (period: "monthly" | "yearly") =>
  req<Subscription>("/api/billing/subscribe", json("POST", { period }));
export const verifyPayment = (p: {
  razorpay_payment_id: string;
  razorpay_subscription_id: string;
  razorpay_signature: string;
  period: "monthly" | "yearly";
}) => req<{ plan: string; plus_until: string | null }>("/api/billing/verify", json("POST", p));
export const cancelPlus = () => req<{ plan: string; plus_until: string | null }>("/api/billing/cancel", json("POST"));


/** Anonymous usage count (event + city area only). Never blocks or throws. */
export function postEvent(event: "maps_open" | "share" | "shared_open", at?: LatLng | null): void {
  try {
    void fetch("/api/event", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "breatheasy" },
      body: JSON.stringify({ event, lat: at?.lat ?? null, lng: at?.lng ?? null }),
      keepalive: true,
    }).catch(() => undefined);
  } catch {
    /* ignore */
  }
}
