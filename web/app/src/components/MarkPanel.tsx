import { useMemo, useRef, useState, useEffect } from "react";
import { arrow, useI18n } from "../i18n";
import type { CoEvent, Mark } from "../api";
import { DAY, fan, GBM, niceTicks } from "../lib/math";
import { hideTip, showTip, tip } from "../lib/tip";
import { AxisY, KTile, Ranges } from "./charts";

const v = (n: string) => `var(${n})`;
const HORIZON = 180;

export interface MarkPanelProps {
  ticker: string;
  name: string;
  grade: string;
  svi?: number | null;
  marks: Mark[];
  events?: CoEvent[];
  valuation: number;
  totalShares: number;
  holders: number;
  /** show the 4 KPI tiles under the chart (admin detail layout) */
  kpis?: boolean;
}

interface Pt { t: number; m: number }

export function MarkPanel(p: MarkPanelProps) {
  const { t, fmt, aud, money, chg, date } = useI18n();
  const [range, setRange] = useState<number>(0);
  const [sim, setSim] = useState(false);
  const [simTick, setSimTick] = useState(0);
  const ref = useRef<SVGSVGElement>(null);
  const now = useMemo(() => Date.now(), [p.marks]); // eslint-disable-line react-hooks/exhaustive-deps

  const series: Pt[] = useMemo(() => {
    const s = p.marks
      .map((m) => ({ t: +new Date(m.at), m: Number(m.mark_aud) }))
      .filter((x) => Number.isFinite(x.t) && Number.isFinite(x.m))
      .sort((a, b) => a.t - b.t);
    return s.length ? s : [{ t: now - DAY, m: 1 }];
  }, [p.marks, now]);

  useEffect(() => {
    if (!sim) return;
    const id = setInterval(() => { if (!document.hidden) setSimTick((x) => x + 1); }, 3000);
    return () => clearInterval(id);
  }, [sim]);

  const issueT = series[0].t;
  const markAtT = (tt: number) => { let m: number | null = null; for (const x of series) if (x.t <= tt) m = x.m; return m; };
  const mNow = series[series.length - 1].m;
  const issueAgo = Math.max((now - issueT) / DAY, 1);
  const since = range ? Math.min(range, issueAgo) : issueAgo; // days ago at left edge
  const startT = now - since * DAY;
  const mStart = markAtT(startT) ?? series[0].m;
  const pR = (mNow / (mStart || 1) - 1) * 100;
  const yrs = issueAgo / 365;
  const cagr = (Math.pow(mNow / (series[0].m || 1), 1 / Math.max(yrs, 1 / 12)) - 1) * 100;

  const F = useMemo(() => (sim ? fan(p.ticker, p.grade, mNow, HORIZON) : []), [sim, p.ticker, p.grade, mNow]);

  const x0 = 58, x1 = 744, y0 = 18, y1 = 240;
  const dMin = -(sim ? HORIZON : 0), dMax = since;
  const X = (dAgo: number) => x0 + ((x1 - x0) * (dMax - dAgo)) / (dMax - dMin);
  const ago = (tt: number) => (now - tt) / DAY;
  const inRange = series.filter((x) => x.t > startT);
  const all = [mStart, ...inRange.map((x) => x.m), 1].concat(F.flatMap((f) => [f.p10, f.p90]));
  const ticks = niceTicks(Math.min(...all) * 0.92, Math.max(...all) * 1.06), lo = ticks[0], hi = ticks[ticks.length - 1];
  const Y = (x: number) => y1 - ((y1 - y0) * (x - lo)) / (hi - lo || 1);

  let d = `M${X(since)} ${Y(mStart)}`;
  inRange.forEach((x) => { d += ` H${X(ago(x.t))} V${Y(x.m)}`; });
  d += ` H${X(0)}`;
  const up = mNow >= mStart;

  // pins: mark changes (issuance / revaluation) + mint / dividend events
  const pins: { dAgo: number; m: number; label: string }[] = [];
  p.marks.forEach((m, i) => {
    const tt = +new Date(m.at);
    if (tt < startT - 1) return;
    const prev = i > 0 ? p.marks[i - 1] : null;
    const lbl = m.source === "issuance"
      ? `${t("ad.ev.iss")} · ${aud(Number(m.mark_aud))}`
      : `${t("ad.ev.rv")} · ${prev ? aud(Number(prev.mark_aud), 3) + " → " : ""}${aud(Number(m.mark_aud), 3)} · ${money(Number(m.mark_aud) * p.totalShares)}`;
    pins.push({ dAgo: ago(tt), m: Number(m.mark_aud), label: `${date(tt)} · ${lbl}` });
  });
  (p.events ?? []).forEach((e) => {
    if (e.kind !== "minted" && e.kind !== "dividend_created") return;
    const tt = +new Date(e.at);
    if (!Number.isFinite(tt) || tt < startT) return;
    pins.push({ dAgo: ago(tt), m: markAtT(tt) ?? mNow, label: `${date(tt)} · ${t(("ev." + e.kind) as "ev.minted")}` });
  });

  const onMove = (e: React.PointerEvent) => {
    const b = ref.current!.getBoundingClientRect(), fx = ((e.clientX - b.left) / b.width) * 760;
    const dAgo = dMax - ((fx - x0) / (x1 - x0)) * (dMax - dMin);
    if (dAgo < 0) {
      const k = Math.max(0, Math.min(F.length - 1, Math.round((-dAgo / HORIZON) * (F.length - 1))));
      const f = F[k];
      if (f) showTip(`${t("ad.simbadge")} +${fmt(f.d)}d · P10 ${aud(f.p10, 2)} · P50 ${aud(f.p50, 2)} · P90 ${aud(f.p90, 2)}`, e.clientX, e.clientY);
      return;
    }
    const tt = now - dAgo * DAY;
    showTip(`${date(tt)} · ${aud(markAtT(tt) ?? mStart, 3)}`, e.clientX, e.clientY);
  };

  const [mu, sg] = GBM[p.grade] ?? GBM.C;
  const band = (a: "p90" | "p75", b: "p10" | "p25", op: number) => {
    let dd = `M${X(-F[0].d)} ${Y(F[0][a])}`;
    F.forEach((f) => { dd += ` L${X(-f.d)} ${Y(f[a])}`; });
    F.slice().reverse().forEach((f) => { dd += ` L${X(-f.d)} ${Y(f[b])}`; });
    return <path d={dd + "Z"} fill={v("--c5")} fillOpacity={op} />;
  };
  const live = sim && F[1] ? F[1].p50 * (1 + Math.sin(simTick / 3) * 0.004) : mNow;
  const ser = Array.from({ length: 19 }, (_, i) => markAtT(now - since * DAY * (1 - i / 18)) ?? mStart);

  return (
    <>
      <div className="pane">
        <div className="detail-head">
          <div style={{ display: "grid", gap: 6 }}>
            <span className="eyebrow">{p.ticker} · {p.name} · {t("ad.c.grade")} {p.grade}{p.svi != null ? ` · SVI ${fmt(Number(p.svi), 1)}` : ""}</span>
            <span className="px">{aud(mNow, 3)}</span>
            <span className={"chg " + arrow(pR)}>{chg(pR)} · {t("ad.range")} · {t("ad.cagr")} {fmt(cagr, 1)}%</span>
          </div>
          <div style={{ display: "grid", gap: 8, justifyItems: "end" }}>
            <Ranges label={t("ad.range")} opts={[["1M", 30], ["3M", 90], ["6M", 180], [t("ad.r.all"), 0]]} value={range} onChange={setRange} />
            <label className="toggle">
              <input type="checkbox" checked={sim} onChange={(e) => setSim(e.target.checked)} />
              <span>{t("ad.simt")}</span><span className="simbadge">{t("ad.simbadge")}</span>
            </label>
          </div>
        </div>
        <div className="chartscroll">
        <svg ref={ref} className="chart" viewBox="0 0 760 280" role="img" aria-label={`${p.ticker} · ${t("ad.l.mark")}${sim ? " · " + t("ad.l.sim") : ""}`}>
          <AxisY x0={x0} x1={x1} Y={Y} ticks={ticks} f={(x) => "A$" + fmt(x, 2)} />
          {1 >= lo && 1 <= hi && (
            <>
              <line x1={x0} x2={x1} y1={Y(1)} y2={Y(1)} stroke={v("--muted")} strokeWidth={1} strokeDasharray="2 3" />
              <text x={x1} y={Y(1) - 5} fontSize={10} textAnchor="end" fill={v("--muted")}>{t("ad.issue1")}</text>
            </>
          )}
          {sim && F.length > 0 && (
            <>
              {band("p90", "p10", 0.12)}
              {band("p75", "p25", 0.2)}
              <polyline points={F.map((f) => `${X(-f.d)},${Y(f.p50)}`).join(" ")} fill="none" stroke={v("--c5")} strokeWidth={2} strokeDasharray="6 5" />
              <line x1={X(0)} x2={X(0)} y1={y0} y2={y1} stroke={v("--line")} />
              <text x={X(0) + 6} y={y0 + 10} fontSize={10} fill={v("--c5")} fontWeight={700}>{t("ad.simbadge")} →</text>
              <text x={x1 - 2} y={Y(F[F.length - 1].p50) - 8} fontSize={11} textAnchor="end" fill={v("--c5")}>P50 A${fmt(F[F.length - 1].p50, 2)}</text>
            </>
          )}
          <path d={d + ` V${y1} H${X(since)} Z`} fill={v(up ? "--up" : "--down")} fillOpacity={0.08} />
          <path d={d} fill="none" stroke={v("--accent")} strokeWidth={2.2} />
          <rect x={x0} y={y0} width={x1 - x0} height={y1 - y0} fill="transparent" onPointerMove={onMove} onPointerLeave={hideTip} />
          {pins.map((pn, i) => {
            const x = X(pn.dAgo), y = Y(pn.m);
            return (
              <g key={i}>
                <line x1={x} x2={x} y1={y + 6} y2={y1} stroke={v("--gold-mark")} strokeDasharray="2 3" />
                <circle cx={x} cy={y} r={5} fill={v("--gold-mark")} stroke={v("--surface")} strokeWidth={2} />
                <circle cx={x} cy={y} r={12} fill="transparent" {...tip(pn.label)} />
              </g>
            );
          })}
          <circle cx={X(0)} cy={Y(mNow)} r={5.5} fill={v("--accent")} stroke={v("--surface")} strokeWidth={2} />
          {X(0) - X(since) > 110 && <text x={X(since)} y={262} fontSize={10.5} textAnchor="start" fill={v("--faint")}>{date(startT)}</text>}
          <text x={X(0)} y={262} fontSize={10.5} textAnchor={sim ? "middle" : "end"} fill={v("--faint")}>{t("ad.today")}</text>
          {sim && <text x={x1} y={262} fontSize={10.5} textAnchor="end" fill={v("--faint")}>+180d</text>}
        </svg>
        </div>
        <div className="legendrow">
          <span><i className="sw" style={{ background: v("--accent") }} />{t("ad.l.mark")}</span>
          <span><i className="sw" style={{ background: v("--c5"), opacity: 0.5 }} />{t("ad.l.sim")}</span>
          <span><i className="sw" style={{ background: v("--gold-mark") }} />{t("ad.l.ev")}</span>
        </div>
        <p className="note">{sim ? t("ad.simnote", { g: p.grade, mu: fmt(mu * 100), sg: fmt(sg * 100), seed: p.ticker }) : t("ad.marknote")}</p>
      </div>
      {p.kpis && (
        <div className="kgrid">
          <KTile label={t("ad.c.val")} value={money(p.valuation)} p={(mNow - 1) * 100} series={ser} />
          <KTile label={t("ad.k.sh")} value={fmt(p.totalShares)} p={null} series={ser.map(() => 1)} sub={t("ad.k.issued1")} />
          <KTile label={t("ad.c.hold")} value={fmt(p.holders)} p={null} series={ser.map((_, i) => Math.min(p.holders, 2 + i))} sub={t("ad.k.kyc")} />
          <KTile label={sim ? t("ad.k.simlive") : t("ad.k.mark")} value={aud(live, 3)} p={sim ? (live / mNow - 1) * 100 : null} series={ser} sub={sim ? "" : t("ad.k.asof")} />
        </div>
      )}
    </>
  );
}
