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
 */
export function DemoApproveGuide({ action, tail, next }: { action: string; tail: DictKey; next?: string }) {
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
      <Link className="btn gold" to={`/admin?next=${encodeURIComponent(back)}`}>{t("demo.btn")}</Link>
    </aside>
  );
}
