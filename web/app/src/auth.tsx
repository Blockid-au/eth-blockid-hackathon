import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError, isMock, type Me } from "./api";

const DEMO_OFF = "blockid-demo-off";
function demoOff(): boolean {
  try { return localStorage.getItem(DEMO_OFF) === "1"; } catch { return false; }
}
function setDemoOff(v: boolean) {
  try { if (v) localStorage.setItem(DEMO_OFF, "1"); else localStorage.removeItem(DEMO_OFF); } catch { /* private mode */ }
}
import type { DictKey } from "./dict";

interface AuthState {
  me: Me | null;
  loading: boolean;
  busy: boolean;
  refresh: () => Promise<Me | null>;
  connect: () => Promise<Me | null>;
  /** Instant guest sign-in: a key is created in this browser and signs in silently (no wallet, no sign-up). */
  tryDemo: () => Promise<Me | null>;
  /** Switch to the shared demo account of the project. */
  useDemo: () => Promise<Me | null>;
  /** Google sign-in (Gmail): the Google ID token is bound to a key created in this browser. */
  google: (credential: string) => Promise<(Me & { newWallet?: string[] }) | null>;
  login: (u: string, p: string) => Promise<Me>;
  logout: () => Promise<void>;
  setMe: (m: Me | null) => void;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const m = await api.me();
      setMe(m);
      return m;
    } catch {
      setMe(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  // First visit: open the project's demo account straight away (no login). Signing out turns this off for this browser.
  useEffect(() => {
    (async () => {
      const m = await refresh();
      if (m || demoOff() || isMock) return;
      try {
        await api.demoLogin();
        await refresh();
      } catch {
        /* demo account not enabled: stay signed out */
      }
    })();
  }, [refresh]);

  const connect = useCallback(async () => {
    setBusy(true);
    try {
      const { signInWithEthereum } = await import("./wallet");
      const r = await signInWithEthereum();
      const m = (await refresh()) ?? { address: r.address, role: r.role };
      setMe(m);
      return m;
    } finally {
      setBusy(false);
    }
  }, [refresh]);

  const tryDemo = useCallback(async () => {
    if (me?.address) return me;
    setBusy(true);
    try {
      try {
        setDemoOff(false);
        await api.demoLogin(); // the project's demo account when it is enabled
        const m = await refresh();
        if (m) return m;
      } catch {
        /* fall back to a key created in this browser */
      }
      const { signInWithDeviceKey } = await import("./devicewallet");
      await signInWithDeviceKey({ method: "guest" });
      return await refresh();
    } finally {
      setBusy(false);
    }
  }, [me, refresh]);

  const google = useCallback(async (credential: string) => {
    setBusy(true);
    try {
      const { signInWithDeviceKey } = await import("./devicewallet");
      const r = await signInWithDeviceKey({ method: "google", credential });
      const m = await refresh();
      // a new key was made on this browser, but the account already has a wallet: the page offers the restore
      return m && r.new_wallet && r.wallets?.length ? { ...m, newWallet: r.wallets } : m;
    } finally {
      setBusy(false);
    }
  }, [refresh]);

  const login = useCallback(async (u: string, p: string) => {
    const r = await api.login(u, p);
    const m: Me = (await refresh()) ?? { username: u, role: r.role, must_change: r.must_change };
    if (r.must_change && !m.must_change) m.must_change = true;
    setMe({ ...m });
    return m;
  }, [refresh]);

  const useDemo = useCallback(async () => {
    setDemoOff(false);
    await api.demoLogin();
    return refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    setDemoOff(true);
    try {
      await api.logout();
    } catch {
      /* ignore */
    }
    setMe(null);
  }, []);

  const value = useMemo(() => ({ me, loading, busy, refresh, connect, tryDemo, useDemo, google, login, logout, setMe }), [me, loading, busy, refresh, connect, tryDemo, useDemo, google, login, logout]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("AuthProvider missing");
  return v;
}

/** Map any thrown error to a translatable message key, or a raw string from the API. */
export function errText(e: unknown, t: (k: DictKey) => string): string {
  if (e instanceof Error && e.name === "KeyError") {  // devicewallet.KeyError: the message is a dictionary key
    const k = e as Error & { key: string; vars?: Record<string, string> };
    return (t as (k: DictKey, v?: Record<string, string>) => string)(k.key as DictKey, k.vars);
  }
  if (e instanceof Error && e.name === "WalletError") {
    const code = (e as Error & { code?: string }).code;
    if (code === "nomm") return t("toast.nomm");
    if (code === "rejected") return t("err.rejected");
    if (code === "timeout") return t("err.walletTimeout");
    if (code === "pending") return t("err.walletPending");
    return "MetaMask: " + e.message;
  }
  if (e instanceof ApiError) {
    if (e.status === 0) return t("err.network");
    if (e.status === 401) return e.message && e.message !== "Unauthorized" ? e.message : t("err.unauth");
    if (e.status === 403) return e.message && e.message !== "Forbidden" ? e.message : t("err.forbidden");
    if (e.status === 429) return e.message && e.message !== "Too Many Requests" ? e.message : t("err.rate");
    return e.message;
  }
  return e instanceof Error ? e.message : String(e);
}
