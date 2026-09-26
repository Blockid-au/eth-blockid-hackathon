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
 * Testnet-demo convenience for judges: how to approve a pending item with the demo admin account.
 * Shown to non-admins wherever an admin approval is pending. `action` is the button label they will press.
 * With `admin`, the button opens that exact admin queue item and returns to `next` after the decision.
 */
export function DemoApproveGuide({ action, tail, next, admin }: { action: string; tail: DictKey; next?: string; admin?: string }) {
  const { t } = useI18n();
  const loc = useLocation();
  const back = safeNext(next ?? loc.pathname + loc.search) ?? "/";
  return (
    <aside className="demoguide" aria-labelledby="demo-h">
      <span className="demotag">{t("demo.tag")}</span>
      <b id="demo-h">{t("demo.h")}</b>
      <ol>
        <li>{t("demo.s1")}</li>
        <li>{t("demo.s2")}</li>
        <li>{t("demo.s3")}</li>
        <li>{t("demo.s4", { a: action })}</li>
      </ol>
      <p>{t(tail)}</p>
      <Link className="btn gold" to={admin ? `${admin}?return=${encodeURIComponent(back)}` : `/admin?next=${encodeURIComponent(back)}`}>{admin ? t("gate.open") : t("demo.btn")}</Link>
    </aside>
  );
}
