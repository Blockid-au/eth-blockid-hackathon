import { Link } from "react-router-dom";
import { useI18n } from "../i18n";
import { useAsync } from "../lib/hooks";
import { loadHskDemo, okAddr } from "../lib/hsk";

/** Compact Home card. */
export function HskHomeCard() {
  const { t } = useI18n();
  const q = useAsync(() => loadHskDemo(), []);
  const d = q.data;
  const n = [d?.agentProvenance, d?.identityRegistry, d?.shareToken, d?.dividendDistributor, d?.payToken, d?.capTableAnchor].filter(okAddr).length;
  const p = Array.isArray(d?.provenance) ? d!.provenance!.length : 0;
  return (
    <div className="card hskcard">
      <div className="between">
        <span className="eyebrow">{t("hsk.eyebrow")}</span>
        <span className={"pill " + (d ? "ok" : "gold")}>{d ? t("hsk.live") : t("hsk.pending")}</span>
      </div>
      <h3>{t("hsk.title")}</h3>
      <p className="note">{t("hsk.msg")}</p>
      {d && <p className="hint">{t("hsk.card.stats", { c: n, p })}</p>}
      <div className="row"><Link className="btn sm" to="/hsk">{t("hsk.open")} →</Link></div>
    </div>
  );
}
