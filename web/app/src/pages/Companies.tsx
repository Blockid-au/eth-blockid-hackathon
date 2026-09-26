import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { arrow, useI18n } from "../i18n";
import { api, type CompanySummary } from "../api";
import { Spark } from "../components/charts";
import { ErrorBox } from "../components/Layout";
import { useAsync, useTitle } from "../lib/hooks";
import { GRADE_C } from "../lib/math";
import type { DictKey } from "../dict";

type SortKey = "ticker" | "name" | "grade" | "valuation_aud" | "mark_aud" | "change_7d" | "change_30d" | "holders";

export function CompanyTable({ rows, selected, onPick }: { rows: CompanySummary[]; selected?: string; onPick: (c: CompanySummary) => void }) {
  const { t, fmt, money, aud, chg } = useI18n();
  const [sort, setSort] = useState<{ k: SortKey; dir: 1 | -1 }>({ k: "valuation_aud", dir: -1 });
  const sorted = useMemo(() => {
    const r = rows.slice();
    r.sort((a, b) => {
      const x = a[sort.k] ?? (typeof b[sort.k] === "number" ? -Infinity : ""), y = b[sort.k] ?? (typeof a[sort.k] === "number" ? -Infinity : "");
      return (x < y ? -1 : x > y ? 1 : 0) * sort.dir * (sort.k === "grade" ? -1 : 1);
    });
    return r;
  }, [rows, sort]);
  const th = (k: SortKey, label: string, right = false) => (
    <th className={right ? "r" : ""} aria-sort={sort.k === k ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
      <button type="button" className="linkbtn" style={{ color: "inherit", font: "inherit", letterSpacing: "inherit", textTransform: "inherit" }} onClick={() => setSort((s) => ({ k, dir: s.k === k ? (-s.dir as 1 | -1) : -1 }))} aria-label={t("co.sort", { c: label })}>
        {label}{sort.k === k ? (sort.dir === 1 ? " ↑" : " ↓") : ""}
      </button>
    </th>
  );
  return (
    <div className="tbl">
      <table className="ctable">
        <thead>
          <tr>
            {th("ticker", t("ad.c.tk"))}{th("name", t("ad.c.name"))}{th("grade", t("ad.c.grade"))}{th("valuation_aud", t("ad.c.val"), true)}{th("mark_aud", t("ad.c.mark"), true)}
            {th("change_7d", "7d", true)}{th("change_30d", "30d", true)}<th>{t("ad.c.trend")}</th>{th("holders", t("ad.c.hold"), true)}<th>{t("ad.c.anch")}</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((c) => {
            const p7 = c.change_7d ?? 0, p30 = c.change_30d ?? 0;
            return (
              <tr key={c.ticker} tabIndex={0} aria-selected={selected === c.ticker} onClick={() => onPick(c)} onKeyDown={(e) => { if (e.key === "Enter") onPick(c); }}>
                <td className="mono" style={{ fontWeight: 600 }}>{c.ticker}</td>
                <td>{c.name}</td>
                <td>{c.grade ? <span className="gchip" style={{ background: `var(${GRADE_C[c.grade] ?? "--c6"})` }}>{c.grade}</span> : "–"} {c.svi != null && <span className="muted">{fmt(Number(c.svi), 1)}</span>}</td>
                <td className="r">{money(c.valuation_aud)}</td>
                <td className="r">{aud(c.mark_aud, 3)}</td>
                <td className="r"><span className={"chg " + arrow(p7)}>{chg(p7)}</span></td>
                <td className="r"><span className={"chg " + arrow(p30)}>{chg(p30)}</span></td>
                <td><Spark vals={c.spark_30d ?? [c.mark_aud, c.mark_aud]} cls={arrow(p30)} /></td>
                <td className="r">{fmt(c.holders ?? 0)}</td>
                <td>{c.sync?.hoodi === "done" && c.sync?.hsk === "done" ? <span className="anch">{t("co.anch3")}</span> : c.anchored ? <span className="anch">{t("co.anchYes")}</span> : <span className="muted-sm">{c.status === "anchoring" ? t(("c.tl.anchoring") as DictKey) : t("co.anchNo")}</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function CompaniesPage() {
  const { t } = useI18n();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const data = useAsync(() => api.companies(), [], 30000);
  useTitle(t("co.h2"));
  const rows = (data.data ?? []).filter((c) => !q || c.ticker.toLowerCase().includes(q.toLowerCase()) || c.name.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="wrap page">
      <div className="head">
        <span className="eyebrow">{t("co.eyebrow")}</span>
        <h2>{t("co.h2")}</h2>
        <p>{t("co.p")}</p>
      </div>
      <div className="pane">
        <div className="phead">
          <input className="inp" style={{ maxWidth: 320 }} type="search" placeholder={t("co.search")} aria-label={t("co.search")} value={q} onChange={(e) => setQ(e.target.value)} />
          <span className="note">{t("ad.clickrow")}</span>
        </div>
        {data.error ? <ErrorBox error={data.error} retry={data.reload} /> : data.loading && !data.data ? <p className="note">{t("common.loading")}</p> : rows.length === 0 ? (
          <p className="empty">{t("co.empty")} <Link to="/new">{t("cta.primary")}</Link></p>
        ) : (
          <CompanyTable rows={rows} onPick={(c) => nav(`/c/${c.ticker}`)} />
        )}
      </div>
    </div>
  );
}
