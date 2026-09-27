import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useI18n } from "../i18n";
import { useNow } from "../lib/hooks";

export type Tone = "run" | "wait" | "ok" | "bad" | "idle";
export interface StatusNext { label: ReactNode; to?: string; onClick?: () => void }

function Elapsed({ since }: { since: string }) {
  const { t } = useI18n();
  const now = useNow(1000);
  const t0 = Date.parse(since);
  if (!Number.isFinite(t0)) return null;
  const s = Math.max(0, Math.round((now - t0) / 1000));
  const m = Math.floor(s / 60);
  const txt = m >= 60 ? `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m` : m ? `${m}m ${String(s % 60).padStart(2, "0")}s` : `${s}s`;
  return <span className="sb-meta num">{t("sb.elapsed", { t: txt })}</span>;
}

/**
 * One slim status line at the top of a screen: status pill, step progress (dots + "Step n of N"),
 * elapsed time while something runs, and the next action as a small link. Replaces full-width banners.
 */
export function StatusBar({ status, tone, step, done, total = 8, since, meta, next }: {
  status: ReactNode; tone: Tone; step?: number | null; done?: number; total?: number; since?: string | null;
  meta?: ReactNode; next?: StatusNext | null;
}) {
  const { t } = useI18n();
  const reached = done ?? (step != null ? step - 1 : 0);
  return (
    <div className="statusbar" role="status" aria-live="polite">
      <span className={"sb-pill " + tone}>{(tone === "run" || tone === "wait") && <i aria-hidden="true" />}<span className="sr-only">{t("sb.label")}: </span>{status}</span>
      {step != null && step > 0 && (
        <span className="sb-steps">
          <span className="sb-dots" aria-hidden="true">
            {Array.from({ length: total }, (_, i) => i + 1).map((n) => (
              <i key={n} className={n <= reached ? "d" : n === step ? "c" : ""} />
            ))}
          </span>
          <span className="sb-n">{t("sb.step", { n: step, N: total })}</span>
        </span>
      )}
      {since && tone === "run" ? <Elapsed since={since} /> : null}
      {meta != null && <span className="sb-meta">{meta}</span>}
      {next && (next.to && !next.onClick
        ? <Link className="sb-next" to={next.to}>{next.label} <span aria-hidden="true">→</span></Link>
        : <button className="sb-next" type="button" onClick={next.onClick}>{next.label} <span aria-hidden="true">→</span></button>)}
    </div>
  );
}
