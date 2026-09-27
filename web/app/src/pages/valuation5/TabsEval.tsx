/* Report v5 — evaluation tabs: Overview, Team, Traction, Market, Moat, Retention, Evidence. */
import { Fragment, type ReactNode } from "react";
import type { Evidence, Valuation as Val } from "../../api";
import { HBars } from "../../components/charts";
import { TeamCard } from "../../components/TeamCard";
import { hrTeamUrl } from "../../lib/hrhost";
import { BenchBar, DimBars, Funnel, LineChart, MetricList, PowersRadar, ScoreGauge } from "../../components/v5/charts5";
import { ConfPill, KTile, LevelBadge, LevelLegend, SeeHow, SrcLink, StageBadge, StageRail, TableView, useFmt5 } from "../../components/v5/ui";
import type { Dim5, Eval5, Level, Series, SubMetric, V5 } from "../../components/v5/types";

export type TabKey = "overview" | "team" | "traction" | "market" | "moat" | "retention" | "valuation" | "evidence" | "finalise";
export const DIM_TAB: Record<string, TabKey> = { founder_quality: "team", traction: "traction", efficiency: "traction", market: "market", moat: "moat", retention: "retention", product_strength: "moat", trust_verification: "evidence" };

const findDim = (e: Eval5 | null, k: string): Dim5 | undefined => e?.dims.find((d) => d.key === k);
/** Which tab an improvement tip belongs to (the dimension whose own `improve` list carries it). */
const tabOfTip = (e: Eval5 | null, tip: string): TabKey | null => { const d = e?.dims.find((x) => x.improve.includes(tip)); return d ? DIM_TAB[d.key] ?? null : null; };
const hasVal = (m: SubMetric) => m.value != null;

/* ---------------- shared header for one dimension ---------------- */
function DimHead({ d, children }: { d?: Dim5; children?: ReactNode }) {
  const { t, fmt, dim } = useFmt5();
  if (!d) return <p className="note">{t("v5.nodata")}</p>;
  const na = d.status === "not_applicable", thin = d.status === "not_enough_data";
  return (
    <div className="card">
      <div className="between">
        <div className="row" style={{ gap: 12, alignItems: "baseline" }}>
          <span className="bigno" style={{ fontSize: "2rem" }}>{fmt(d.score)}</span>
          <span className="muted-sm">/100 · {d.label || dim(d.key)} · {t("v5.db.weight", { w: fmt(d.weight * 100) })}</span>
        </div>
        <span className="row" style={{ gap: 6 }}>{na ? <span className="pill">{t("v5.dh.na")}</span> : thin ? <span className="pill">{t("v5.db.thin")}</span> : null}<LevelBadge level={d.level} /><ConfPill c={d.confidence} /></span>
      </div>
      <div className="dbar" style={{ cursor: "default", padding: 0 }} aria-hidden="true">
        <span className="nm muted-sm">{t("v5.db.vsstage")}</span>
        <span className="tr"><b style={{ width: Math.max(0, Math.min(100, d.score)) + "%" }} /><i style={{ left: "50%" }} /><i className="q" style={{ left: "75%" }} /></span>
        <span className="sv">{fmt(d.score)}</span>
      </div>
      <p className="sub">{t("v5.dh.cov", { c: fmt(d.coverage * 100) })}{d.cap != null && d.cap < 100 ? " " + t("v5.dh.capped", { c: fmt(d.cap) }) : ""}</p>
      {d.rationale && <p className="sub">{d.rationale}</p>}
      {d.improve.length > 0 && (
        <div className="banner ok" style={{ display: "grid", gap: 4 }}>
          <b>{t("v5.raise.h")}</b>
          {d.improve.map((r, i) => <span key={i}>↑ {r}</span>)}
        </div>
      )}
      {d.flags.length > 0 && <ul className="checks">{d.flags.map((f, i) => <li key={i} className="warning"><span className="ic" aria-hidden="true">!</span><span>{f}</span></li>)}</ul>}
      {children}
    </div>
  );
}

/* ---------------- what we need (no data yet) ---------------- */
function Need({ items, onAdd }: { items: string[]; onAdd?: () => void }) {
  const { t } = useFmt5();
  return (
    <div className="card" style={{ borderStyle: "dashed" }}>
      <h4>{t("v5.need.h")}</h4>
      <p className="sub">{t("v5.need.p")}</p>
      <ul className="checks">{items.map((x) => <li key={x} className="info"><span className="ic" aria-hidden="true">+</span><span>{x}</span></li>)}</ul>
      {onAdd && <button type="button" className="btn ghost sm" style={{ justifySelf: "start" }} onClick={onAdd}>{t("v5.need.add")}</button>}
    </div>
  );
}

/* ================= Overview ================= */
export function Overview({ v, x, go, finaliseCta }: { v: Val; x: V5; go: (k: TabKey) => void; finaliseCta?: ReactNode }) {
  const { t, money, fmt, pct, stage } = useFmt5();
  const e = x.eval, tri = x.tri, svi = v.svi!;
  const st = e?.stage.stage ?? tri?.stage_class?.stage ?? "seed";
  const value = tri?.value_aud ?? svi.valuation_mid_aud, lo = tri?.low_aud ?? svi.valuation_low_aud, hi = tri?.high_aud ?? svi.valuation_high_aud;
  const grade = /[A-E]/.exec(e?.band || svi.band)?.[0] ?? svi.band;
  const reasons = e?.stage.reasons.length ? e.stage.reasons : tri?.stage_class?.reasons ?? [];
  const main = (e?.dims ?? []).filter((d) => d.weight > 0);
  return (
    <div className="stack">
      <div className="card">
        <div className="v5hero">
          <ScoreGauge score={e?.index ?? svi.index} grade={grade} label={t("v5.ov.score")} />
          <div className="facts">
            <span className="muted-sm">{t("v5.ov.value")}</span>
            <span className="val">{money(value)}</span>
            <span className="rng">{t("v5.ov.range", { lo: money(lo), hi: money(hi) })}</span>
            <div className="row" style={{ gap: 8 }}>
              {tri && <ConfPill c={tri.confidence} />}
              <StageBadge stage={st} />
              {tri?.uses_projections && <span className="lbl-proj">* {t("v5.proj.label")}</span>}
            </div>
            <StageRail stage={st} />
            {e && <span className="hint">{t("v5.ov.trust", { p: pct(e.trust_share * 100, 0) })}</span>}
          </div>
        </div>
        <SeeHow label={t("v5.ov.why.stage", { s: stage(st) })}>
          <p className="sub">{t(("v5.basis." + (e?.stage.basis ?? "default")) as "v5.basis.default")}</p>
          {reasons.length > 0 && <ul className="checks">{reasons.map((r, i) => <li key={i} className="info"><span className="ic" aria-hidden="true">{i + 1}</span><span>{r}</span></li>)}</ul>}
          {e?.stage.conflict && <p className="banner warn">{t("v5.ov.conflict")}</p>}
          <p className="hint">{t("v5.ov.stagekeys")}{e?.stage.table_version ? " · " + t("v5.ov.tablever", { v: e.stage.table_version }) : ""}</p>
        </SeeHow>
        {tri && tri.confidence_reasons.length > 0 && (
          <SeeHow label={t("v5.ov.why.conf")}>
            <ul className="checks">{tri.confidence_reasons.map((r, i) => <li key={i} className="info"><span className="ic" aria-hidden="true">i</span><span>{r}</span></li>)}</ul>
          </SeeHow>
        )}
      </div>
      {finaliseCta}
      <div className="cols">
        <div className="card">
          <h4>{t("v5.ov.dims")}</h4>
          <p className="sub">{t("v5.ov.dims.p", { s: stage(st) })}</p>
          <DimBars dims={main} stageLabel={stage(st)} onPick={(k) => DIM_TAB[k] && go(DIM_TAB[k])} />
        </div>
        <div className="stack">
          {(e?.top_raise.length ?? 0) > 0 && (
            <div className="card">
              <h4>{t("v5.ov.top3")}</h4>
              <ol className="steps">{e!.top_raise.slice(0, 3).map((r, i) => {
                const tab = tabOfTip(e, r);
                return <li key={i}>{tab ? <button type="button" className="linkbtn" onClick={() => go(tab)}>{r}</button> : r}</li>;
              })}</ol>
            </div>
          )}
          <LevelLegend />
        </div>
      </div>
      {e && (
        <SeeHow label={t("v5.ov.how")}>
          <p className="sub">{t("v5.ov.how.p")}</p>
          <TableView caption={t("v5.ov.how")} head={[t("v5.col.dim"), t("v5.col.score"), t("v5.col.weight"), t("v5.col.contrib")]}
            rows={[...main.map((d) => [t(("v5.dim." + d.key) as "v5.dim.traction"), fmt(d.score), "×" + fmt(d.weight, 2), fmt(d.score * d.weight, 1)]), [<b key="s">{t("v5.col.total")}</b>, "", "", <b key="v">{fmt(main.reduce((a, d) => a + d.score * d.weight, 0), 1)}</b>]]} />
        </SeeHow>
      )}
    </div>
  );
}

/* ================= Team ================= */
export function TeamTab({ v, x, onTeamDone }: { v: Val; x: V5; onTeamDone?: () => void }) {
  const { t } = useFmt5();
  const d = findDim(x.eval, "founder_quality");
  return (
    <div className="stack">
      <DimHead d={d} />
      <TeamCard valuationId={v.id} teamId={v.team_id} summary={v.team} weight={d?.weight ?? v.svi?.weights?.founder_quality} sample={v.id === "sample"}
        applied={v.svi?.dimensions?.founder_quality?.basis === "team_report"} onDone={onTeamDone} />
      {v.team_id && <a className="btn ghost sm" style={{ justifySelf: "start" }} href={hrTeamUrl(v.team_id)} target="_blank" rel="noopener noreferrer">{t("v5.team.open")} ↗</a>}
      {d && d.submetrics.length > 0 && <MetricList items={d.submetrics} />}
    </div>
  );
}

/* ================= Traction ================= */
export function TractionTab({ x, series, onAdd }: { x: V5; series: Series | null; onAdd?: () => void }) {
  const { t, val, money, fmt } = useFmt5();
  const d = findDim(x.eval, "traction"), eff = findDim(x.eval, "efficiency");
  const s = series ?? x.eval?.series ?? null;
  const tiles = (d?.submetrics ?? []).filter(hasVal);
  const serKey = s?.mrr?.some((v) => v != null) ? "mrr" : "revenue";
  const ser = s ? (serKey === "mrr" ? s.mrr : s.revenue) : null;
  return (
    <div className="stack">
      <DimHead d={d} />
      {tiles.length > 0 && (
        <div className="ktiles">
          {tiles.map((m) => <KTile key={m.key} label={m.label || m.metric} value={val(m.value, m.unit)} sub={<LevelBadge level={m.level} />} />)}
        </div>
      )}
      {s && ser && ser.some((v) => v != null) ? (
        <div className="card">
          <div className="between"><h4>{t(serKey === "mrr" ? "v5.tr.mrr" : "v5.tr.rev")}</h4><LevelBadge level={(s.level ?? 2) as Level} /></div>
          <LineChart labels={s.months} series={[{ name: t(serKey === "mrr" ? "v5.tr.mrr" : "v5.tr.rev"), vals: ser, color: "--c1" }]} fmtV={(n) => money(n)} ariaLabel={t(serKey === "mrr" ? "v5.tr.mrr" : "v5.tr.rev")} />
          <TableView caption={t("v5.tr.mrr")} head={[t("v5.col.month"), t("v5.col.value")]} rows={s.months.map((m, i) => [m, ser[i] == null ? "–" : money(ser[i]!)])} />
        </div>
      ) : (
        <Need items={[t("v5.need.csv"), t("v5.need.mrr"), t("v5.need.customers")]} onAdd={onAdd} />
      )}
      {d && d.submetrics.length > 0 && <div className="card"><h4>{t("v5.tr.metrics")}</h4><p className="sub">{t("v5.tr.metrics.p")}</p><MetricList items={d.submetrics} /></div>}
      {eff && (
        <div className="card">
          <div className="between"><h4>{t("v5.dim.efficiency")} · {fmt(eff.score)}/100</h4><span className="row" style={{ gap: 6 }}><LevelBadge level={eff.level} short /><ConfPill c={eff.confidence} /></span></div>
          {eff.improve.length > 0 && <p className="sub">↑ {eff.improve.join(" · ")}</p>}
          {eff.submetrics.length ? <MetricList items={eff.submetrics} /> : <p className="note">{t("v5.nodata")}</p>}
        </div>
      )}
      <SeeHow label={t("v5.seehow.score")}><p className="sub">{t("v5.tr.how")}</p><p className="sub">{t("v5.lv.shrink")}</p></SeeHow>
    </div>
  );
}

/* ================= Market ================= */
export function MarketTab({ x }: { x: V5 }) {
  const { t, money, fmt, pct } = useFmt5();
  const d = findDim(x.eval, "market");
  const m = x.eval?.market;
  const has = !!m && (m.tam_aud || m.sam_aud || m.som_aud);
  const srcLabel = (s?: string) => (!s ? "" : s === "self_reported" ? t("v5.src.self") : s.startsWith("abs:") ? t("v5.mk.abs") : s);
  return (
    <div className="stack">
      <DimHead d={d} />
      {has ? (
        <div className="cols">
          <div className="card">
            <h4>{t("v5.mk.h")}</h4>
            <Funnel rows={[
              { key: "tam", label: "TAM", value: m!.tam_aud, note: t("v5.mk.tam") },
              { key: "sam", label: "SAM", value: m!.sam_aud, note: t("v5.mk.sam") },
              { key: "som", label: "SOM", value: m!.som_aud ? m!.som_aud[1] : null, note: m!.som_aud ? t("v5.mk.som.r", { lo: money(m!.som_aud[0]), hi: money(m!.som_aud[1]) }) + (m!.som_share ? " · " + t("v5.mk.som.s", { a: pct(m!.som_share[0] * 100, 0), b: pct(m!.som_share[1] * 100, 0) }) : "") : t("v5.mk.som") },
            ]} />
            {m!.warnings.map((w, i) => <p key={i} className="banner warn">{w}</p>)}
          </div>
          <div className="stack">
            {m!.customers != null && m!.price_aud != null && (
              <div className="card">
                <h4>{t("v5.mk.bu")}</h4>
                {m!.target_customer && <p className="sub">{m!.target_customer}</p>}
                <div className="row" style={{ gap: 8 }} role="group" aria-label={t("v5.mk.bu")}>
                  <KTile label={t("v5.mk.cust")} value={fmt(m!.customers)} sub={srcLabel(m!.customers_source)} />
                  <b aria-hidden="true">×</b>
                  <KTile label={t("v5.mk.price")} value={money(m!.price_aud)} sub={srcLabel(m!.price_source)} />
                  <b aria-hidden="true">=</b>
                  <KTile label="SAM" value={money(m!.sam_aud ?? m!.customers * m!.price_aud)} />
                </div>
              </div>
            )}
            {m!.tam_aud != null && (
              <div className="card">
                <h4>{t("v5.mk.td")}</h4>
                <b>{money(m!.tam_aud)}</b>
                {m!.tam_quote && <q className="muted-sm">{m!.tam_quote}</q>}
                {m!.tam_source_url && <SrcLink url={m!.tam_source_url} />}
              </div>
            )}
            {m!.cagr_pct != null && (
              <div className="card">
                <KTile label={t("v5.mk.cagr")} value={pct(m!.cagr_pct, 1)} />
                {m!.cagr_source_url && <SrcLink url={m!.cagr_source_url} />}
              </div>
            )}
            {m!.source_tier > 0 && <p className="sub">{t("v5.mk.tier")}: <b>{t(("v5.tier." + m!.source_tier) as "v5.tier.1")}</b></p>}
          </div>
        </div>
      ) : <Need items={[t("v5.need.target"), t("v5.need.price"), t("v5.need.geo")]} />}
      {d && d.submetrics.length > 0 && <SeeHow label={t("v5.seehow.score")}><MetricList items={d.submetrics} /></SeeHow>}
    </div>
  );
}

/* ================= Moat ================= */
export function MoatTab({ v, x }: { v: Val; x: V5 }) {
  const { t, fmt, money } = useFmt5();
  const d = findDim(x.eval, "moat");
  const ps = x.eval?.powers ?? [];
  const comps = (v.competitors ?? []).slice(0, 8);
  const pname = (k: string, l?: string) => { const s = t(("v5.pw." + k) as "v5.pw.network_effects"); return s.startsWith("v5.pw.") ? l ?? k : s; };
  return (
    <div className="stack">
      <DimHead d={d} />
      {ps.length > 0 ? (
        <div className="cols">
          <div className="card">
            <h4>{t("v5.mo.radar")}</h4>
            <p className="sub">{t("v5.mo.radar.p")}</p>
            <PowersRadar powers={ps} />
          </div>
          <div className="card">
            <h4>{t("v5.mo.grid")}</h4>
            <div className="powers">
              {ps.map((p) => (
                <div className="pw" key={p.key}>
                  <span><b>{pname(p.key, p.label)}</b> <span className="muted-sm">×{fmt(p.weight, 2)}{p.computed ? " · " + t("v5.mo.computed", { s: fmt(p.points) }) : ""}</span></span>
                  {p.computed ? <span className="muted-sm">{fmt(p.points)}/100</span> : (
                    <span className="dots" role="img" aria-label={t("v5.mo.level", { l: p.level })}>{[1, 2, 3].map((k) => <i key={k} className={p.level >= k ? "on" : ""} />)}<span className="muted-sm" style={{ marginLeft: 4 }}>{t(("v5.mo.l" + p.level) as "v5.mo.l0")}</span></span>
                  )}
                  {p.quote && <q>{p.quote}{p.source_url ? <> — <SrcLink url={p.source_url} /></> : null}</q>}
                  {p.note && <span className="hint" style={{ gridColumn: "1 / -1" }}>{p.note}</span>}
                </div>
              ))}
            </div>
            <TableView caption={t("v5.mo.grid")} head={[t("v5.col.power"), t("v5.col.level"), t("v5.col.score")]} rows={ps.map((p) => [pname(p.key, p.label), p.computed ? "–" : `${p.level}/3`, fmt(p.points)])} />
          </div>
        </div>
      ) : <Need items={[t("v5.need.ip"), t("v5.need.integrations"), t("v5.need.licences")]} />}
      {comps.length > 0 && (
        <div className="card">
          <h4>{t("v5.mo.comp")}</h4>
          <HBars ariaLabel={t("v5.mo.comp")} axis ndLabel={t("v.nd")}
            rows={comps.map((c) => ({ name: c.name, value: c.raised_aud == null ? null : c.raised_aud / 1e6, color: "--c3", label: c.raised_aud == null ? "" : fmt(c.raised_aud / 1e6, 1), tip: `${c.name} · ${c.raised_aud == null ? t("v.nd") : money(c.raised_aud)}${c.note ? " · " + c.note : ""}` }))} />
          <p className="hint">{t("v5.mo.comp.p")}</p>
          <TableView caption={t("v5.mo.comp")} head={[t("v5.col.name"), t("v5.col.raised")]} rows={comps.map((c) => [c.name, c.raised_aud == null ? t("v.nd") : money(c.raised_aud)])} />
        </div>
      )}
      <SeeHow label={t("v5.seehow.score")}><p className="sub">{t("v5.mo.how")}</p></SeeHow>
    </div>
  );
}

/* ================= Retention ================= */
export function RetentionTab({ x, onAdd }: { x: V5; onAdd?: () => void }) {
  const { t, pct, val, stage } = useFmt5();
  const d = findDim(x.eval, "retention");
  const st = x.eval?.stage.stage ?? "seed";
  const withData = (d?.submetrics ?? []).filter(hasVal);
  const cohorts = (x.eval?.cohorts ?? []).slice(-3);
  const cLen = Math.max(0, ...cohorts.map((c) => c.pts.length));
  return (
    <div className="stack">
      <DimHead d={d} />
      {!withData.length ? (
        <Need onAdd={onAdd} items={st === "idea" || st === "pre-seed" ? [t("v5.need.rt.early", { s: stage(st) }), t("v5.need.pilots"), t("v5.need.reviews")] : [t("v5.need.csvmov"), t("v5.need.nrr"), t("v5.need.churn"), t("v5.need.cohort")]} />
      ) : (
        <div className="ktiles" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
          {withData.map((m) => (
            <div className="kt" key={m.key}>
              <small>{m.label || m.metric}</small>
              <span className="row" style={{ gap: 6 }}><b>{val(m.value, m.unit)}</b><LevelBadge level={m.level} short /></span>
              {m.bench && <BenchBar value={m.value} bench={m.bench} unit={m.unit} lowerBetter={m.lower_better} />}
              {m.metric === "top_customer_share_pct" && m.value != null && m.value > 20 && <em className="bad">{t(m.value > 50 ? "v5.rt.conc.high" : "v5.rt.conc.flag", { p: pct(m.value, 0) })}</em>}
            </div>
          ))}
        </div>
      )}
      {cohorts.length > 0 && cLen > 1 && (
        <div className="card">
          <h4>{t("v5.rt.cohort")}</h4>
          <p className="sub">{t("v5.rt.cohort.p")}</p>
          <LineChart labels={Array.from({ length: cLen }, (_, i) => "M" + i)} series={cohorts.map((c, i) => ({ name: c.label, vals: c.pts, color: ["--c1", "--c3", "--c4"][i] }))} fmtV={(n) => pct(n, 0)} yMax={100} ariaLabel={t("v5.rt.cohort")} />
          <TableView caption={t("v5.rt.cohort")} head={[t("v5.col.cohort"), ...Array.from({ length: cLen }, (_, i) => "M" + i)]} rows={cohorts.map((c) => [c.label, ...c.pts.map((p) => (p == null ? "–" : pct(p, 0)))])} />
        </div>
      )}
      {d && d.submetrics.length > 0 && <SeeHow label={t("v5.seehow.score")}><p className="sub">{t("v5.rt.how")}</p><MetricList items={d.submetrics} /></SeeHow>}
    </div>
  );
}

/* ================= Evidence ================= */
export function EvidenceTab({ x, evidence, uploads }: { x: V5; evidence: Evidence[] | undefined; uploads?: ReactNode }) {
  const { t, date, fmt } = useFmt5();
  const e = x.eval;
  const subs = (e?.dims ?? []).flatMap((d) => d.submetrics);
  const byLv = [0, 1, 2, 3, 4].map((l) => subs.filter((m) => (m.value == null ? 0 : m.level) === l).length);
  const total = subs.length || 1;
  const tone = ["--line", "--o1", "--o2", "--o3", "--o4"];
  const lk = e?.lookups ?? {};
  const lookRows = Object.entries(lk).filter(([, v2]) => (v2 != null && typeof v2 !== "object") || (!!v2 && typeof v2 === "object" && Object.keys(v2).length > 0));
  return (
    <div className="stack">
      {subs.length > 0 && (
        <div className="card">
          <h4>{t("v5.ev.levels")}</h4>
          <p className="sub">{t("v5.ev.levels.p", { n: subs.length })}</p>
          <div className="bars100">
            <div className="s" role="img" aria-label={byLv.map((n, l) => `${t(("v5.lv." + l) as "v5.lv.0")} ${n}`).join(", ")}>
              {byLv.map((n, l) => n > 0 && <i key={l} style={{ width: (n / total) * 100 + "%", background: `var(${tone[l]})` }} title={`${t(("v5.lv." + l) as "v5.lv.0")} · ${n}`} />)}
            </div>
          </div>
          <div className="legend5">{byLv.map((n, l) => <span key={l}><LevelBadge level={l as Level} short />{t(("v5.lv." + l) as "v5.lv.0")} · {fmt(n)}</span>)}</div>
        </div>
      )}
      {uploads}
      {(e?.flags.length ?? 0) > 0 && (
        <div className="card">
          <h4>{t("v5.ev.flags")}</h4>
          <ul className="checks">{e!.flags.map((f, i) => <li key={i} className={f.severity === "high" ? "error" : f.severity === "warning" ? "warning" : "info"}><span className="ic" aria-hidden="true">!</span><span>{f.message}{f.action ? <span className="muted-sm"> · {t(("v5.ev.act." + f.action) as "v5.ev.act.review")}</span> : null}</span></li>)}</ul>
        </div>
      )}
      <div className="card">
        <h4>{t("v.evidence")}</h4>
        <p className="sub">{t("v.evidence.p")}</p>
        {!evidence ? <p className="note">{t("common.loading")}</p> : evidence.length === 0 ? <p className="note">{t("v.evidence.empty")}</p> : (
          <div className="evidence">
            {evidence.map((ev, i) => (
              <div key={i}>
                <a href={ev.url} target="_blank" rel="noopener noreferrer nofollow">{ev.title || ev.url}</a>
                <span className="dom">{ev.kind ? <span className="pill" style={{ marginRight: 6 }}>{ev.kind}</span> : null}<SrcLink url={ev.url} />{ev.retrieved_at ? " · " + t("v.retrieved", { d: date(ev.retrieved_at, true) }) : ""}</span>
                {ev.snippet && <p>{ev.snippet}</p>}
              </div>
            ))}
          </div>
        )}
      </div>
      {(e?.docs.length ?? 0) > 0 && (
        <div className="card">
          <h4>{t("v5.ev.docs")}</h4>
          <ul className="checks">{e!.docs.map((dc) => <li key={dc.doc_id} className="ok"><span className="ic" aria-hidden="true">✓</span><span>{dc.filename} · {t(dc.kind === "deck" ? "v5.up.deck" : dc.kind === "metrics_csv" ? "v5.up.csv" : "v5.up.fin")} · <span className="mono muted-sm">{dc.sha256.slice(0, 12)}…</span></span></li>)}</ul>
        </div>
      )}
      {lookRows.length > 0 && (
        <SeeHow label={t("v5.ev.lookups")}>
          <dl className="dl5">{lookRows.map(([k, v2]) => <Fragment key={k}><dt>{k}</dt><dd className="mono">{typeof v2 === "object" ? JSON.stringify(v2).slice(0, 160) : String(v2)}</dd></Fragment>)}</dl>
        </SeeHow>
      )}
      {(e?.dropped.length ?? 0) > 0 && (
        <SeeHow label={t("v5.ev.dropped", { n: e!.dropped.length })}>
          <ul className="checks">{e!.dropped.map((dr, i) => <li key={i} className="info"><span className="ic" aria-hidden="true">–</span><span>{dr}</span></li>)}</ul>
        </SeeHow>
      )}
      {(e?.analysts.length ?? 0) > 0 && (
        <SeeHow label={t("v5.ev.analysts")}>
          <TableView caption={t("v5.ev.analysts")} head={[t("v5.col.analyst"), t("v5.col.claims"), t("v5.col.dropped"), t("v5.col.searches")]}
            rows={e!.analysts.map((a) => [t(("v5.an." + a.name) as "v5.an.traction").startsWith("v5.an.") ? a.name : t(("v5.an." + a.name) as "v5.an.traction"), fmt(a.claims ?? 0), fmt(a.dropped ?? 0), fmt(a.searches ?? 0)])} />
        </SeeHow>
      )}
    </div>
  );
}
