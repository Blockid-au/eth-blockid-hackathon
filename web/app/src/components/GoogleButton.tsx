import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api";
import { errText, useAuth } from "../auth";
import { useI18n } from "../i18n";

/** Google Identity Services: "Sign in with Google". The ID token is bound to a key created in this browser. */
interface Gis {
  accounts: { id: {
    initialize: (o: { client_id: string; callback: (r: { credential: string }) => void; ux_mode?: string; auto_select?: boolean; itp_support?: boolean }) => void;
    renderButton: (el: HTMLElement, o: Record<string, unknown>) => void;
  } };
}
declare global {
  interface Window { google?: Gis }
}

let script: Promise<void> | null = null;
function loadGis(): Promise<void> {
  script ??= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => { script = null; reject(new Error("Could not load Google sign-in")); };
    document.head.appendChild(s);
  });
  return script;
}

let cfg: Promise<string | null> | null = null;
export function googleClientId(): Promise<string | null> {
  cfg ??= api.authConfig().then((c) => c.google_client_id).catch(() => { cfg = null; return null; });
  return cfg;
}

export function GoogleButton({ onDone, width = 240 }: { onDone?: () => void; width?: number }) {
  const { t, lang } = useI18n();
  const { google } = useAuth();
  const box = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"loading" | "ready" | "off">("loading");
  const [err, setErr] = useState("");
  const [newWallet, setNewWallet] = useState<string | null>(null);
  const done = useRef(onDone);
  done.current = onDone;

  useEffect(() => {
    let alive = true;
    (async () => {
      const id = await googleClientId();
      if (!id) { if (alive) setState("off"); return; }
      try {
        await loadGis();
        if (!alive || !box.current || !window.google) return;
        window.google.accounts.id.initialize({
          client_id: id,
          itp_support: true,
          callback: async ({ credential }) => {
            setErr(""); setNewWallet(null);
            try {
              const m = await google(credential);
              // new browser, new key, but this Google account already has a wallet: say so (and stay here)
              if (m?.newWallet?.length) { setNewWallet(m.newWallet[0]); return; }
              done.current?.();
            } catch (e) { setErr(e instanceof ApiError && e.status === 409 ? t("fx.g.taken") : errText(e, t)); }
          },
        });
        window.google.accounts.id.renderButton(box.current, { theme: "outline", size: "large", text: "continue_with", shape: "pill", width, locale: lang });
        setState("ready");
      } catch {
        if (alive) setState("off");
      }
    })();
    return () => { alive = false; };
  }, [google, lang, t, width]);

  if (state === "off") return <span className="muted-sm">{t("in.google.off")}</span>;
  return (
    <span style={{ display: "grid", gap: 6 }}>
      <div ref={box} style={{ minHeight: 40 }} aria-busy={state === "loading"} />
      {err && <span role="alert" style={{ color: "var(--bad)", fontSize: ".82rem" }}>{err}</span>}
      {newWallet && (
        <span role="status" className="banner warn" style={{ fontSize: ".82rem", display: "grid", gap: 6 }}>
          <span>{t("fx.g.newkey", { a: newWallet })}</span>
          <span className="row" style={{ gap: 10, flexWrap: "wrap" }}>
            <Link className="btn gold sm" to="/i/account#restore">{t("fx.g.restore")}</Link>
            <button className="btn ghost sm" type="button" onClick={() => { setNewWallet(null); done.current?.(); }}>{t("fx.g.keepNew")}</button>
          </span>
        </span>
      )}
    </span>
  );
}
