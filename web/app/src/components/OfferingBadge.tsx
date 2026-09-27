import { useI18n } from "../i18n";

/** "Offering open" chip on business cards and the company page (simulated share offering, pages/Offerings.tsx). */
export function OfferingBadge() {
  const { t } = useI18n();
  return <span className="of-badge"><i aria-hidden="true" />{t("of.badge")}</span>;
}
