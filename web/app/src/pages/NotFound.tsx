import { Link } from "react-router-dom";
import { useI18n } from "../i18n";
import { useTitle } from "../lib/hooks";

export function NotFound() {
  const { t } = useI18n();
  useTitle(t("nf.h"));
  return (
    <div className="wrap nf">
      <span className="eyebrow">404</span>
      <h1>{t("nf.h")}</h1>
      <p className="muted">{t("nf.p")}</p>
      <div className="row">
        <Link className="btn" to="/">{t("nf.home")}</Link>
        <Link className="btn ghost" to="/companies">{t("nav.companies")}</Link>
      </div>
    </div>
  );
}
