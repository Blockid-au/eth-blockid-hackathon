/* Hand-drawn SVG charts, ported 1:1 from docs/prototype.html. Colours are CSS tokens so light/dark follow the theme. */
import { useRef, type ReactNode } from "react";
import { arrow, useI18n } from "../i18n";
import { niceTicks, GRADE_C } from "../lib/math";
import { hideTip, showTip, tip } from "../lib/tip";

const v = (name: string) => `var(${name})`;

/* ---------- sparkline ---------- */
export function Spark({ vals, cls, w = 88, h = 26, className = "spark" }: { vals: number[]; cls: "up" | "down" | "flat"; w?: number; h?: number; className?: string }) {
  const data = vals.length >= 2 ? vals : vals.length === 1 ? [vals[0], vals[0]] : [0, 0];
  const mn = Math.min(...data), mx = Math.max(...data);
  const Y = (x: number) => (mx === mn ? h / 2 : h - 3 - ((x - mn) / (mx - mn)) * (h - 6));
  const pts = data.map((x, i) => [(i / (data.length - 1)) * (w - 4) + 2, Y(x)] as const);
  const col = v(cls === "up" ? "--up" : cls === "down" ? "--down" : "--faint");
  const last = pts[pts.length - 1];
  return (
    <svg className={className} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <polyline points={pts.map((p) => p.join(",")).join(" ")} fill="none" stroke={col} strokeWidth={1.8} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r={2.4} fill={col} />
    </svg>
  );
}

/* ---------- KPI tile with sparkline + delta ---------- */
export function KTile({ label, value, p, series, sub }: { label: string; value: string; p?: number | null; series: number[]; sub?: string }) {
  const { t, chg } = useI18n();
  const cls = arrow(p ?? 0);
  return (
    <div className="ktile">
      <small>{label}</small>
      <b>{value}</b>
      <div className="foot">
        <span className={"chg " + (p == null ? "flat" : cls)}>{p == null ? sub ?? "" : chg(p) + " " + t("ad.k.30d")}</span>
        <Spark vals={series} cls={p == null ? "flat" : cls} w={72} h={24} className="" />
      </div>
    </div>
  );
}

/* ---------- ownership ring / donut ---------- */
export interface Part { name: string; v: number; c: string; tip?: string }
export function Ring({ parts, size = 120, r = 44, sw = 18, gapDeg = 1.2, children, label }: { parts: Part[]; size?: number; r?: number; sw?: number; gapDeg?: number; children?: ReactNode; label: string }) {
  const C = 2 * Math.PI * r, total = parts.reduce((a, p) => a + Math.max(p.v, 0), 0) || 1, cx = size / 2;
  let off = 0;
  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="chart" role="img" aria-label={label} style={{ maxWidth: size }}>
      {parts.length === 0 && <circle cx={cx} cy={cx} r={r} fill="none" stroke={v("--line")} strokeWidth={sw} />}
      {parts.map((p, i) => {
        const len = (Math.max(p.v, 0) / total) * C, gap = (gapDeg / 360) * C;
        const el = (
          <circle key={i} cx={cx} cy={cx} r={r} fill="none" stroke={v(p.c)} strokeWidth={sw} strokeDasharray={`${Math.max(len - gap, 0)} ${C}`} strokeDashoffset={-off} transform={`rotate(-90 ${cx} ${cx})`} {...(p.tip ? tip(p.tip) : {})} />
        );
        off += len;
        return el;
      })}
      {children}
    </svg>
  );
}

export function Donut({ parts, center, sub, label }: { parts: Part[]; center: string; sub: string; label: string }) {
  return (
    <div className="donutwrap">
      <Ring parts={parts} size={260} r={92} sw={30} gapDeg={(2 / (2 * Math.PI * 92)) * 360} label={label}>
        <text x={130} y={126} textAnchor="middle" fontSize={24} fontWeight={800} fill={v("--ink")} fontFamily="Be Vietnam Pro, sans-serif">{center}</text>
        <text x={130} y={148} textAnchor="middle" fontSize={12} fill={v("--muted")}>{sub}</text>
      </Ring>
    </div>
  );
}

export function Legend({ parts, digits = 1 }: { parts: { name: string; c: string; pct: number }[]; digits?: number }) {
  const { fmt } = useI18n();
  return (
    <div className="legendrow">
      {parts.map((p, i) => (
        <span key={i}><i className="sw" style={{ background: v(p.c) }} />{p.name} {fmt(p.pct, digits)}%</span>
      ))}
    </div>
  );
}

/* ---------- SVI radar ---------- */
export interface DimRow { key: string; label: string; score: number; weight: number; basis?: string; rationale?: string }
export function Radar({ dims }: { dims: DimRow[] }) {
  const { fmt } = useI18n();
  const cx = 180, cy = 150, R = 100, n = Math.max(dims.length, 3);
  const pt = (i: number, r: number) => { const a = -Math.PI / 2 + (i * 2 * Math.PI) / n; return [cx + r * Math.cos(a), cy + r * Math.sin(a)] as const; };
  return (
    <svg className="chart" viewBox="0 0 360 300" role="img" aria-label={"SVI radar: " + dims.map((d) => `${d.label} ${fmt(d.score)}`).join(", ")}>
      {[25, 50, 75, 100].map((lv) => (
        <polygon key={lv} points={dims.map((_, i) => pt(i, (R * lv) / 100).join(",")).join(" ")} fill="none" stroke={v("--line")} strokeWidth={1} />
      ))}
      <text x={cx + 4} y={cy - R / 2 + 4} fontSize={10} fill={v("--faint")}>50</text>
      <text x={cx + 4} y={cy - R + 4} fontSize={10} fill={v("--faint")}>100</text>
      {dims.map((d, i) => {
        const [x, y] = pt(i, R), [lx, ly] = pt(i, R + 22);
        return (
          <g key={d.key}>
            <line x1={cx} y1={cy} x2={x} y2={y} stroke={v("--line")} />
            <text x={lx} y={ly + 4} fontSize={11.5} textAnchor={Math.abs(lx - cx) < 8 ? "middle" : lx > cx ? "start" : "end"} fill={v("--muted")}>{d.label}</text>
          </g>
        );
      })}
      <polygon points={dims.map((d, i) => pt(i, (R * d.score) / 100).join(",")).join(" ")} fill={v("--accent")} fillOpacity={0.16} stroke={v("--accent")} strokeWidth={2} strokeLinejoin="round" />
      {dims.map((d, i) => {
        const [x, y] = pt(i, (R * d.score) / 100);
        const label = `${d.label} · ${fmt(d.score)}/100 · ${fmt(d.weight * 100)}%${d.basis ? " · " + d.basis : ""}`;
        return (
          <g key={d.key}>
            <circle cx={x} cy={y} r={4.5} fill={v("--accent")} stroke={v("--surface")} strokeWidth={2} />
            <circle cx={x} cy={y} r={12} fill="transparent" {...tip(label)} />
          </g>
        );
      })}
    </svg>
  );
}

export function Contrib({ dims, totalLabel }: { dims: DimRow[]; totalLabel: string }) {
  const { fmt, t } = useI18n();
  let sum = 0;
  return (
    <div className="contrib">
      {dims.map((d) => {
        const c = d.score * d.weight;
        sum += c;
        return (
          <div className="r" key={d.key} title={d.rationale || undefined}>
            <span>{d.label} · {fmt(d.score)}{d.basis === "self_reported" && <> <span className="pill sr" title={t("sr.chip.tip")}>{t("sr.chip")}</span></>}</span>
            <span className="t"><i style={{ width: Math.max(0, Math.min(100, d.score)) + "%" }} /></span>
            <span className="w">×{fmt(d.weight, 2)}</span>
            <span className="v">{fmt(c, 1)}</span>
          </div>
        );
      })}
      <div className="r sum"><span>{totalLabel}</span><span /><span /><span className="v">{fmt(sum, 1)}</span></div>
    </div>
  );
}

/* ---------- valuation range ---------- */
export function RangeChart({ low, mid, high }: { low: number; mid: number; high: number }) {
  const { money } = useI18n();
  const ticks = niceTicks(0, Math.max(high * 1.3, 1), 6), max = ticks[ticks.length - 1];
  const x0 = 20, x1 = 440, X = (x: number) => x0 + ((x1 - x0) * x) / max;
  const clampLbl = (x: number) => Math.min(Math.max(x, 40), 420);
  return (
    <svg className="chart" viewBox="0 0 460 96" role="img" aria-label={`Valuation range ${money(low)} to ${money(high)}, mid ${money(mid)}`}>
      <rect x={x0} y={34} width={x1 - x0} height={10} rx={5} fill={v("--sunken")} />
      <rect x={X(low)} y={34} width={Math.max(X(high) - X(low), 2)} height={10} rx={5} fill={v("--accent")} fillOpacity={0.35} />
      {ticks.map((tk) => (
        <text key={tk} x={X(tk)} y={88} fontSize={10.5} textAnchor="middle" fill={v("--faint")}>{money(tk)}</text>
      ))}
      {[low, high].map((x, i) => <line key={i} x1={X(x)} x2={X(x)} y1={28} y2={50} stroke={v("--accent")} strokeWidth={2} />)}
      <circle cx={X(mid)} cy={39} r={8} fill={v("--accent")} stroke={v("--surface")} strokeWidth={3} />
      <text x={clampLbl(X(mid))} y={20} fontSize={13} fontWeight={700} textAnchor="middle" fill={v("--ink")}>{money(mid)}</text>
      <text x={clampLbl(X(low))} y={66} fontSize={11} textAnchor="middle" fill={v("--muted")}>{money(low)}</text>
      <text x={clampLbl(X(high))} y={66} fontSize={11} textAnchor="middle" fill={v("--muted")}>{money(high)}</text>
    </svg>
  );
}

/* ---------- horizontal bars (competitors, dividends) ---------- */
export interface HBar { name: string; value: number | null; color: string; label: string; tip: string }
export function HBars({ rows, x0 = 120, x1 = 400, rowH = 34, ndLabel, ariaLabel, axis }: { rows: HBar[]; x0?: number; x1?: number; rowH?: number; ndLabel?: string; ariaLabel: string; axis?: boolean }) {
  const { fmt } = useI18n();
  const max = Math.max(...rows.map((r) => r.value ?? 0), 0);
  const ticks = axis ? niceTicks(0, max || 1, 3) : [];
  const top = axis ? ticks[ticks.length - 1] : max || 1;
  const X = (x: number) => x0 + ((x1 - x0) * x) / top;
  const H = 12 + rows.length * rowH + (axis ? 24 : 0);
  const trunc = (s: string) => (s.length > 17 ? s.slice(0, 16) + "…" : s);
  return (
    <svg className="chart" viewBox={`0 0 460 ${H}`} role="img" aria-label={ariaLabel}>
      {axis && ticks.map((tk, i) => (
        <g key={tk}>
          <line x1={X(tk)} x2={X(tk)} y1={6} y2={H - 24} stroke={v("--line")} strokeDasharray={i ? "3 4" : undefined} />
          <text x={X(tk)} y={H - 8} fontSize={10.5} textAnchor="middle" fill={v("--faint")}>{fmt(tk, tk % 1 ? 1 : 0)}</text>
        </g>
      ))}
      {rows.map((r, i) => {
        const y = (axis ? 12 : 8) + i * rowH;
        const w = r.value == null ? 0 : Math.max(X(r.value) - x0, 0);
        return (
          <g key={i}>
            <text x={x0 - 10} y={y + 15} fontSize={12} textAnchor="end" fill={v("--ink")}>{trunc(r.name)}</text>
            {r.value == null ? (
              <text x={x0 + 2} y={y + 15} fontSize={11.5} fontStyle="italic" fill={v("--faint")}>{ndLabel}</text>
            ) : (
              <>
                {w > 4 && <path d={`M${x0} ${y + 4} h${w - 4} a4 4 0 0 1 4 4 v8 a4 4 0 0 1 -4 4 h${-(w - 4)} z`} fill={v(r.color)} />}
                <text x={x0 + w + 6} y={y + 15} fontSize={11.5} fontWeight={600} fill={v("--muted")}>{r.label}</text>
              </>
            )}
            <rect x={0} y={y} width={460} height={rowH - 4} fill="transparent" {...tip(r.tip)} />
          </g>
        );
      })}
    </svg>
  );
}

/* ---------- 100% bars (dilution before / after) ---------- */
export function Bars100({ label, parts }: { label: string; parts: { name: string; v: number; c: string }[] }) {
  const { fmt } = useI18n();
  const tot = parts.reduce((a, p) => a + p.v, 0) || 1;
  return (
    <div className="bars100">
      <div className="lab"><span>{label}</span><span className="num">{fmt(parts.reduce((a, p) => a + p.v, 0))}</span></div>
      <div className="s">
        {parts.filter((p) => p.v > 0).map((p, i) => (
          <i key={i} style={{ width: (p.v / tot) * 100 + "%", background: v(p.c) }} {...tip(() => `${p.name} · ${fmt((p.v / tot) * 100, 1)}%`)} />
        ))}
      </div>
    </div>
  );
}

/* ---------- grade bars ---------- */
export function GradeChart({ grades, extra }: { grades: Record<string, number>; extra?: (g: string) => string }) {
  const { fmt, t } = useI18n();
  const G = ["A", "B", "C", "D", "E"], n = G.map((g) => grades[g] ?? 0), mx = Math.max(...n, 1);
  const x0 = 34, y1 = 150, bw = 38, gap = 16, H = 120;
  return (
    <svg className="chart" viewBox="0 0 300 190" role="img" aria-label={"Company count by SVI grade: " + G.map((g, i) => `${g} ${n[i]}`).join(", ")}>
      {G.map((g, i) => {
        const h = (n[i] / mx) * H, x = x0 + i * (bw + gap);
        return (
          <g key={g}>
            {n[i] > 0 && <path d={`M${x} ${y1} V${y1 - h + 4} a4 4 0 0 1 4 -4 h${bw - 8} a4 4 0 0 1 4 4 V${y1} Z`} fill={v(GRADE_C[g])} />}
            <text x={x + bw / 2} y={y1 - h - 6} fontSize={12} fontWeight={700} textAnchor="middle" fill={v("--ink")}>{fmt(n[i])}</text>
            <text x={x + bw / 2} y={y1 + 18} fontSize={12} textAnchor="middle" fill={v("--muted")}>{g}</text>
            <rect x={x} y={y1 - H} width={bw} height={H} fill="transparent" {...tip(() => `${t("ad.c.grade")} ${g} · ${n[i]}${extra ? " · " + extra(g) : ""}`)} />
          </g>
        );
      })}
      <line x1={26} x2={290} y1={y1} y2={y1} stroke={v("--line")} />
    </svg>
  );
}

/* ---------- y axis helper ---------- */
export function AxisY({ x0, x1, Y, ticks, f }: { x0: number; x1: number; Y: (v: number) => number; ticks: number[]; f: (v: number) => string }) {
  return (
    <>
      {ticks.map((tk) => (
        <g key={tk}>
          <line x1={x0} x2={x1} y1={Y(tk)} y2={Y(tk)} stroke={v("--line")} strokeDasharray="3 4" />
          <text x={x0 - 8} y={Y(tk) + 4} fontSize={10.5} textAnchor="end" fill={v("--faint")}>{f(tk)}</text>
        </g>
      ))}
    </>
  );
}

/* ---------- step-area over time (platform value) ---------- */
export interface Pin { i: number; label: string }
export function StepArea({ labels, vals, pins, fmtV, fmtX, ariaLabel }: { labels: string[]; vals: number[]; pins: Pin[]; fmtV: (v: number) => string; fmtX: (i: number) => string; ariaLabel: string }) {
  const ref = useRef<SVGSVGElement>(null);
  const x0 = 64, x1 = 626, y0 = 16, y1 = 206;
  const n = Math.max(vals.length, 2);
  const data = vals.length ? vals : [0, 0];
  const mx = Math.max(...data, 1) * 1.08, ticks = niceTicks(0, mx), top = ticks[ticks.length - 1];
  const X = (i: number) => x0 + ((x1 - x0) * i) / (n - 1), Y = (x: number) => y1 - ((y1 - y0) * x) / top;
  let d = `M${X(0)} ${Y(data[0])}`;
  data.forEach((x, i) => { if (i) d += ` H${X(i)} V${Y(x)}`; });
  if (data.length === 1) d += ` H${X(1)}`;
  const last = data.length - 1;
  const onMove = (e: React.PointerEvent) => {
    const b = ref.current!.getBoundingClientRect(), fx = ((e.clientX - b.left) / b.width) * 640;
    const i = Math.max(0, Math.min(last, Math.round(((fx - x0) / (x1 - x0)) * (n - 1))));
    showTip(`${fmtX(i)} · ${fmtV(data[i])}`, e.clientX, e.clientY);
  };
  return (
    <svg ref={ref} className="chart" viewBox="0 0 640 240" role="img" aria-label={ariaLabel}>
      <AxisY x0={x0} x1={x1} Y={Y} ticks={ticks} f={fmtV} />
      <path d={d + ` V${y1} H${X(0)} Z`} fill={v("--accent")} fillOpacity={0.12} />
      <path d={d} fill="none" stroke={v("--accent")} strokeWidth={2} />
      {labels.length > 1 && [0, 0.25, 0.5, 0.75, 1].map((f) => {
        const i = Math.round(f * last);
        return <text key={f} x={X(i)} y={228} fontSize={10.5} textAnchor={f === 0 ? "start" : f === 1 ? "end" : "middle"} fill={v("--faint")}>{fmtX(i)}</text>;
      })}
      {pins.map((p, k) => (
        <g key={k}>
          <circle cx={X(p.i)} cy={Y(data[p.i])} r={4} fill={v("--gold-mark")} stroke={v("--surface")} strokeWidth={2} />
        </g>
      ))}
      <circle cx={X(last)} cy={Y(data[last])} r={5} fill={v("--accent")} stroke={v("--surface")} strokeWidth={2} />
      <text x={X(last) - 8} y={Y(data[last]) - 10} fontSize={12} fontWeight={700} textAnchor="end" fill={v("--ink")}>{fmtV(data[last])}</text>
      <rect x={x0} y={y0} width={x1 - x0} height={y1 - y0} fill="transparent" onPointerMove={onMove} onPointerLeave={hideTip} />
      {pins.map((p, k) => (
        <circle key={"h" + k} cx={X(p.i)} cy={Y(data[p.i])} r={11} fill="transparent" {...tip(p.label)} />
      ))}
    </svg>
  );
}

/* ---------- range tabs ---------- */
export function Ranges<T extends string | number>({ opts, value, onChange, label }: { opts: [string, T][]; value: T; onChange: (v: T) => void; label: string }) {
  return (
    <span className="ranges" role="group" aria-label={label}>
      {opts.map(([l, x]) => (
        <button key={l} type="button" aria-pressed={x === value} onClick={() => onChange(x)}>{l}</button>
      ))}
    </span>
  );
}
