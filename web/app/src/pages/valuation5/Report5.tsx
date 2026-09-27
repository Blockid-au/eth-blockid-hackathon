/**
 * Report v5 — a guided, tabbed report (docs/PLAN-EVALUATION-V5.md §5.2, docs/PLAN-VALUATION-V5.md §8,
 * docs/DECISIONS-V5.md #1). Mounted by pages/Valuation.tsx only when `readV5(v)` finds v5 data.
 * Summary first; details behind "See how" expanders; every chart has a table view.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { Evidence, Valuation as Val } from "../../api";
import { useAsync } from "../../lib/hooks";
import { api5 } from "../../components/v5/api5";
import { Tabs5, useFmt5, useHashTab } from "../../components/v5/ui";
import type { Series, TokView, V5 } from "../../components/v5/types";
import { EvidenceTab, MarketTab, MoatTab, Overview, RetentionTab, TeamTab, TractionTab, type TabKey } from "./TabsEval";
import { ValuationTab } from "./TabValuation";
import { Finalise, FrozenCard } from "./Finalise";
import { DocUploads, ProjectionsCard } from "./Uploads";

const KEYS: TabKey[] = ["overview", "team", "traction", "market", "moat", "retention", "valuation", "evidence", "finalise"];

/** Monthly series from an uploaded metrics CSV (documents → parsed.series). */
function seriesFromDocs(docs: Awaited<ReturnType<typeof api5.documents>> | undefined): Series | null {
  const d = (docs ?? []).filter((x) => x.kind === "metrics_csv" && x.parsed?.months?.length).pop();
  if (!d?.parsed?.months) return null;
  const s = d.parsed.series ?? {};
  return { months: d.parsed.months, mrr: s.mrr_aud, revenue: s.revenue_aud, customers: s.customers, level: 2 };
}

export function Report5({ v, x, evidence, isAdmin, canEdit, adminSlot, onTeamDone, reload }: {
  v: Val; x: V5; evidence: Evidence[] | undefined; isAdmin: boolean; canEdit: boolean; adminSlot?: ReactNode; onTeamDone?: () => void; reload: () => void;
}) {
  const { t, fmt, money } = useFmt5();
  const [tab, setTab] = useHashTab<TabKey>(KEYS, "overview");
  const hasTri = !!x.tri;
  const [tok, setTok] = useState<TokView | null>(null);
  useEffect(() => {
    if (!hasTri) return;
    let live = true;
    api5.tokenisation(v.id).then((r) => { if (live) setTok(r); }).catch(() => { if (live) setTok(null); });
    return () => { live = false; };
  }, [v.id, v.status, hasTri]);
  const docs = useAsync(() => (canEdit ? api5.documents(v.id).catch(() => []) : Promise.resolve([])), [v.id, canEdit]);
  const series = useMemo(() => seriesFromDocs(docs.data), [docs.data]);
  const [rescoring, setRescoring] = useState(false);
  const [msg, setMsg] = useState("");
  const locked = v.status === "approved" && tok?.final_state === "valid";

  const score = (k: string) => { const d = x.eval?.dims.find((z) => z.key === k); return d ? fmt(d.score) : undefined; };
  const tabs: { key: TabKey; label: string; badge?: string }[] = [
    { key: "overview", label: t("v5.tab.overview") },
    { key: "team", label: t("v5.tab.team"), badge: score("founder_quality") },
    { key: "traction", label: t("v5.tab.traction"), badge: score("traction") },
    { key: "market", label: t("v5.tab.market"), badge: score("market") },
    { key: "moat", label: t("v5.tab.moat"), badge: score("moat") },
    { key: "retention", label: t("v5.tab.retention"), badge: score("retention") },
    ...(hasTri ? [{ key: "valuation" as TabKey, label: t("v5.tab.valuation"), badge: money(x.tri!.value_aud) }] : []),
    { key: "evidence", label: t("v5.tab.evidence") },
    ...(hasTri ? [{ key: "finalise" as TabKey, label: t("v5.tab.finalise"), badge: tok?.final_state === "valid" ? "✓" : undefined }] : []),
  ];
  const cur = tabs.some((z) => z.key === tab) ? tab : "overview";
  const goAdd = () => { setTab("evidence"); setTimeout(() => document.getElementById("v5-uploads")?.scrollIntoView({ behavior: "smooth", block: "start" }), 60); };

  const rescore = async () => {
    setRescoring(true); setMsg("");
    try { await api5.rescore(v.id); setMsg(t("v5.up.rescored")); reload(); void docs.reload(); } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); } finally { setRescoring(false); }
  };

  const cta = hasTri && v.status === "approved" ? (
    tok?.final && tok.final_state === "valid" ? <FrozenCard f={tok.final} v={v} state="valid" compact /> : (
      <div className="banner gold" style={{ justifyContent: "space-between" }}>
        <span><b>{t("v5.cta.h")}</b> · {t(tok?.pending ? "v5.hint.pending" : "v5.cta.p")}</span>
        <button type="button" className="btn gold sm" onClick={() => setTab("finalise")}>{t("v5.cta.btn")} →</button>
      </div>
    )
  ) : null;

  const uploads = canEdit && !locked ? (
    <div className="stack" id="v5-uploads">
      <div className="card">
        <div className="between"><h4>{t("v5.up.addh")}</h4>{(docs.data?.length ?? 0) > 0 && <button type="button" className="btn sm" disabled={rescoring} onClick={() => void rescore()}>{rescoring ? <span className="spinner" aria-hidden="true" /> : null}{t("v5.up.rescore")}</button>}</div>
        <p className="sub">{t("v5.up.addp")}</p>
        <DocUploads vid={v.id} onUploaded={() => void docs.reload()} />
        {msg && <p className="toast" role="status">{msg}</p>}
      </div>
      {hasTri && <ProjectionsCard vid={v.id} stage={x.eval?.stage.stage ?? x.tri?.stage_class?.stage ?? "seed"} onConfirmed={reload} />}
    </div>
  ) : null;

  return (
    <div className="panel v5" role="region" aria-label={t("s3.h")}>
      {adminSlot}
      <Tabs5 tabs={tabs} cur={cur} set={setTab} label={t("v5.tabs")} />
      <div role="tabpanel" id={"v5p-" + cur} aria-labelledby={"v5t-" + cur} tabIndex={-1}>
        {cur === "overview" && <Overview v={v} x={x} go={setTab} finaliseCta={cta} />}
        {cur === "team" && <TeamTab v={v} x={x} onTeamDone={onTeamDone} />}
        {cur === "traction" && <TractionTab x={x} series={series} onAdd={canEdit && !locked ? goAdd : undefined} />}
        {cur === "market" && <MarketTab x={x} />}
        {cur === "moat" && <MoatTab v={v} x={x} />}
        {cur === "retention" && <RetentionTab x={x} onAdd={canEdit && !locked ? goAdd : undefined} />}
        {cur === "valuation" && <ValuationTab x={x} final={tok?.final_state === "valid" ? tok.final : null} />}
        {cur === "evidence" && <EvidenceTab x={x} evidence={evidence} uploads={uploads} />}
        {cur === "finalise" && (canEdit
          ? <Finalise v={v} x={x} tok={tok} isAdmin={isAdmin} onChanged={(r) => { if (r) setTok(r); else void api5.tokenisation(v.id).then(setTok).catch(() => undefined); }} />
          : <div className="card"><h4>{t("v5.fn.h")}</h4><p className="sub">{t("v5.fn.owner")}</p></div>)}
      </div>
      <p className="hint">{t("v5.legal")}</p>
    </div>
  );
}
