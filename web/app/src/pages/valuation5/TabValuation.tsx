/* Report v5 — "How we reached this value": football field across methods, then one method at a time. */
import { Fragment, useState } from "react";
import type { DictKey } from "../../dict";
import { FootballField, SensGrid } from "../../components/v5/charts5";
import { Checks, ConfPill, KTile, SeeHow, SrcLink, StageBadge, TableView, useFmt5 } from "../../components/v5/ui";
import { tip } from "../../lib/tip";
import type { FieldBar, Method5, V5, ValuationFinal } from "../../components/v5/types";

type Obj = Record<string, unknown>;
const n = (x: unknown): number | null => (x == null || x === "" || !Number.isFinite(Number(x)) ? null : Number(x));
const arr = <T = Obj,>(x: unknown): T[] => (Array.isArray(x) ? (x as T[]) : []);
const obj = (x: unknown): Obj => (x && typeof x === "object" && !Array.isArray(x) ? (x as Obj) : {});

export function methodLabel(t: (k: DictKey) => string, m: { method: string; label?: string }) {
  const k = ("v5.m." + m.method) as DictKey;
  const s = t(k);
  return s === k ? m.label || m.method : s;
}

function DcfDetail({ m }: { m: Method5 }) {
  const { t, money, pct, fmt } = useFmt5();
  const i = m.inputs;
  const res = obj(i.result);
  const rows = arr<Obj>(i.rows);
  const fcff = arr<number>(res.fcff), ebitda = arr<number>(res.ebitda);
  const b = obj(i.rate_build);
  const r = n(b.rate), g = n(i.g);
  const sens = obj(res.sensitivity);
  const cols = arr<number>(sens.gs ?? sens.exit_multiples);
  const tvShare = n(res.tv_share);
  const scen = arr<Obj>(res.scenarios);
  return (
    <div className="stack">
      {scen.length > 0 && (
        <div className="dbars">
          {scen.map((sc) => {
            const v = n(sc.value_aud) ?? 0, mx = Math.max(...scen.map((z) => n(z.value_aud) ?? 0), 1);
            return (
              <div className="dbar" key={String(sc.scenario)} style={{ cursor: "default" }}>
                <span className="nm">{t(("v5.fc." + sc.scenario) as DictKey).startsWith("v5.fc.") ? String(sc.scenario) : t(("v5.fc." + sc.scenario) as DictKey)}<small>{pct((n(sc.probability) ?? 0) * 100, 0)}</small></span>
                <span className="tr"><b style={{ width: (v / mx) * 100 + "%" }} /></span>
                <span className="sv" style={{ fontSize: ".74rem" }}>{money(v)}</span>
              </div>
            );
          })}
        </div>
      )}
      {rows.length > 0 && (
        <div className="tbl">
          <table>
            <caption className="sr-only">{t("v5.dcf.fcff")}</caption>
            <thead><tr><th>{t("v5.col.year")}</th>{rows.map((y) => <th key={String(y.year)} className="r">{String(y.year)} {y.actual ? "A" : "P"}</th>)}</tr></thead>
            <tbody>
              <tr><td>{t("v5.dcf.revenue")}</td>{rows.map((y) => <td key={String(y.year)} className="r">{n(y.revenue) == null ? "–" : money(n(y.revenue)!)}</td>)}</tr>
              {ebitda.length === rows.length && <tr><td>{t("v5.dcf.ebitda")}</td>{ebitda.map((x, k) => <td key={k} className="r">{money(x)}</td>)}</tr>}
              {fcff.length === rows.length && <tr><td><b>{t("v5.dcf.fcff")}</b></td>{fcff.map((x, k) => <td key={k} className="r"><b>{money(x)}</b></td>)}</tr>}
            </tbody>
          </table>
        </div>
      )}
      <div className="cols">
        <div className="card">
          <h4>{t("v5.dcf.build")}</h4>
          <dl className="dl5">
            {n(b.rf) != null && <><dt>{t("v5.dcf.rf")}</dt><dd>{pct(n(b.rf)! * 100, 2)}</dd></>}
            {n(b.beta ?? b.beta_l ?? b.beta_u) != null && <><dt>{t("v5.dcf.beta")}</dt><dd>{fmt(n(b.beta ?? b.beta_l ?? b.beta_u)!, 2)}</dd></>}
            {n(b.erp) != null && <><dt>{t("v5.dcf.erp")}</dt><dd>{pct(n(b.erp)! * 100, 2)}</dd></>}
            {n(b.crp) != null && <><dt>{t("v5.dcf.crp")}</dt><dd>{pct(n(b.crp)! * 100, 2)}</dd></>}
            {n(b.size_premium) != null && <><dt>{t("v5.dcf.size")}</dt><dd>{pct(n(b.size_premium)! * 100, 2)}</dd></>}
            {r != null && <><dt><b>{t("v5.dcf.rate")}</b></dt><dd><b>{pct(r * 100, 2)}</b></dd></>}
            {g != null && <><dt>{t("v5.dcf.g")}</dt><dd>{pct(g * 100, 2)}</dd></>}
            {n(i.exit_multiple) != null && <><dt>{t("v5.dcf.exitm")}</dt><dd>{fmt(n(i.exit_multiple)!, 1)}×</dd></>}
            {(res.terminal_used ?? i.terminal) != null && <><dt>{t("v5.dcf.terminal")}</dt><dd>{t(("v5.dcf.t." + String(res.terminal_used ?? i.terminal)) as DictKey)}</dd></>}
            {n(res.ev) != null && <><dt>{t("v5.dcf.ev")}</dt><dd>{money(n(res.ev)!)}</dd></>}
            {n(i.net_debt_aud) != null && <><dt>{t("v5.dcf.nd")}</dt><dd>− {money(n(i.net_debt_aud)!)}</dd></>}
          </dl>
        </div>
        {tvShare != null && (
          <div className="card">
            <h4>{t("v5.dcf.tv")}</h4>
            <div className="bars100">
              <div className="s" role="img" aria-label={t("v5.dcf.tv.aria", { p: pct(tvShare * 100, 0) })}>
                <i style={{ width: (1 - tvShare) * 100 + "%", background: "var(--c3)" }} /><i style={{ width: tvShare * 100 + "%", background: "var(--c1)" }} />
              </div>
            </div>
            <div className="legend5"><span><i className="sw" style={{ background: "var(--c3)" }} />{t("v5.dcf.tv.pv")} · {pct((1 - tvShare) * 100, 0)}</span><span><i className="sw" style={{ background: "var(--c1)" }} />{t("v5.dcf.tv.tv")} · {pct(tvShare * 100, 0)}</span></div>
            <p className={"sub" + (tvShare > 0.75 ? " bad" : "")}>{t(tvShare > 0.75 ? "v5.dcf.tv.high" : "v5.dcf.tv.ok")}</p>
          </div>
        )}
      </div>
      {n(res.uncapped_value_aud) != null && <p className="sub">{t("v5.ff.uncapped", { v: money(n(res.uncapped_value_aud)!) })}</p>}
      {arr(sens.values).length > 0 && (
        <div className="card">
          <h4>{t("v5.dcf.sens")}</h4>
          <p className="sub">{t("v5.dcf.sens.p")}</p>
          <SensGrid rates={arr<number>(sens.rates)} gs={cols} exit={!sens.gs} values={arr<(number | null)[]>(sens.values)} base={m.value_aud} />
        </div>
      )}
    </div>
  );
}

function CompsDetail({ m }: { m: Method5 }) {
  const { t, fmt, money, pct } = useFmt5();
  const i = m.inputs;
  const isE = m.method === "ebitda_multiple", isP = m.method === "precedents";
  const base = n(isE ? i.ebitda_aud : isP ? i.metric_aud : i.revenue_aud);
  const band = arr<number>(i.band);
  const mid = n(i.median_multiple) ?? (band.length === 3 ? n(band[1]) : null);
  const disc = n(i.discount ?? i.dlom);
  const nd = n(i.net_debt_aud);
  const deals = arr<Obj>(i.deals);
  const points: { name: string; mult: number; url?: string }[] = deals.length
    ? deals.map((d) => ({ name: String(d.target ?? d.name ?? "—"), mult: n(d.multiple) ?? 0, url: String(d.source_url ?? "") }))
    : arr<unknown>(i.multiples).map((x, k) => (typeof x === "object" && x ? { name: String((x as Obj).name ?? "#" + (k + 1)), mult: n((x as Obj).multiple) ?? 0, url: String((x as Obj).source_url ?? "") } : { name: "#" + (k + 1), mult: n(x) ?? 0 }));
  const mx = Math.max(...points.map((p) => p.mult), mid ?? 0, 1);
  const baseKey = isE ? "v5.cm.ebitda" : isP ? (i.basis === "revenue" ? "v5.cm.rev" : "v5.cm.ebitda") : "v5.cm.rev";
  return (
    <div className="stack">
      {base != null && mid != null && (
        <div className="row" style={{ gap: 8 }}>
          <KTile label={t(baseKey as DictKey)} value={money(base)} />
          <b aria-hidden="true">×</b>
          <KTile label={t("v5.cm.mult")} value={fmt(mid, 1) + "×"} />
          {disc != null && disc > 0 && <><b aria-hidden="true">×</b><KTile label={t("v5.cm.disc")} value={"(1 − " + pct(disc * 100, 0) + ")"} /></>}
          {nd != null && nd !== 0 && <><b aria-hidden="true">−</b><KTile label={t("v5.dcf.nd")} value={money(nd)} /></>}
          <b aria-hidden="true">=</b>
          <KTile label={t("v5.cm.val")} value={money(m.value_aud)} />
        </div>
      )}
      {points.length > 0 && (
        <div className="card">
          <h4>{t(isP ? "v5.cm.deals" : "v5.cm.peers")}</h4>
          <div className="dbars">
            {points.map((c, k) => (
              <div className="dbar" key={k} style={{ cursor: "default" }} {...tip(`${c.name} · ${fmt(c.mult, 1)}×`)}>
                <span className="nm">{c.name}</span>
                <span className="tr"><b style={{ width: (c.mult / mx) * 100 + "%", background: "var(--c3)" }} />{mid != null && <i style={{ left: (mid / mx) * 100 + "%" }} />}</span>
                <span className="sv">{fmt(c.mult, 1)}×</span>
              </div>
            ))}
          </div>
          <div className="legend5"><span><i className="mk" />{t("v5.cm.median")}</span></div>
          <TableView caption={t("v5.cm.peers")} head={[t("v5.col.name"), t("v5.cm.mult"), t("v5.col.source")]} rows={points.map((c) => [c.name, fmt(c.mult, 1) + "×", c.url ? <SrcLink key="s" url={c.url} /> : "–"])} />
        </div>
      )}
      {!points.length && band.length === 3 && <p className="sub">{t("v5.cm.band", { lo: fmt(band[0], 1), mid: fmt(band[1], 1), hi: fmt(band[2], 1) })}{i.detail ? " · " + String(i.detail) : ""}</p>}
    </div>
  );
}

function VcDetail({ m }: { m: Method5 }) {
  const { t, money, fmt, pct } = useFmt5();
  const i = m.inputs;
  const metric = n(i.exit_metric_aud), em = n(i.exit_multiple), inv = n(i.investment_aud) ?? 0, yrs = n(i.years_to_exit) ?? 5, ret = n(i.retention) ?? 1;
  const tm = arr<number>(i.target_multiples), irr = n(i.target_irr);
  const exitV = metric != null && em != null ? metric * em : null;
  const steps: [string, string][] = [];
  if (exitV != null) steps.push([t("v5.vc.exitrev", { r: money(metric!), m: fmt(em!, 1), y: fmt(yrs) }), money(exitV)]);
  if (ret !== 1) steps.push([t("v5.vc.ret", { p: pct(ret * 100, 0) }), money((exitV ?? 0) * ret)]);
  if (irr != null) steps.push([t("v5.vc.irr", { p: pct(irr * 100, 0), y: fmt(yrs) }), money(m.value_aud + inv)]);
  else if (tm.length === 3) steps.push([t("v5.vc.div", { m: fmt(tm[1], 0), lo: fmt(tm[0], 0), hi: fmt(tm[2], 0) }), money(m.value_aud + inv)]);
  if (inv) steps.push([t("v5.vc.raise"), "− " + money(inv)]);
  steps.push([t("v5.vc.pre"), money(m.value_aud)]);
  return (
    <ol className="checks">
      {steps.map(([a, b], k) => <li key={k} className={k === steps.length - 1 ? "ok" : "info"}><span className="ic" aria-hidden="true">{k + 1}</span><span className="between" style={{ flexWrap: "nowrap" }}><span>{a}</span><b className="num">{b}</b></span></li>)}
    </ol>
  );
}

function StartupDetail({ m }: { m: Method5 }) {
  const { t, money, fmt, dim } = useFmt5();
  const i = m.inputs;
  if (m.method === "scorecard") {
    const lines = obj(i.lines), w = obj(i.weights);
    const keys = Object.keys(lines).length ? Object.keys(lines) : Object.keys(w);
    return (
      <div className="stack">
        <p className="sub">{t("v5.sc.p", { b: money(n(i.base_pre_money_aud) ?? 0), f: fmt(n(i.factor) ?? 1, 2) })}</p>
        <div className="dbars">
          {keys.map((k) => {
            const s = n(obj(lines[k]).score) ?? 0;
            return (
              <div className="dbar" key={k} style={{ cursor: "default" }} {...tip(`${dim(k)} · ${fmt(s)}/100 · ×${fmt(n(w[k]) ?? 0, 2)}`)}>
                <span className="nm">{dim(k)}<small>×{fmt(n(w[k]) ?? 0, 2)}</small></span>
                <span className="tr"><b style={{ width: Math.min(100, s) + "%" }} /><i style={{ left: "50%" }} /></span>
                <span className="sv">{fmt(s)}</span>
              </div>
            );
          })}
        </div>
        <div className="legend5"><span><i className="mk" />{t("v5.sc.avg")}</span></div>
      </div>
    );
  }
  if (m.method === "berkus") {
    const sc = obj(i.scores), cap = n(i.cap_per_factor_aud) ?? 750000;
    return (
      <div className="stack">
        <p className="sub">{t("v5.bk.p", { c: money(cap) })}</p>
        <div className="dbars">
          {Object.entries(sc).map(([k, x]) => {
            const s = Math.max(0, Math.min(100, n(x) ?? 0));
            return (
              <div className="dbar" key={k} style={{ cursor: "default" }} {...tip(`${t(("v5.bk." + k) as DictKey)} · ${fmt(s)}% · ${money((s / 100) * cap)}`)}>
                <span className="nm">{t(("v5.bk." + k) as DictKey)}<small>{fmt(s)}%</small></span>
                <span className="tr"><b style={{ width: s + "%" }} /></span>
                <span className="sv" style={{ fontSize: ".74rem" }}>{money((s / 100) * cap)}</span>
              </div>
            );
          })}
        </div>
      </div>
    );
  }
  if (m.method === "rfs") {
    const rs = obj(i.ratings), base = n(i.base_pre_money_aud) ?? 0, step = base * (n(i.step_ratio) ?? 0.05);
    return (
      <div className="stack">
        <p className="sub">{t("v5.rfs.p", { b: money(base), s: money(step), n: String(n(i.net_steps) ?? "") })}</p>
        <div className="dbars">
          {Object.entries(rs).map(([k, x]) => {
            const v = Math.max(-2, Math.min(2, n(x) ?? 0));
            return (
              <div className="dbar" key={k} style={{ cursor: "default" }} {...tip(`${t(("v5.rfs." + k) as DictKey)} · ${v > 0 ? "+" : ""}${v}`)}>
                <span className="nm">{t(("v5.rfs." + k) as DictKey)}</span>
                <span className="tr" aria-label={String(v)}>
                  <i style={{ left: "50%" }} />
                  {v !== 0 && <b style={{ left: v >= 0 ? "50%" : 50 + v * 25 + "%", width: Math.abs(v) * 25 + "%", background: v >= 0 ? "var(--div-up)" : "var(--div-dn)", borderRadius: v >= 0 ? "0 4px 4px 0" : "4px 0 0 4px" }} />}
                </span>
                <span className="sv">{v > 0 ? "+" : ""}{v}</span>
              </div>
            );
          })}
        </div>
        <div className="legend5"><span><i className="sw" style={{ background: "var(--div-dn)" }} />{t("v5.rfs.minus")}</span><span><i className="mk" />0</span><span><i className="sw" style={{ background: "var(--div-up)" }} />{t("v5.rfs.plus")}</span></div>
      </div>
    );
  }
  return null;
}

function Inputs({ m }: { m: Method5 }) {
  const { t, fmt } = useFmt5();
  const flat = Object.entries(m.inputs).filter(([, v]) => v == null || ["number", "string", "boolean"].includes(typeof v));
  if (!flat.length) return null;
  return (
    <SeeHow label={t("v5.va.inputs", { n: flat.length })}>
      <dl className="dl5">{flat.map(([k, v]) => <Fragment key={k}><dt>{k.replace(/_/g, " ")}</dt><dd className="mono">{typeof v === "number" ? fmt(v, Number.isInteger(v) ? 0 : 3) : String(v)}</dd></Fragment>)}</dl>
    </SeeHow>
  );
}

export function ValuationTab({ x, final }: { x: V5; final?: ValuationFinal | null }) {
  const { t, money, fmt, stage } = useFmt5();
  const tri = x.tri;
  const methods = tri ? [...tri.methods].sort((a, b) => b.weight - a.weight) : [];
  const [cur, setCur] = useState<string>(methods[0]?.method ?? "");
  if (!tri) return <p className="note">{t("v5.nodata")}</p>;
  const m = methods.find((z) => z.method === cur) ?? methods[0];
  const lbl = (b: FieldBar | Method5) => methodLabel(t, b);
  const offer = final ? final.pre_money_aud : null;
  const startup = ["scorecard", "berkus", "rfs"];
  return (
    <div className="stack">
      <div className="card">
        <div className="between">
          <div>
            <h4>{t("v5.va.h")}</h4>
            <p className="sub">{t("v5.va.p")}</p>
          </div>
          <span className="row" style={{ gap: 6 }}><ConfPill c={tri.confidence} />{tri.stage_class && <StageBadge stage={tri.stage_class.cls} />}</span>
        </div>
        <FootballField bars={tri.field} value={tri.value_aud} low={tri.low_aud} high={tri.high_aud} offer={offer} labelFor={lbl} />
        {tri.uses_projections && (
          <p className="lbl-proj">* {tri.projection_label || t("v5.proj.label")}{tri.without_projections_aud != null ? " " + t("v5.proj.without", { v: money(tri.without_projections_aud) }) : ""}</p>
        )}
        <p className="hint">{t("v5.va.legal")}{tri.params_version ? " · " + t("v5.va.params", { v: tri.params_version }) : ""}</p>
      </div>
      <div className="card">
        <h4>{t("v5.va.methods")}</h4>
        <div className="mtabs" role="group" aria-label={t("v5.va.methods")}>
          {methods.map((z) => (
            <button key={z.method} type="button" aria-pressed={z.method === m?.method} className={z.weight > 0 ? "" : "off"} onClick={() => setCur(z.method)}>
              {lbl(z)}<span className="mono muted-sm">{z.weight > 0 ? fmt(z.weight * 100) + "%" : "0%"}</span>
            </button>
          ))}
        </div>
        {m && (
          <div className="stack" role="region" aria-label={lbl(m)}>
            <div className="between">
              <div>
                <b>{lbl(m)}</b> <span className="muted-sm">· {t(("v5.md." + m.method) as DictKey) === "v5.md." + m.method ? "" : t(("v5.md." + m.method) as DictKey)}</span>
              </div>
              <span className="num"><b>{money(m.value_aud)}</b> <span className="muted-sm">({money(m.low_aud)} – {money(m.high_aud)})</span></span>
            </div>
            {!(m.weight > 0) && <p className="banner warn">{t("v5.va.excluded")}{m.excluded_reason ? ": " + m.excluded_reason : ""}</p>}
            {m.uses_projections && <p className="lbl-proj">{t("v5.proj.label")}</p>}
            {(m.method === "dcf" || m.method === "first_chicago") && <DcfDetail m={m} />}
            {(m.method === "revenue_multiple" || m.method === "ebitda_multiple" || m.method === "precedents") && <CompsDetail m={m} />}
            {m.method === "vc_method" && <VcDetail m={m} />}
            {startup.includes(m.method) && <StartupDetail m={m} />}
            {m.method === "stage_scorecard" && tri.stage_class && <p className="sub">{t("v5.va.stagefallback", { s: stage(tri.stage_class.stage ?? tri.stage_class.cls) })}</p>}
            <Checks items={m.checks} empty={t("v5.va.nochecks")} />
            {m.notes.length > 0 && <ul className="muted-sm">{m.notes.map((z, k) => <li key={k}>{z}</li>)}</ul>}
            {m.sources.length > 0 && <div className="row" style={{ gap: 6 }}><span className="muted-sm">{t("v5.sm.src")}:</span>{m.sources.map((s) => <SrcLink key={s} url={s} />)}</div>}
            <Inputs m={m} />
          </div>
        )}
      </div>
      <SeeHow label={t("v5.va.weights")}>
        <p className="sub">{t("v5.va.weights.p")}</p>
        <TableView caption={t("v5.va.weights")} head={[t("v5.col.method"), t("v5.col.base"), t("v5.col.weight"), t("v5.col.note")]}
          rows={methods.map((z) => [lbl(z), z.raw_weight != null ? fmt(z.raw_weight, 2) : "–", fmt(z.weight * 100) + "%", z.excluded_reason ?? ""])} />
      </SeeHow>
    </div>
  );
}
