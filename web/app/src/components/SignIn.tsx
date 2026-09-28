import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { errText, useAuth } from "../auth";
import { useI18n } from "../i18n";
import { GoogleButton } from "./GoogleButton";

/** Three ways in, easiest first. */
export function SignInCard({ compact = false }: { compact?: boolean }) {
  const { t } = useI18n();
  const { tryDemo, connect, busy } = useAuth();
  const nav = useNavigate();
  const [err, setErr] = useState("");
  const [which, setWhich] = useState<"" | "demo" | "wallet">("");
  const run = async (w: "demo" | "wallet", f: () => Promise<unknown>) => {
    setErr(""); setWhich(w);
    try { await f(); nav("/i"); } catch (e) { setErr(errText(e, t)); } finally { setWhich(""); }
  };
  return (
    <section className={"card solid signin" + (compact ? " compact" : "")} aria-label={t("in.sign.h")}>
      {!compact && <h4>{t("in.sign.h")}</h4>}
      <div className="signin-opts">
        <div className="signin-opt">
          <button className="btn" type="button" disabled={busy} onClick={() => run("demo", tryDemo)}>
            {busy && which === "demo" ? <span className="spinner" aria-hidden="true" /> : null}{t("in.sign.try")}
          </button>
          <span className="muted-sm">{t("in.sign.trySub")}</span>
        </div>
        <div className="signin-opt">
          <GoogleButton onDone={() => nav("/i")} />
          <span className="muted-sm">{t("in.sign.googleSub")}</span>
        </div>
        <div className="signin-opt">
          <button className="btn ghost" type="button" disabled={busy} onClick={() => run("wallet", connect)}>
            {busy && which === "wallet" ? <span className="spinner" aria-hidden="true" /> : null}{t("in.sign.mm")}
          </button>
          <span className="muted-sm" role={which === "wallet" ? "status" : undefined}>{which === "wallet" ? t("err.walletWait") : t("in.sign.mmSub")}</span>
        </div>
      </div>
      {err && <span role="alert" style={{ color: "var(--bad)", fontSize: ".85rem" }}>{err}</span>}
    </section>
  );
}

