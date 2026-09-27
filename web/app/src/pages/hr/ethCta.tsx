/* Calls to action that hand a business over to eth.blockid.au (value it, list its shares, open its valuation). */
import { useI18n } from "../../i18n";
import { ethUrl } from "../../lib/hrhost";
import { normUrl } from "../../lib/people";

/** eth.blockid.au/start with the business website (and the "list shares" goal) pre-filled. */
export function ethStartUrl(website?: string | null, goal?: "list"): string {
  const q = new URLSearchParams();
  if (goal) q.set("goal", goal);
  const u = website ? normUrl(website) : null;
  if (u) q.set("url", u);
  const s = q.toString();
  return ethUrl("/start" + (s ? "?" + s : ""));
}
export const ethValuationUrl = (id: string) => ethUrl(`/v/${encodeURIComponent(id)}/report`);

const Arrow = () => <span aria-hidden="true" className="hx-ext">↗</span>;

/** Card with the eth CTAs. `valuationId` switches the primary action to "Open the business valuation". */
export function EthCtas({ website, valuationId, name, variant = "card" }: { website?: string | null; valuationId?: string | null; name?: string | null; variant?: "card" | "band" | "inline" }) {
  const { t } = useI18n();
  const nm = (name ?? "").trim();
  const title = valuationId ? t("hr2.eth.h.linked", { n: nm || t("hr2.eth.thisbiz") }) : nm ? t("hr2.eth.h", { n: nm }) : t("hr2.eth.h.any");
  const body = valuationId ? t("hr2.eth.p.linked") : t("hr2.eth.p");
  const btns = (
    <div className="hx-eth-btns">
      {valuationId
        ? <a className="btn" href={ethValuationUrl(valuationId)}>{t("hr.r.valuation.btn")}<Arrow /></a>
        : <a className="btn" href={ethStartUrl(website)}>{t("hr2.eth.value")}<Arrow /></a>}
      <a className="btn ghost" href={ethStartUrl(website, "list")}>{t("hr2.eth.list")}<Arrow /></a>
    </div>
  );
  if (variant === "inline") return <div className="hx-eth inline hr-noprint">{btns}</div>;
  return (
    <section className={"hx-eth hr-noprint " + variant} aria-label={t("hr2.eth.label")}>
      <div className="hx-eth-txt">
        <span className="eyebrow">{t("hr2.eth.eyebrow")}</span>
        <h2>{title}</h2>
        <p>{body}</p>
      </div>
      {btns}
    </section>
  );
}
