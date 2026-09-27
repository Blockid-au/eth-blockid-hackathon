/**
 * v5 charts. Built to the dataviz rules: thin marks (≤ 24px bars, 4px rounded data end, square at the baseline),
 * 2px lines, ≥ 8px markers with a 2px surface ring, solid hairline grid, text in ink tokens (never series colour),
 * hover tooltips on every mark, and a table view for every chart. Colours are CSS tokens (light/dark selected in v5.css).
 */
import { useRef } from "react";
import { useI18n } from "../../i18n";
import { niceTicks } from "../../lib/math";
import { hideTip, showTip, tip } from "../../lib/tip";
import { LevelBadge, TableView, useFmt5 } from "./ui";
import type { Dim5, FieldBar, Power, SubMetric, Unit } from "./types";

const cv = (n: string) => `var(${n})`;
const clamp = (x: number, a: number, b: number) => Math.max(a, Math.min(b, x));

/* ---------------- business score gauge (meter + hero number) ---------------- */
export function ScoreGauge({ score, grade, label, median = 50 }: { score: number; grade: string; label: string; median?: number }) {
  const { fmt, t } = useI18n();
  const R = 80, cx = 100, cy = 96, sw = 14;
  const pt = (f: number, r = R) => { const a = Math.PI * (1 - f); return [cx + r * Math.cos(a), cy - r * Math.sin(a)] as const; };
  const arc = (f0: number, f1: number) => { const [x0, y0] = pt(f0), [x1, y1] = pt(Math.min(f1, 0.9999)); return `M${x0} ${y0} A${R} ${R} 0 0 1 ${x1} ${y1}`; };
  const f = clamp(score / 100, 0, 1);
  const [mx0, my0] = pt(median / 100, R - sw / 2 - 4), [mx1, my1] = pt(median / 100, R + sw / 2 + 4);
  return (
    <svg className="chart" viewBox="0 0 200 124" role="img" aria-label={`${label}: ${fmt(score, 1)} / 100, ${t("v5.grade")} ${grade}`} style={{ maxWidth: 240 }}>
      <path d={arc(0, 1)} fill="none" stroke={cv("--accent-soft")} strokeWidth={sw} strokeLinecap="round" />
      {f > 0.005 && <path d={arc(0, f)} fill="none" stroke={cv("--accent")} strokeWidth={sw} strokeLinecap="round" />}
      <line x1={mx0} y1={my0} x2={mx1} y2={my1} stroke={cv("--ink")} strokeWidth={2} />
      <text x={mx1} y={my1 - 4} fontSize={9} textAnchor="middle" fill={cv("--muted")}>{t("v5.g.median")}</text>
      <text x={cx} y={cy - 18} textAnchor="middle" fontSize={34} fontWeight={700} fill={cv("--ink")} fontFamily="var(--display)">{fmt(score, 0)}</text>
      <text x={cx} y={cy + 2} textAnchor="middle" fontSize={11} fill={cv("--muted")}>{t("v5.grade")} {grade} · /100</text>
      <text x={pt(0)[0]} y={cy + 18} fontSize={9} textAnchor="middle" fill={cv("--faint")}>0</text>
      <text x={pt(1)[0]} y={cy + 18} fontSize={9} textAnchor="middle" fill={cv("--faint")}>100</text>
      <path d={arc(0, 1)} fill="none" stroke="transparent" strokeWidth={sw + 12} {...tip(`${label} · ${fmt(score, 1)}/100 · ${t("v5.g.medtip")}`)} />
    </svg>
  );
}

/* ---------------- dimension bars vs stage benchmark markers ---------------- */
export function DimBars({ dims, onPick, stageLabel }: { dims: Dim5[]; onPick?: (k: string) => void; stageLabel: string }) {
  const { t, fmt, dim } = useFmt5();
  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="legend5" aria-hidden="true">
        <span><i className="bar" />{t("v5.db.score")}</span>
        <span><i className="mk" />{t("v5.db.median", { s: stageLabel })}</span>
        <span><i className="mk q" />{t("v5.db.top")}</span>
      </div>
      <div className="dbars" role="list">
        {dims.map((d) => {
          const tipText = `${dim(d.key)} · ${fmt(d.score)}/100 · ${t("v5.db.weight", { w: fmt(d.weight * 100) })} · ${t("v5.db.cov", { c: fmt(d.coverage * 100) })}`;
          const Tag = onPick ? "button" : "div";
          return (
            <Tag key={d.key} role="listitem" className="dbar" {...(onPick ? { type: "button" as const, onClick: () => onPick(d.key) } : {})} {...tip(tipText)} aria-label={tipText}>
              <span className="nm">{dim(d.key)}<small>×{fmt(d.weight, 2)}</small></span>
              <span className="tr" aria-hidden="true">
                <b className={d.coverage < 0.4 ? "thin" : undefined} style={{ width: clamp(d.score, 0, 100) + "%" }} />
                <i style={{ left: "50%" }} />
                <i className="q" style={{ left: "75%" }} />
              </span>
              <span className="sv">{fmt(d.score)}</span>
              <span className="meta"><LevelBadge level={d.level} short /><span className={"conf " + d.confidence}>{t(("v5.conf." + d.confidence) as "v5.conf.high")}</span>{d.coverage < 0.4 && <span className="pill">{t("v5.db.thin")}</span>}</span>
            </Tag>
          );
        })}
      </div>
      <TableView caption={t("v5.ov.dims")} head={[t("v5.col.dim"), t("v5.col.score"), t("v5.col.weight"), t("v5.col.cov"), t("v5.col.level"), t("v5.conf")]}
        rows={dims.map((d) => [dim(d.key), fmt(d.score), fmt(d.weight * 100) + "%", fmt(d.coverage * 100) + "%", "L" + fmt(d.level, 1), t(("v5.conf." + d.confidence) as "v5.conf.high")])} />
    </div>
  );
}

/* ---------------- a value on the stage P25–P90 band ---------------- */
export function BenchBar({ value, bench, unit, lowerBetter }: { value: number | null; bench: [number, number, number, number]; unit: Unit; lowerBetter?: boolean }) {
  const { val, t } = useFmt5();
  const log = unit === "aud";
  const pts = [...bench, ...(value != null ? [value] : [])].filter((x) => Number.isFinite(x));
  const f = (x: number) => (log ? Math.log10(Math.max(x, 1)) : x);
  let lo = Math.min(...pts.map(f)), hi = Math.max(...pts.map(f));
  const pad = (hi - lo) * 0.08 || 1;
  lo -= pad; hi += pad;
  if (!log && lo < 0 && Math.min(...pts) >= 0) lo = 0;
  const X = (x: number) => clamp(((f(x) - lo) / (hi - lo)) * 100, 0, 100);
  const [p25, p50, p75, p90] = bench;
  const tipText = `${t("v5.bb.you")} ${val(value, unit)} · P25 ${val(p25, unit)} · ${t("v5.bb.med")} ${val(p50, unit)} · P75 ${val(p75, unit)} · P90 ${val(p90, unit)}${lowerBetter ? " · " + t("v5.bb.lower") : ""}`;
  return (
    <div className="bench" role="img" aria-label={tipText} {...tip(tipText)}>
      <div className="trk">
        <span className="base" />
        <span className="iqr" style={{ left: Math.min(X(p25), X(p75)) + "%", width: Math.abs(X(p75) - X(p25)) + "%" }} />
        {[p25, p75, p90].map((b, i) => <span key={i} className="tk" style={{ left: X(b) + "%" }} />)}
        <span className="tk m" style={{ left: X(p50) + "%" }} />
        {value != null && <span className="dot" style={{ left: X(value) + "%" }} />}
      </div>
      <div className="lbls" aria-hidden="true">
        <span style={{ left: X(p50) + "%" }}>{t("v5.bb.med")} {val(p50, unit)}</span>
      </div>
    </div>
  );
}

/* ---------------- TAM / SAM / SOM funnel (log-scaled widths, ordinal ramp) ---------------- */
export function Funnel({ rows }: { rows: { key: string; label: string; value: number | null; note?: string }[] }) {
  const { money, t } = useI18n();
  const have = rows.filter((r) => r.value != null && r.value > 0) as { key: string; label: string; value: number; note?: string }[];
  if (!have.length) return null;
  const mx = Math.log10(Math.max(...have.map((r) => r.value))), mn = Math.log10(Math.min(...have.map((r) => r.value)));
  const W = (v: number) => (mx === mn ? 100 : 38 + ((Math.log10(v) - mn) / (mx - mn)) * 62);
  const tone = ["--o1", "--o2", "--o3", "--o4"];
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="funnel" role="img" aria-label={have.map((r) => `${r.label} ${money(r.value)}`).join(", ")}>
        {have.map((r, i) => (
          <div className="fr" key={r.key}>
            <span className={"fb" + (i === 0 ? " dk" : "")} style={{ width: W(r.value) + "%", background: cv(tone[Math.min(i + (have.length < 3 ? 1 : 0), 3)]) }} {...tip(`${r.label} · ${money(r.value)}${r.note ? " · " + r.note : ""}`)}>
              <span>{r.label}</span><b>{money(r.value)}</b>
            </span>
            {r.note && <small>{r.note}</small>}
          </div>
        ))}
      </div>
      <p className="hint">{t("v5.mk.logscale")}</p>
      <TableView caption={t("v5.mk.h")} head={[t("v5.col.measure"), t("v5.col.value")]} rows={have.map((r) => [r.label, money(r.value)])} />
    </div>
  );
}

/* ---------------- 7 Powers radar (levels 0–3) ---------------- */
export function PowersRadar({ powers }: { powers: Power[] }) {
  const { t, fmt } = useI18n();
  const n = powers.length, cx = 170, cy = 140, R = 92;
  if (n < 3) return null;
  const pt = (i: number, r: number) => { const a = -Math.PI / 2 + (i * 2 * Math.PI) / n; return [cx + r * Math.cos(a), cy + r * Math.sin(a)] as const; };
  const name = (k: string) => t(("v5.pw." + k) as "v5.pw.network_effects");
  return (
    <svg className="chart" viewBox="0 0 340 290" role="img" aria-label={t("v5.mo.radar") + ": " + powers.map((p) => `${name(p.key)} ${p.level}/3`).join(", ")} style={{ maxWidth: 420, justifySelf: "center" }}>
      {[1, 2, 3].map((lv) => <polygon key={lv} points={powers.map((_, i) => pt(i, (R * lv) / 3).join(",")).join(" ")} fill="none" stroke={cv("--grid")} strokeWidth={1} />)}
      {powers.map((p, i) => {
        const [x, y] = pt(i, R), [lx, ly] = pt(i, R + 18);
        return (
          <g key={p.key}>
            <line x1={cx} y1={cy} x2={x} y2={y} stroke={cv("--grid")} />
            <text x={lx} y={ly + 4} fontSize={10.5} textAnchor={Math.abs(lx - cx) < 8 ? "middle" : lx > cx ? "start" : "end"} fill={cv("--muted")}>{name(p.key)}</text>
          </g>
        );
      })}
      <polygon points={powers.map((p, i) => pt(i, (R * Math.max(p.level, 0.08)) / 3).join(",")).join(" ")} fill={cv("--accent")} fillOpacity={0.12} stroke={cv("--accent")} strokeWidth={2} strokeLinejoin="round" />
      {powers.map((p, i) => {
        const [x, y] = pt(i, (R * p.level) / 3);
        return (
          <g key={p.key}>
            <circle cx={x} cy={y} r={4.5} fill={cv("--accent")} stroke={cv("--surface")} strokeWidth={2} />
            <circle cx={x} cy={y} r={13} fill="transparent" {...tip(`${name(p.key)} · ${t("v5.mo.level", { l: p.level })} · ${fmt(p.points)}/100`)} />
          </g>
        );
      })}
      <text x={cx + 4} y={cy - R + 12} fontSize={9} fill={cv("--faint")}>3</text>
    </svg>
  );
}

/* ---------------- football field ---------------- */
export function FootballField({ bars, value, low, high, offer, labelFor }: { bars: FieldBar[]; value: number; low: number; high: number; offer?: number | null; labelFor: (b: FieldBar) => string }) {
  const { money, fmt, t } = useI18n();
  const all = bars.flatMap((b) => [b.low_aud, b.high_aud, b.uncapped_mid_aud ?? b.mid_aud]).concat([low, high, value]).filter((x) => x > 0);
  const mn0 = Math.min(...all), mx0 = Math.max(...all);
  const log = mx0 / Math.max(mn0, 1) > 20;
  let ticks: number[];
  let X: (x: number) => number;
  if (log) {
    const a = Math.floor(Math.log10(mn0)), b = Math.ceil(Math.log10(mx0));
    ticks = Array.from({ length: b - a + 1 }, (_, i) => 10 ** (a + i));
    X = (x) => clamp(((Math.log10(Math.max(x, 1)) - a) / Math.max(b - a, 1)) * 100, 0, 100);
  } else {
    ticks = niceTicks(0, mx0 * 1.05, 4);
    const top = ticks[ticks.length - 1] || 1;
    X = (x) => clamp((x / top) * 100, 0, 100);
  }
  const sorted = [...bars].sort((a, b) => b.weight - a.weight);
  const on = sorted.filter((b) => b.weight > 0), off = sorted.filter((b) => !(b.weight > 0));
  const row = (b: FieldBar) => {
    const excl = !(b.weight > 0);
    const tt = `${labelFor(b)} · ${money(b.low_aud)} – ${money(b.high_aud)} · ${t("v5.ff.mid")} ${money(b.mid_aud)} · ${excl ? t("v5.ff.excl") + (b.excluded_reason ? ": " + b.excluded_reason : "") : t("v5.ff.counts", { w: fmt(b.weight * 100) })}`;
    return (
      <div key={b.method} className={"ffrow" + (excl ? " off" : "")} {...tip(tt)}>
        <div className="lb"><span>{labelFor(b)}{b.uses_projections ? " *" : ""}</span><span className="w">{excl ? t("v5.ff.excl") : t("v5.ff.counts", { w: fmt(b.weight * 100) })} · {money(b.mid_aud)}</span></div>
        <div className="tr" aria-hidden="true">
          <span className="bar" style={{ left: X(b.low_aud) + "%", width: Math.max(X(b.high_aud) - X(b.low_aud), 0.8) + "%" }} />
          <span className="mid" style={{ left: X(b.mid_aud) + "%" }} />
          {b.uncapped_mid_aud != null && b.uncapped_mid_aud !== b.mid_aud && <span className="unc" style={{ left: X(b.uncapped_mid_aud) + "%" }} {...tip(t("v5.ff.uncapped", { v: money(b.uncapped_mid_aud) }))} />}
        </div>
        {excl && b.excluded_reason && <span className="why">{b.excluded_reason}</span>}
      </div>
    );
  };
  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="legend5" aria-hidden="true">
        <span><i className="bar" style={{ borderRadius: 3 }} />{t("v5.ff.lg.range")}</span>
        <span><i className="mk" />{t("v5.ff.lg.blend")}</span>
        <span><i className="sw" style={{ background: "var(--gold-soft)", border: "1px solid var(--gold-mark)" }} />{t("v5.ff.lg.band")}</span>
        {offer != null && <span><i className="sw" style={{ background: "var(--c4)", transform: "rotate(45deg)", width: 8, height: 8 }} />{t("v5.ff.lg.offer")}</span>}
        <span><i className="bar" style={{ background: "var(--axis)", borderRadius: 3 }} />{t("v5.ff.lg.off")}</span>
      </div>
      <div className="ff ffwrap" role="img" aria-label={t("v5.ff.aria", { v: money(value), lo: money(low), hi: money(high) })}>
        <div className="plot">
          <span className="band" style={{ left: X(low) + "%", width: Math.max(X(high) - X(low), 0.5) + "%" }} />
          <span className="blend" style={{ left: X(value) + "%" }}><span>{money(value)}</span></span>
          {on.map(row)}
          {offer != null && <div className="ffrow"><div className="lb"><span>{t("v5.ff.offer")}</span><span className="w">{money(offer)}</span></div><div className="tr"><span className="diamond" style={{ left: X(offer) + "%" }} {...tip(t("v5.ff.offer") + " · " + money(offer))} /></div></div>}
          {off.map(row)}
        </div>
        <div className="axis" aria-hidden="true">{ticks.map((tk) => <span key={tk} style={{ left: X(tk) + "%" }}>{money(tk)}</span>)}</div>
      </div>
      {log && <p className="hint">{t("v5.ff.log")}</p>}
      <TableView caption={t("v5.va.ff")} head={[t("v5.col.method"), t("v5.col.low"), t("v5.col.mid"), t("v5.col.high"), t("v5.col.weight")]}
        rows={sorted.map((b) => [labelFor(b), money(b.low_aud), money(b.mid_aud), money(b.high_aud), b.weight > 0 ? fmt(b.weight * 100) + "%" : t("v5.ff.excl")])} />
    </div>
  );
}

/* ---------------- DCF sensitivity grid (diverging around the base) ---------------- */
export function SensGrid({ rates, gs, values, base, exit }: { rates: number[]; gs: number[]; values: (number | null)[][]; base: number; exit?: boolean }) {
  const { money, pct, fmt, t } = useI18n();
  const all = values.flat().filter((v): v is number => v != null && Number.isFinite(v));
  const span = Math.max(...all.map((v) => Math.abs(v / base - 1)), 0.01);
  const bg = (v: number) => {
    const d = v / base - 1, k = Math.round((Math.min(Math.abs(d) / span, 1)) * 55);
    return `color-mix(in srgb, var(${d >= 0 ? "--div-up" : "--div-dn"}) ${k}%, var(--div-mid))`;
  };
  const ri = Math.floor(rates.length / 2), gi = Math.floor(gs.length / 2);
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="tbl">
        <table className="sens">
          <caption className="sr-only">{t("v5.dcf.sens")}</caption>
          <thead><tr><th scope="col">{t("v5.dcf.rate")} ↓ · {exit ? t("v5.dcf.exitm") : "g"} →</th>{gs.map((g) => <th key={g} scope="col">{exit ? fmt(g, 1) + "×" : pct(g * 100, 1)}</th>)}</tr></thead>
          <tbody>
            {rates.map((r, i) => (
              <tr key={r}>
                <th scope="row">{pct(r * 100, 1)}</th>
                {gs.map((g, j) => {
                  const v = values[i]?.[j];
                  const ok = v != null && Number.isFinite(v);
                  return <td key={g} className={i === ri && j === gi ? "base" : undefined} style={{ background: ok ? bg(v) : undefined }} {...tip(`${t("v5.dcf.rate")} ${pct(r * 100, 1)} · ${exit ? fmt(g, 1) + "×" : "g " + pct(g * 100, 1)} · ${ok ? money(v) : "–"}`)}>{ok ? money(v) : "–"}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="legend5"><span><i className="sw" style={{ background: "var(--div-dn)" }} />{t("v5.dcf.lower")}</span><span><i className="sw" style={{ background: "var(--div-mid)", border: "1px solid var(--line)" }} />{t("v5.dcf.base")}</span><span><i className="sw" style={{ background: "var(--div-up)" }} />{t("v5.dcf.higher")}</span></div>
    </div>
  );
}

/* ---------------- line chart (growth series, cohort curves) — one y-axis, crosshair tooltip ---------------- */
export interface LineSeries { name: string; vals: (number | null)[]; color: string }
export function LineChart({ labels, series, fmtV, ariaLabel, yMax }: { labels: string[]; series: LineSeries[]; fmtV: (v: number) => string; ariaLabel: string; yMax?: number }) {
  const ref = useRef<SVGSVGElement>(null);
  const x0 = 56, x1 = 612, y0 = 14, y1 = 190, n = Math.max(labels.length, 2);
  const vals = series.flatMap((s) => s.vals.filter((v): v is number => v != null));
  const ticks = niceTicks(0, Math.max(yMax ?? 0, ...vals, 1), 4), top = ticks[ticks.length - 1];
  const X = (i: number) => x0 + ((x1 - x0) * i) / (n - 1), Y = (v: number) => y1 - ((y1 - y0) * v) / top;
  const path = (s: LineSeries) => { let d = "", pen = false; s.vals.forEach((v, i) => { if (v == null) { pen = false; return; } d += (pen ? " L" : " M") + X(i) + " " + Y(v); pen = true; }); return d.trim(); };
  const onMove = (e: React.PointerEvent) => {
    const b = ref.current!.getBoundingClientRect(), fx = ((e.clientX - b.left) / b.width) * 640;
    const i = clamp(Math.round(((fx - x0) / (x1 - x0)) * (n - 1)), 0, labels.length - 1);
    showTip(`${labels[i]} · ` + series.map((s) => `${series.length > 1 ? s.name + " " : ""}${s.vals[i] == null ? "–" : fmtV(s.vals[i]!)}`).join(" · "), e.clientX, e.clientY);
  };
  const stepX = Math.max(1, Math.ceil(labels.length / 6));
  return (
    <div className="stack" style={{ gap: 8 }}>
      {series.length > 1 && <div className="legend5">{series.map((s) => <span key={s.name}><i className="sw" style={{ background: cv(s.color), height: 3, width: 14, borderRadius: 2 }} />{s.name}</span>)}</div>}
      <svg ref={ref} className="chart" viewBox="0 0 640 220" role="img" aria-label={ariaLabel}>
        {ticks.map((tk) => (
          <g key={tk}>
            <line x1={x0} x2={x1} y1={Y(tk)} y2={Y(tk)} stroke={cv(tk === 0 ? "--axis" : "--grid")} />
            <text x={x0 - 8} y={Y(tk) + 4} fontSize={10.5} textAnchor="end" fill={cv("--faint")}>{fmtV(tk)}</text>
          </g>
        ))}
        {labels.map((l, i) => (i % stepX === 0 || i === labels.length - 1) && <text key={i} x={X(i)} y={210} fontSize={10.5} textAnchor={i === 0 ? "start" : i === labels.length - 1 ? "end" : "middle"} fill={cv("--faint")}>{l}</text>)}
        {series.map((s) => <path key={s.name} d={path(s)} fill="none" stroke={cv(s.color)} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />)}
        {series.map((s) => {
          const i = s.vals.map((v, k) => (v == null ? -1 : k)).filter((k) => k >= 0).pop();
          if (i == null) return null;
          return (
            <g key={s.name + "e"}>
              <circle cx={X(i)} cy={Y(s.vals[i]!)} r={4.5} fill={cv(s.color)} stroke={cv("--surface")} strokeWidth={2} />
              {series.length === 1 && <text x={X(i) - 8} y={Math.max(y0 + 10, Y(s.vals[i]!) - 10)} fontSize={12} fontWeight={700} textAnchor="end" fill={cv("--ink")}>{fmtV(s.vals[i]!)}</text>}
            </g>
          );
        })}
        <rect x={x0} y={y0} width={x1 - x0} height={y1 - y0} fill="transparent" onPointerMove={onMove} onPointerLeave={hideTip} />
      </svg>
    </div>
  );
}

/* ---------------- sub-metric view: cards on phones, table on wide screens (both carry the same data) ---------------- */
export function MetricList({ items }: { items: SubMetric[] }) {
  const { t, val, fmt } = useFmt5();
  const name = (m: SubMetric) => m.label || m.metric.replace(/_/g, " ");
  return (
    <div className="mcards">
      {items.map((m) => (
        <div className="mcard" key={m.key}>
          <div className="top">
            <span>{name(m)} <span className="muted-sm">×{fmt(m.weight, 2)}</span></span>
            <span className="row" style={{ gap: 6 }}><b>{val(m.value, m.unit)}</b><LevelBadge level={m.level} /></span>
          </div>
          {m.bench && m.value != null ? <BenchBar value={m.value} bench={m.bench} unit={m.unit} lowerBetter={m.lower_better} /> : m.value == null ? <span className="muted-sm">{t("v5.sm.missing")}</span> : null}
          <div className="between muted-sm">
            <span>{m.score == null ? t("v5.sm.noscore") : t("v5.sm.score", { s: fmt(m.score) })}{m.status && m.status !== "scored" && m.status !== "missing" ? <> · <span className="pill">{t(("v5.sm.st." + m.status) as "v5.sm.st.capped")}</span></> : null}{m.as_of ? " · " + m.as_of : ""}</span>
            {m.source_url || m.source ? <span>{t("v5.sm.src")}: {m.source_url ? <a href={m.source_url} target="_blank" rel="noopener noreferrer nofollow">{m.source || m.source_url.replace(/^https?:\/\/(www\.)?/, "").replace(/\/.*$/, "")}</a> : m.source}</span> : null}
          </div>
          {m.quote && <q>{m.quote}</q>}
          {m.note && <span className="hint">{m.note}</span>}
        </div>
      ))}
    </div>
  );
}
