import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import * as api from "./api";
import type { Me, SavedPlace } from "./types";

interface AccountState {
  enabled: boolean;
  me: Me | null;
  loading: boolean;
  places: SavedPlace[];
  error: string | null;
  signIn: (credential: string) => Promise<void>;
  signOut: () => Promise<void>;
  reload: () => Promise<void>;
  refreshPlaces: () => Promise<void>;
  setError: (e: string | null) => void;
}

const Ctx = createContext<AccountState | null>(null);

export function AccountProvider({ enabled, children }: { enabled: boolean; children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [places, setPlaces] = useState<SavedPlace[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refreshPlaces = useCallback(async () => {
    try {
      setPlaces(await api.listPlaces());
    } catch {
      setPlaces([]);
    }
  }, []);

  const reload = useCallback(async () => {
    if (!enabled) return;
    try {
      const r = await api.getMe();
      setMe(r.user);
      if (r.user) await refreshPlaces();
      else setPlaces([]);
    } catch {
      setMe(null);
    } finally {
      setLoading(false);
    }
  }, [enabled, refreshPlaces]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const signIn = useCallback(
    async (credential: string) => {
      setError(null);
      try {
        const r = await api.signInWithGoogle(credential);
        setMe(r.user);
        await refreshPlaces();
      } catch (e) {
        setError((e as Error).message);
      }
    },
    [refreshPlaces],
  );

  const signOut = useCallback(async () => {
    try {
      await api.signOut();
    } finally {
      window.google?.accounts.id.disableAutoSelect();
      setMe(null);
      setPlaces([]);
    }
  }, []);

  const value = useMemo(
    () => ({ enabled, me, loading, places, error, signIn, signOut, reload, refreshPlaces, setError }),
    [enabled, me, loading, places, error, signIn, signOut, reload, refreshPlaces],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAccount(): AccountState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAccount outside AccountProvider");
  return v;
}

// ---------- Google Identity Services ----------
declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (cfg: Record<string, unknown>) => void;
          renderButton: (el: HTMLElement, opts: Record<string, unknown>) => void;
          disableAutoSelect: () => void;
        };
      };
    };
  }
}

let gisPromise: Promise<void> | null = null;
function loadGis(): Promise<void> {
  if (window.google?.accounts?.id) return Promise.resolve();
  gisPromise ??= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => {
      gisPromise = null;
      reject(new Error("Couldn't load Google sign-in."));
    };
    document.head.appendChild(s);
  });
  return gisPromise;
}

export function GoogleSignInButton({ clientId, width = 260 }: { clientId: string; width?: number }) {
  const { signIn, setError } = useAccount();
  const el = useRef<HTMLDivElement>(null);
  const cb = useRef(signIn);
  cb.current = signIn;

  useEffect(() => {
    let cancelled = false;
    loadGis()
      .then(() => {
        if (cancelled || !el.current || !window.google) return;
        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: (r: { credential?: string }) => r.credential && cb.current(r.credential),
          ux_mode: "popup",
          auto_select: false,
          itp_support: true,
        });
        const dark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
        window.google.accounts.id.renderButton(el.current, {
          type: "standard",
          theme: dark ? "filled_black" : "outline",
          size: "large",
          shape: "pill",
          text: "signin_with",
          logo_alignment: "left",
          width,
        });
      })
      .catch((e: Error) => setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [clientId, width, setError]);

  return <div ref={el} className="gsi-button" />;
}
