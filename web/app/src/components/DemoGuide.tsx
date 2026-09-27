import { Link, useLocation } from "react-router-dom";
import { useI18n } from "../i18n";
import type { DictKey } from "../dict";

/** Only same-origin relative paths: "/x", never "//host", "/\\host" or "scheme:". */
export function safeNext(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const s = raw.trim();
  if (!s.startsWith("/") || s.startsWith("//") || s.startsWith("/\\") || /^\/[^?#]*:/.test(s) || /[\u0000-\u001f]/.test(s)) return null;
  return s;
}

/**
 * Testnet-demo convenience for judges: a small chip saying how to approve a pending item with the demo admin account.
 * Shown to non-admins wherever an admin approval is pending. `action` is the button label they will press.
 * With `admin`, the link opens that exact admin queue item and returns to `next` after the decision.
 * (`tail` is kept for callers; the chip is one line, so it is not shown.)
 */
export function DemoApproveGuide({ action, next, admin }: { action: string; tail?: DictKey; next?: string; admin?: string }) {
  const { t } = useI18n();
  const loc = useLocation();
  const back = safeNext(next ?? loc.pathname + loc.search) ?? "/";
  return (
    <p className="demochip">
      <span className="demotag">{t("demo.chip")}</span>
      <span>{t("demo.chip.p", { a: action })}</span>
      <Link to={admin ? `${admin}?return=${encodeURIComponent(back)}` : `/admin?next=${encodeURIComponent(back)}`}>{t("demo.chip.btn")} →</Link>
    </p>
  );
}

/** Deep link used by status bars: the admin item to approve, returning to `next`. */
export function demoApproveLink(admin: string, next: string): string {
  return `${admin}?return=${encodeURIComponent(safeNext(next) ?? "/")}`;
}
