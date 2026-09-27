import { useState } from "react";
import { Link } from "react-router-dom";
import { useI18n } from "../i18n";
import { api, type AdminWallets } from "../api";
import { useAsync } from "../lib/hooks";
import { shortAddr } from "../lib/addr";

/* Low-balance thresholds (whole units). Below these a chain sync can stall waiting for gas. */
export const MIN_ISSUER_HOODI_ETH = 0.05;
export const MIN_ISSUER_HSK = 0.03;
export const MIN_ISSUER_BLKD = 100;
/** The relayer only pays gas for dividend claims on BlockID EVM (Hoodi/HashKey mirrors are paused). */
export const MIN_RELAYER_BLKD = 100;

const FAUCET: Record<Chain, string | null> = { hoodi: "https://hoodi-faucet.pk910.de", hsk: "https://hskchain.net/faucet", local: null };
const UNIT: Record<Chain, string> = { hoodi: "Hoodi ETH", hsk: "HSK", local: "BLKD" };
type Chain = "local" | "hoodi" | "hsk";

export interface LowBal { who: "issuer" | "relayer"; address: string; chain: Chain; have: number; min: number }

/** wei string / number -> whole units (18 decimals), null when unknown. */
function units(v: unknown): number | null {
  if (v == null || v === "") return null;
  try { return Number(BigInt(String(v)) / 10n ** 12n) / 1e6; } catch { const n = Number(v); return Number.isFinite(n) ? n : null; }
}

export function lowBalances(w?: AdminWallets | null): LowBal[] {
  if (!w) return [];
  const out: LowBal[] = [];
  const check = (who: LowBal["who"], chain: Chain, min: number) => {
    const x = w[who];
    if (!x?.address) return;
    const have = units(chain === "local" ? x.local_balance : chain === "hoodi" ? x.hoodi_balance : x.hsk_balance);
    if (have != null && have < min) out.push({ who, address: x.address, chain, have, min });
  };
  check("issuer", "hoodi", MIN_ISSUER_HOODI_ETH);
  check("issuer", "hsk", MIN_ISSUER_HSK);
  check("issuer", "local", MIN_ISSUER_BLKD);
  check("relayer", "local", MIN_RELAYER_BLKD);
  return out;
}

/** Warning banner listing every wallet below its threshold; renders nothing when all are funded. */
export function LowBalanceBanner({ wallets, compact = false }: { wallets?: AdminWallets | null; compact?: boolean }) {
  const { t, fmt } = useI18n();
  const [copied, setCopied] = useState<string | null>(null);
  const low = lowBalances(wallets);
  if (!low.length) return null;
  const copy = async (a: string) => { try { await navigator.clipboard.writeText(a); setCopied(a); setTimeout(() => setCopied(null), 2000); } catch { /* selection still possible */ } };
  return (
    <div className={"banner warn lowbal" + (compact ? " compact" : "")} role="alert">
      <ul>
        {low.map((l) => {
          const f = FAUCET[l.chain];
          return (
            <li key={l.who + l.chain}>
              <span>{t(l.who === "issuer" ? "lb.issuer" : "lb.relayer", { a: shortAddr(l.address), u: UNIT[l.chain], v: fmt(l.have, 4) })}{" "}
                {t(l.chain === "hoodi" ? "lb.hoodi" : l.chain === "hsk" ? "lb.hsk" : "lb.local")}</span>
              {!compact && <span className="muted-sm"> {t("lb.min", { m: fmt(l.min, l.min < 1 ? 3 : 0), u: UNIT[l.chain] })}</span>}
              <span className="row" style={{ gap: 6, marginTop: 4 }}>
                <button className="btn ghost sm" type="button" onClick={() => void copy(l.address)} aria-label={`${t("s8.copy")} ${l.address}`}>{copied === l.address ? "✓ " + t("toast.copied") : t("s8.copy")}</button>
                {f && <a className="btn ghost sm" href={f} target="_blank" rel="noopener noreferrer">{t("lb.faucet")}: {f.replace(/^https?:\/\//, "")}</a>}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** Self-fetching quiet line for places outside the admin console (the step with the approve / re-sync button). */
export function LowBalanceInline() {
  const { t } = useI18n();
  const w = useAsync(() => api.adminWallets(), [], 60000);
  const low = lowBalances(w.data);
  if (!low.length) return null;
  return (
    <p className="quietline" role="note">
      <span aria-hidden="true">⚠</span>
      <span>{t("lb.quiet", { n: low.length })}</span>
      <Link to="/admin/wallets">{t("lb.quiet.link")} →</Link>
    </p>
  );
}
