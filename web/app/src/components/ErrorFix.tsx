import { useState } from "react";
import { Link } from "react-router-dom";
import { api, type ErrorInfo } from "../api";
import { errText, useAuth } from "../auth";
import { useI18n } from "../i18n";
import type { DictKey } from "../dict";

const LABEL: Record<string, string> = { blockid: "BlockID Chain", hoodi: "Ethereum Hoodi", hsk: "HashKey Chain testnet" };
const KNOWN = new Set(["cap_table_mismatch", "transfer_scan_failed", "insufficient_gas", "chain_not_configured",
  "mint_failed", "dividend_failed", "not_issued", "network"]);

/** Client-side fallback for rows the server did not classify (mirrors agents/.../studio/errors.py). */
export function classifyError(raw?: string | null): ErrorInfo | null {
  if (!raw) return null;
  const cap = /sum\(balances\)=(\d+) != totalSupply=(\d+)/.exec(raw);
  const rules: [string, RegExp, ErrorInfo["action"], ErrorInfo["target"]][] = [
    ["cap_table_mismatch", /cap table incomplete/i, "refresh", "cap-table"],
    ["transfer_scan_failed", /could not scan share transfers/i, "refresh", "cap-table"],
    ["insufficient_gas", /InsufficientFunds|needs about .* gas|top up the issuer/i, "top_up", "issuer-wallets"],
    ["chain_not_configured", /is not configured/i, "configure", "sync"],
    ["mint_failed", /^mint \d+/i, "retry_item", "approvals"],
    ["dividend_failed", /^dividend \d+/i, "retry_item", "approvals"],
    ["not_issued", /not issued/i, "approve_issue", "tracker"],
    ["network", /timed? ?out|timeout|connection|50[234]|nonce too low|replacement/i, "resync", "sync"],
  ];
  for (const [code, re, action, target] of rules) {
    if (re.test(raw)) {
      const info: ErrorInfo = { code, action, target };
      if (cap) info.detail = { on_chain_in_table: +cap[1], total_supply: +cap[2], missing: +cap[2] - +cap[1] };
      return info;
    }
  }
  return { code: "unknown", action: "refresh", target: "tracker" };
}

/** Where the person should look to fix it. `#fix` makes the target section scroll into view and flash. */
function targetPath(i: ErrorInfo, ticker: string): string {
  if (i.target === "issuer-wallets") return "/admin/wallets";
  if (i.target === "approvals") return i.code === "dividend_failed" ? "/admin/dividends" : "/admin/mints";
  if (i.target === "cap-table") return `/c/${ticker}/cap-table#fix`;
  if (i.target === "sync") return `/c/${ticker}/sync#fix`;
  return `/c/${ticker}/issue#fix`;
}

/**
 * An issuer error explained in plain words, with a link to the place to fix it and, for admins, the button that
 * fixes it ("Refresh from chain & re-sync" clears the error, rebuilds the cap table from chain, re-syncs mirrors).
 */
export function ErrorFix({ error, info, ticker, companyId, onDone, hideLink }: {
  error?: string | null; info?: ErrorInfo | null; ticker: string; companyId?: number | null; onDone?: () => void;
  hideLink?: boolean;
}) {
  const { t, fmt } = useI18n();
  const { me } = useAuth();
  const admin = me?.role === "admin";
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; s: string } | null>(null);
  const i = info ?? classifyError(error);
  if (!i) return null;
  const code = KNOWN.has(i.code) ? i.code : "unknown";
  const chains = Object.keys(i.chains ?? {});
  const where = chains.length ? " · " + chains.map((k) => LABEL[k] ?? k).join(", ") : "";
  const missing = i.detail?.missing;
  const canRefresh = admin && companyId != null && (i.action === "refresh" || i.action === "resync" || code === "unknown");

  const refresh = async () => {
    if (companyId == null) return;
    setBusy(true); setMsg(null);
    try { await api.refreshCompany(companyId); setMsg({ ok: true, s: t("fix.sent") }); onDone?.(); }
    catch (e) { setMsg({ ok: false, s: errText(e, t) }); }
    finally { setBusy(false); }
  };

  return (
    <div className="banner bad fixbox" role="alert">
      <div className="grow">
        <b>{t(`fix.${code}.h` as DictKey, { c: where })}</b>
        <p className="fix-p">{t(`fix.${code}.p` as DictKey, { n: missing != null ? fmt(missing) : "?" })}</p>
        {!admin && (i.action === "refresh" || i.action === "resync") && <p className="muted-sm fix-p">{t("fix.adminonly")}</p>}
        <div className="row fix-actions">
          {canRefresh && <button className="btn gold sm" type="button" disabled={busy} onClick={refresh}>{t("fix.refresh")}</button>}
          {!hideLink && (admin || i.target === "cap-table" || i.target === "sync" || i.target === "tracker") && (
            <Link className="btn ghost sm" to={targetPath(i, ticker)}>{t(`fix.go.${i.target}` as DictKey)}</Link>
          )}
        </div>
        {msg && <p className={msg.ok ? "toast" : "err"} role={msg.ok ? "status" : "alert"}>{msg.s}</p>}
        {error && (
          <details className="fix-raw">
            <summary className="muted-sm">{t("fix.raw")}</summary>
            <code className="mono">{error}</code>
          </details>
        )}
      </div>
    </div>
  );
}
