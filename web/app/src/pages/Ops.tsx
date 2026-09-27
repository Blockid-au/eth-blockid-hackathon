/* Admin "Operations" — /admin/ops/:tab (docs/PLAN-OPS.md §1–5). Tabs: Overview · Incidents · Traffic & users · Errors ·
   Weekly reports. Data: /v1/admin/ops/* (agents/src/blockid_agents/ops/), mocked in mock.ops.ts. Overview and Incidents
   refresh every 30 s. Charts follow the dataviz rules: one axis, solid hairline grid, 2 px lines, legend + selective
   direct labels, crosshair / per-mark tooltips, a table view; series colours --c1 (eth) / --c3 (hr), validated for CVD. */
import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { opsApi, type OpsEmailLog, type OpsError, type OpsIncident, type OpsReport, type OpsSendResult, type OpsSeverity, type OpsStats, type OpsSummary, type OpsTrafficDay } from "../api";
import { aiApi } from "./AiHealth";
import { errText, useAuth } from "../auth";
import { useI18n } from "../i18n";
import { useAsync, useNow } from "../lib/hooks";
import { niceTicks } from "../lib/math";
import { hideTip, showTip, tip } from "../lib/tip";
import { ErrorBox } from "../components/Layout";
import { StatusBar, type Tone } from "../components/StatusBar";
import { Ranges } from "../components/charts";
import type { DictKey } from "../dict";
import "./ops.css";

const TABS = ["overview", "incidents", "traffic", "errors", "reports"] as const;
type Tab = (typeof TABS)[number];
const REFRESH = 30000;
const RUNBOOK = "https://github.com/Blockid-au/eth-blockid/blob/main/docs/RUNBOOK-INCIDENTS.md";
const SEV_TONE: Record<string, string> = { critical: "bad", warn: "warn", info: "idle" };
const SEV_ICON: Record<string, string> = { critical: "✕", warn: "▲", info: "●" };
const ST_TONE: Record<string, string> = { open: "bad", acknowledged: "warn", resolved: "ok" };
const HOST_C = ["--c1", "--c3", "--c4", "--c5"]; // fixed order, validated (light + dark) — colour follows the host
const cv = (n: string) => `var(${n})`;

/** Translate with a fallback when the key is unknown (new values from the API). */
function useTx() {
  const { t } = useI18n();
  return (key: string, fallback: string, vars?: Record<string, string | number>) => {
    const s = t(key as DictKey, vars);
    return s === key ? fallback : s;
  };
}

function useWidth<T extends HTMLElement>(): [React.RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(600);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setW(el.clientWidth || 600);
    const ro = new ResizeObserver(() => setW(el.clientWidth || 600));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

function useToast(): [string, (s: string) => void] {
  const [m, setM] = useState("");
  useEffect(() => { if (!m) return; const x = setTimeout(() => setM(""), 6000); return () => clearTimeout(x); }, [m]);
  return [m, setM];
}

/* ================= small pieces ================= */
export function SevPill({ s }: { s: OpsSeverity | string }) {
  const tx = useTx();
  return <span className={"opspill " + (SEV_TONE[s] ?? "idle")}><i aria-hidden="true">{SEV_ICON[s] ?? "●"}</i>{tx("ops.sev." + s, s)}</span>;
}
function StPill({ s }: { s: string }) {
  const tx = useTx();
  return <span className={"opspill soft " + (ST_TONE[s] ?? "idle")}>{tx("ops.st." + s, s)}</span>;
}
function MailPill({ s }: { s: string }) {
  const tx = useTx();
  const tone = s === "sent" ? "ok" : s === "failed" ? "bad" : s === "pending" ? "idle" : "warn";
  return <span className={"opspill soft " + tone}>{tx("ops.mail." + s, s)}</span>;
}

/** Tiny trend line: de-emphasis ink, the current point in the accent (stat-tile contract). */
function Trend({ vals }: { vals: number[] }) {
  if (vals.length < 2) return null;
  const w = 76, h = 26, mn = Math.min(...vals), mx = Math.max(...vals);
  const Y = (x: number) => (mx === mn ? h / 2 : h - 4 - ((x - mn) / (mx - mn)) * (h - 8));
  const pts = vals.map((x, i) => [(i / (vals.length - 1)) * (w - 8) + 4, Y(x)] as const);
  const last = pts[pts.length - 1];
  return (
    <svg className="opsspark" viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <polyline points={pts.map((p) => p.join(",")).join(" ")} fill="none" stroke={cv("--faint")} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r={3.5} fill={cv("--accent")} stroke={cv("--surface")} strokeWidth={1.5} />
    </svg>
  );
}

/** Stat tile: label · value · signed change vs a named period (colour = direction × whether up is good) · trend.
 *  `note` replaces the change line when there is no earlier period to compare with. */
function Stat({ label, k, fmtV, period, upGood = true, extra, note }: { label: string; k?: Kpi; fmtV?: (n: number) => string; period: string; upGood?: boolean; extra?: ReactNode; note?: ReactNode }) {
  const { fmt, t } = useI18n();
  const v = k?.value, p = k?.prev;
  const ch = v != null && p != null && p !== 0 ? ((v - p) / Math.abs(p)) * 100 : null;
  const dir = ch == null || Math.abs(ch) < 0.5 ? "flat" : ch > 0 ? "up" : "down";
  const good = dir === "flat" ? "flat" : (dir === "up") === upGood ? "good" : "bad";
  return (
    <div className="opstat">
      <small>{label}</small>
      <b>{!k ? "…" : v == null ? "–" : (fmtV ?? ((n: number) => fmt(n)))(v)}</b>
      {extra ? <span className="opstat-extra">{extra}</span> : null}
      <div className="opstat-foot">
        <span className={"opsdelta " + good}>
          {!k ? "" : ch != null ? <>{dir === "up" ? "▲ +" : dir === "down" ? "▼ −" : "— "}{fmt(Math.abs(ch), Math.abs(ch) < 10 ? 1 : 0)} % <span className="muted">{period}</span></>
            : note ? <span className="muted">{note}</span> : p === 0 && v ? t("ops.k.new") : p == null ? "" : t("ops.k.nochange")}
        </span>
        <Trend vals={k?.series ?? []} />
      </div>
    </div>
  );
}

/** Very small markdown subset for runbook steps: numbered / bulleted lists, ### headings, ``` code blocks, `code`, **bold**, https links. */
function inline(s: string, key = ""): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(`[^`]+`|\*\*[^*]+\*\*|https?:\/\/[^\s)<>]+)/g;
  let last = 0, m: RegExpExecArray | null, i = 0;
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(s.slice(last, m.index));
    const x = m[0];
    if (x.startsWith("`")) out.push(<code key={key + i++}>{x.slice(1, -1)}</code>);
    else if (x.startsWith("**")) out.push(<b key={key + i++}>{x.slice(2, -2)}</b>);
    else { const u = x.replace(/[.,;:]+$/, ""); out.push(<a key={key + i++} href={u} target="_blank" rel="noreferrer noopener">{u}</a>); if (u.length < x.length) out.push(x.slice(u.length)); }
    last = m.index + x.length;
  }
  if (last < s.length) out.push(s.slice(last));
  return out;
}
export function RunbookMd({ md, steps }: { md?: string | null; steps?: string[] | null }) {
  if (steps?.length) return <ol className="opsmd-ol">{steps.map((s, i) => <li key={i}>{inline(s, i + ":")}</li>)}</ol>;
  if (!md) return null;
  const blocks: ReactNode[] = [];
  const lines = md.replace(/\r/g, "").split("\n");
  let list: { kind: "ol" | "ul"; items: string[] } | null = null;
  const flush = () => { if (list) { const L = list; blocks.push(L.kind === "ol" ? <ol key={blocks.length} className="opsmd-ol">{L.items.map((x, i) => <li key={i}>{inline(x, i + ":")}</li>)}</ol> : <ul key={blocks.length}>{L.items.map((x, i) => <li key={i}>{inline(x, i + ":")}</li>)}</ul>); list = null; } };
  for (let i = 0; i < lines.length; i++) {
    const ln = lines[i];
    if (/^\s*```/.test(ln)) {
      flush();
      const code: string[] = [];
      for (i++; i < lines.length && !/^\s*```/.test(lines[i]); i++) code.push(lines[i]);
      blocks.push(<pre key={blocks.length}><code>{code.join("\n")}</code></pre>);
      continue;
    }
    const ol = /^\s*\d+[.)]\s+(.*)$/.exec(ln), ul = /^\s*[-*]\s+(.*)$/.exec(ln), hd = /^\s*#{1,6}\s+(.*)$/.exec(ln);
    if (ol || ul) {
      const kind = ol ? "ol" : "ul";
      if (list && list.kind !== kind) flush();
      list ??= { kind, items: [] };
      list.items.push((ol ?? ul)![1]);
    } else if (/^\s{2,}\S/.test(ln) && list) {
      list.items[list.items.length - 1] += " " + ln.trim();
    } else if (!ln.trim()) {
      flush();
    } else {
      flush();
      blocks.push(hd ? <h6 key={blocks.length}>{inline(hd[1])}</h6> : <p key={blocks.length}>{inline(ln)}</p>);
    }
  }
  flush();
  return <div className="opsmd">{blocks}</div>;
}

/* ================= charts ================= */
interface Series { key: string; label: string; color: string; vals: number[] }
const shortDate = (d: string, locale: string) => new Date(d + (d.length === 10 ? "T00:00:00" : "")).toLocaleDateString(locale, { day: "numeric", month: "short" });

/** Multi-series line chart on one y-axis, rendered at the container's real width. Crosshair + tooltip on hover/touch. */
function LineChart({ dates, series, ariaLabel }: { dates: string[]; series: Series[]; ariaLabel: string }) {
  const { fmt, locale } = useI18n();
  const [ref, W] = useWidth<HTMLDivElement>();
  const [hi, setHi] = useState<number | null>(null);
  const H = 210, x0 = 44, x1 = Math.max(x0 + 60, W - 44), y0 = 12, y1 = H - 28;
  const n = dates.length;
  const mx = Math.max(1, ...series.flatMap((s) => s.vals));
  const ticks = niceTicks(0, mx, 4), top = ticks[ticks.length - 1];
  const X = (i: number) => x0 + (n <= 1 ? 0 : ((x1 - x0) * i) / (n - 1)), Y = (v: number) => y1 - ((y1 - y0) * v) / top;
  const last = n - 1;
  const ends = series.map((s) => Y(s.vals[last] ?? 0));
  const labelEnds = series.length <= 4 && ends.every((a, i) => ends.every((b, j) => i === j || Math.abs(a - b) >= 14));
  const nx = Math.max(2, Math.min(6, Math.floor((x1 - x0) / 70)));
  const xt = [...new Set(Array.from({ length: nx }, (_, k) => Math.round((k * last) / (nx - 1))))];
  const pick = (e: React.PointerEvent<SVGRectElement>) => {
    const b = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
    const i = Math.max(0, Math.min(last, Math.round(((e.clientX - b.left - x0) / (x1 - x0)) * last)));
    setHi(i);
    showTip(`${shortDate(dates[i], locale)} · ${series.map((s) => `${s.label} ${fmt(s.vals[i] ?? 0)}`).join(" · ")}`, e.clientX, e.clientY);
  };
  return (
    <div ref={ref} className="opschart">
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={ariaLabel}>
        {ticks.map((tk) => (
          <g key={tk}>
            <line x1={x0} x2={x1} y1={Y(tk)} y2={Y(tk)} stroke={cv("--line")} strokeWidth={1} />
            <text x={x0 - 8} y={Y(tk) + 4} fontSize={11} textAnchor="end" fill={cv("--faint")}>{fmt(tk)}</text>
          </g>
        ))}
        {xt.map((i) => <text key={i} x={X(i)} y={H - 8} fontSize={11} textAnchor={i === 0 ? "start" : i === last ? "end" : "middle"} fill={cv("--faint")}>{shortDate(dates[i], locale)}</text>)}
        {series.map((s) => (
          <polyline key={s.key} points={s.vals.map((v, i) => `${X(i)},${Y(v)}`).join(" ")} fill="none" stroke={cv(s.color)} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        ))}
        {hi != null && <line x1={X(hi)} x2={X(hi)} y1={y0} y2={y1} stroke={cv("--muted")} strokeWidth={1} />}
        {series.map((s) => {
          const i = hi ?? last;
          return <circle key={s.key} cx={X(i)} cy={Y(s.vals[i] ?? 0)} r={4} fill={cv(s.color)} stroke={cv("--surface")} strokeWidth={2} />;
        })}
        {labelEnds && hi == null && series.map((s, k) => (
          <text key={s.key} x={X(last) + 8} y={ends[k] + 4} fontSize={11} fontWeight={600} fill={cv("--muted")}>{s.label}</text>
        ))}
        <rect x={x0} y={y0} width={x1 - x0} height={y1 - y0} fill="transparent" style={{ touchAction: "pan-y" }}
          onPointerMove={pick} onPointerDown={pick} onPointerLeave={() => { setHi(null); hideTip(); }} />
      </svg>
    </div>
  );
}

/** Daily stacked columns (≤ 24 px, 4 px rounded top on the top segment, 2 px surface gap between segments); the tallest
 *  day is labelled, every day has a tooltip with the per-series values. */
function Columns({ dates, series, ariaLabel }: { dates: string[]; series: Series[]; ariaLabel: string }) {
  const { fmt, locale } = useI18n();
  const [ref, W] = useWidth<HTMLDivElement>();
  const n = Math.max(dates.length, 1);
  const tot = dates.map((_, i) => series.reduce((a, s) => a + (s.vals[i] ?? 0), 0));
  const H = 180, x0 = 36, x1 = W - 8, y0 = 16, y1 = H - 26;
  const mx = Math.max(1, ...tot), ticks = niceTicks(0, mx, 3), top = ticks[ticks.length - 1];
  const slot = (x1 - x0) / n, bw = Math.max(2, Math.min(24, slot - 2));
  const Y = (v: number) => y1 - ((y1 - y0) * v) / top;
  const imax = tot.indexOf(Math.max(...tot));
  const nx = Math.max(2, Math.min(6, Math.floor((x1 - x0) / 70)));
  const xt = [...new Set(Array.from({ length: nx }, (_, k) => Math.round((k * (n - 1)) / (nx - 1))))];
  return (
    <div ref={ref} className="opschart">
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={ariaLabel}>
        {ticks.map((tk) => (
          <g key={tk}>
            <line x1={x0} x2={x1} y1={Y(tk)} y2={Y(tk)} stroke={cv("--line")} strokeWidth={1} />
            <text x={x0 - 6} y={Y(tk) + 4} fontSize={11} textAnchor="end" fill={cv("--faint")}>{fmt(tk)}</text>
          </g>
        ))}
        {dates.map((dt, i) => {
          const x = x0 + i * slot + (slot - bw) / 2;
          let base = y1;
          const segs = series.map((s) => ({ s, v: s.vals[i] ?? 0 })).filter((z) => z.v > 0);
          return (
            <g key={dt}>
              {segs.map(({ s, v }, k) => {
                const h0 = y1 - Y(v), gap = k ? 2 : 0, h = Math.max(0, h0 - gap), yb = base - gap, last = k === segs.length - 1, r = last ? Math.min(4, bw / 2, h) : 0;
                base = yb - h;
                return <path key={s.key} d={`M${x} ${yb} V${yb - h + r} a${r} ${r} 0 0 1 ${r} ${-r} h${bw - 2 * r} a${r} ${r} 0 0 1 ${r} ${r} V${yb} Z`} fill={cv(s.color)} />;
              })}
              {i === imax && tot[i] > 0 && <text x={x + bw / 2} y={Y(tot[i]) - 5} fontSize={11} fontWeight={600} textAnchor="middle" fill={cv("--ink")}>{fmt(tot[i])}</text>}
              <rect x={x0 + i * slot} y={y0} width={slot} height={y1 - y0} fill="transparent"
                {...tip(`${shortDate(dt, locale)} · ${series.map((s) => `${s.label} ${fmt(s.vals[i] ?? 0)}`).join(" · ")}`)} />
            </g>
          );
        })}
        {xt.map((i) => <text key={i} x={x0 + i * slot + slot / 2} y={H - 8} fontSize={11} textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"} fill={cv("--faint")}>{dates[i] ? shortDate(dates[i], locale) : ""}</text>)}
      </svg>
    </div>
  );
}

/** Ranked list with a proportional bar (one colour — nominal categories are not a value ramp). */
function RankBars({ rows, head }: { rows: { name: ReactNode; v: number; sub?: ReactNode; tipText: string }[]; head: [string, string] }) {
  const { fmt } = useI18n();
  const mx = Math.max(1, ...rows.map((r) => r.v));
  return (
    <div className="opsrank" role="table">
      <div className="opsrank-h" role="row"><span role="columnheader">{head[0]}</span><span role="columnheader">{head[1]}</span></div>
      {rows.map((r, i) => (
        <div key={i} className="opsrank-r" role="row" {...tip(r.tipText)}>
          <span role="cell" className="opsrank-n">{r.name}{r.sub ? <small className="muted"> {r.sub}</small> : null}</span>
          <span role="cell" className="num">{fmt(r.v)}</span>
          <i aria-hidden="true" style={{ width: `${(r.v / mx) * 100}%` }} />
        </div>
      ))}
    </div>
  );
}

function Legend({ items }: { items: { label: string; color: string }[] }) {
  return <div className="legendrow">{items.map((x) => <span key={x.label}><i className="opskey" style={{ background: cv(x.color) }} />{x.label}</span>)}</div>;
}

/* ================= Overview ================= */
interface Kpi { value: number | null; prev?: number | null; series?: number[] }
const SLOW = 300000; // traffic / stats change slowly (logs parsed hourly)
const CHECK_TONE: Record<string, string> = { ok: "ok", warn: "warn", critical: "bad", info: "idle", unknown: "idle" };
const CHECK_ICON: Record<string, string> = { ok: "●", warn: "▲", critical: "✕", info: "●", unknown: "?" };

/** Week-over-week KPIs from /traffic?days=14 + /stats?days=14 (+ AI spend from /v1/admin/ai/health). */
function useKpis() {
  const tr = useAsync(() => opsApi.traffic(14), [], SLOW);
  const st = useAsync(() => opsApi.stats(14), [], SLOW);
  const ai = useAsync(() => aiApi.health(), [], 60000);
  return useMemo(() => {
    const out: Record<string, Kpi & { sub?: string | number | null }> = {};
    const t = tr.data;
    if (t) {
      const days = [...new Set(t.daily.map((d) => d.date))].sort().slice(-14);
      const per = (f: (d: OpsTrafficDay) => number) => days.map((dd) => t.daily.filter((d) => d.date === dd).reduce((a, d) => a + f(d), 0));
      const wk = (v: number[]) => ({ value: v.slice(-7).reduce((a, x) => a + x, 0), prev: v.length >= 14 ? v.slice(0, 7).reduce((a, x) => a + x, 0) : null, series: v });
      out.visitors = wk(per((d) => d.visitors));
      out.views = wk(per((d) => d.page_views));
    }
    const s = st.data;
    if (s) {
      const reg = s.registrations_daily.map((d) => d.accounts);
      let acc = s.accounts.total - reg.reduce((a, x) => a + x, 0);
      out.users = { value: s.accounts.total, prev: s.accounts.total - s.accounts.new_7d, series: reg.map((x) => (acc += x)), sub: s.accounts.new_7d };
      out.wallets = { value: s.wallets.linked_total, prev: null, sub: s.wallets.signed_in_7d };
      out.active = { value: s.active_users.d7, prev: null };
      out.vals = { value: s.valuations.finished_7d, prev: s.days >= 14 ? s.valuations.finished_period - s.valuations.finished_7d : null, sub: s.valuations.started_7d };
      out.hr = { value: s.hr.teams_7d, prev: s.days >= 14 ? s.hr.teams_period - s.hr.teams_7d : null };
    }
    const a = ai.data;
    if (a) {
      const spend = a.providers.reduce((x, p) => x + (p.spend_today_usd ?? 0), 0), budget = a.providers.reduce((x, p) => x + (p.budget_today_usd ?? 0), 0);
      out.ai = { value: spend, prev: null, sub: budget || null };
    }
    return { k: out, error: tr.error || st.error, loaded: !!(t && s) };
  }, [tr.data, st.data, ai.data, tr.error, st.error]);
}

function Overview({ go }: { go: (tab: Tab, id?: string | number) => void }) {
  const { t, fmt, ago, date } = useI18n();
  const sum = useAsync(() => opsApi.summary(), [], REFRESH);
  const inc = useAsync(() => opsApi.incidents("active"), [], REFRESH);
  const { k: K, error: kErr } = useKpis();
  const now = useNow(1000);
  const [got, setGot] = useState(Date.now());
  const [allChecks, setAllChecks] = useState(false);
  useEffect(() => { if (sum.data) setGot(Date.now()); }, [sum.data]);
  const d = sum.data;
  if (!d) return sum.error ? <ErrorBox error={sum.error} retry={sum.reload} /> : <p className="note">{t("common.loading")}</p>;
  const oc = d.open_incidents.critical, ow = d.open_incidents.warn, oi = d.open_incidents.info;
  const tone: Tone = oc ? "bad" : ow ? "wait" : "ok";
  const wk = t("ops.k.vsweek");
  const active = [...(inc.data ?? [])].sort((a, b) => sevRank(a.severity) - sevRank(b.severity) || Date.parse(b.opened_at) - Date.parse(a.opened_at));
  const acked = active.filter((x) => x.status === "acknowledged").length;
  const failing = d.checks.filter((c) => c.status === "warn" || c.status === "critical").length;
  const checks = [...d.checks].sort((a, b) => checkRank(a.status) - checkRank(b.status));
  const shownChecks = allChecks ? checks : checks.filter((c) => c.status !== "ok");
  const stale = d.last_check_at ? now - Date.parse(d.last_check_at) > 5 * 60000 : true;
  return (
    <div className="ops-sec">
      <StatusBar tone={tone} status={oc + ow + oi ? t("ops.sb.open", { c: oc, w: ow }) : t("ops.sb.ok")}
        meta={t("ops.sb.meta", { s: Math.max(0, Math.round((now - got) / 1000)) })}
        next={oc + ow ? { label: t("ops.sb.see"), onClick: () => go("incidents") } : null} />
      {sum.error ? <p className="banner warn" role="alert">{t("ops.err.stale")}</p> : null}
      {!d.enabled ? <p className="banner warn" role="alert">{t("ops.s.disabled")}</p> : null}
      <div className="opsstrip">
        <div className={"opscell " + (oc ? "bad" : ow ? "warn" : "ok")}>
          <small>{t("ops.s.open")}</small>
          <div className="opscell-row">
            <span className="opscount bad"><i aria-hidden="true">{SEV_ICON.critical}</i><b className="num">{fmt(oc)}</b> {t("ops.sev.critical")}</span>
            <span className="opscount warn"><i aria-hidden="true">{SEV_ICON.warn}</i><b className="num">{fmt(ow)}</b> {t("ops.sev.warn")}</span>
            <span className="opscount idle"><i aria-hidden="true">{SEV_ICON.info}</i><b className="num">{fmt(oi)}</b> {t("ops.sev.info")}</span>
          </div>
          {acked ? <span className="muted">{t("ops.s.acked", { n: acked })}</span> : null}
        </div>
        <div className={"opscell " + (stale ? "warn" : failing ? "" : "ok")}>
          <small>{t("ops.s.check")}</small>
          <b className={stale ? "warn" : ""}>{d.last_check_at ? (stale ? "▲ " : "") + ago(d.last_check_at) : t("ops.s.never")}</b>
          <span className="muted">{t("ops.s.checks", { n: d.checks.length, f: failing })}{d.errors_24h ? <> · <button type="button" className="linkbtn" onClick={() => go("errors")}>{t("ops.s.errors", { n: fmt(d.errors_24h) })}</button></> : null}</span>
        </div>
        <EmailCell e={d.email} last={d.last_report} />
      </div>

      {kErr ? <p className="banner warn" role="alert">{t("ops.err.kpi")}</p> : null}
      <div className="opsstats">
        <Stat label={t("ops.k.visitors")} k={K.visitors} period={wk} />
        <Stat label={t("ops.k.views")} k={K.views} period={wk} />
        <Stat label={t("ops.k.users")} k={K.users} period={wk} extra={K.users?.sub != null ? t("ops.k.new7", { n: fmt(Number(K.users.sub)) }) : null} />
        <Stat label={t("ops.k.active")} k={K.active} period={wk} note={K.wallets ? t("ops.k.wallets", { n: fmt(K.wallets.value ?? 0) }) : null} />
        <Stat label={t("ops.k.vals")} k={K.vals} period={wk} extra={K.vals?.sub != null ? t("ops.k.started", { n: fmt(Number(K.vals.sub)) }) : null} />
        <Stat label={t("ops.k.hr")} k={K.hr} period={wk} />
        <Stat label={t("ops.k.ai")} k={K.ai} period="" fmtV={(n) => "US$" + fmt(n, n < 100 ? 2 : 0)} note={K.ai ? (K.ai.sub ? t("ops.k.budget", { b: "US$" + fmt(Number(K.ai.sub), 2) }) : t("ops.k.nobudget")) : null} />
      </div>

      <div className="pane">
        <div className="phead"><h4>{t("ops.o.open")}</h4><button type="button" className="linkbtn" onClick={() => go("incidents")}>{t("ops.o.all")}</button></div>
        {!active.length ? <p className="note">{inc.data ? t("ops.o.none") : t("common.loading")}</p> : (
          <div className="opsinc">
            {active.slice(0, 5).map((x) => <IncRow key={x.id} x={x} onOpen={() => go("incidents", x.id)} />)}
          </div>
        )}
      </div>

      <div className="pane">
        <div className="phead">
          <h4>{t("ops.c.h")} <span className="muted num">· {t("ops.c.n", { ok: d.checks.filter((c) => c.status === "ok").length, n: d.checks.length })}</span></h4>
          <button type="button" className="linkbtn" aria-pressed={allChecks} onClick={() => setAllChecks(!allChecks)}>{allChecks ? t("ops.c.problems") : t("ops.c.all")}</button>
        </div>
        {!shownChecks.length ? <p className="note">{t("ops.c.allok")}</p> : (
          <div className="opschecks">
            {shownChecks.map((c) => (
              <div key={c.id} className="opscheck">
                <span className={"opspill " + (CHECK_TONE[c.status] ?? "idle")}><i aria-hidden="true">{CHECK_ICON[c.status] ?? "?"}</i>{t(("ops.cs." + (CHECK_TONE[c.status] ? c.status : "unknown")) as DictKey)}</span>
                <span className="opscheck-t"><b>{c.title}</b><small className="muted">{c.detail}</small></span>
                <span className="opscheck-m">
                  {c.incident_id != null ? <button type="button" className="linkbtn" onClick={() => go("incidents", c.incident_id!)}>{t("ops.c.inc")}</button>
                    : c.runbook_url ? <a className="opslink" href={c.runbook_url} target="_blank" rel="noreferrer noopener">{t("ops.d.runbook")} ↗</a> : null}
                  <small className="muted mono" title={c.last_run_at ? date(c.last_run_at, true) : ""}>{c.id}</small>
                </span>
              </div>
            ))}
          </div>
        )}
        <p className="note">{t("ops.o.gen", { t: date(d.generated_at, true) })}{d.leader === false ? " · " + t("ops.c.follower") : ""}</p>
      </div>
    </div>
  );
}
const sevRank = (s: string) => (s === "critical" ? 0 : s === "warn" ? 1 : 2);
const checkRank = (s: string) => (s === "critical" ? 0 : s === "warn" ? 1 : s === "unknown" ? 2 : s === "info" ? 3 : 4);

function EmailCell({ e, last }: { e: OpsSummary["email"]; last: OpsSummary["last_report"] }) {
  const { t, fmt, ago } = useI18n();
  const url = RUNBOOK + "#email-delivery";
  if (!e.configured) return (
    <div className="opscell warn" role="alert">
      <small>{t("ops.s.mail")}</small>
      <b className="warn">▲ {t("ops.s.nosmtp")}</b>
      <span className="muted">{t("ops.s.nosmtp.d", { n: e.pending ?? 0 })} <a href={url} target="_blank" rel="noreferrer noopener">{t("ops.s.runbook")}</a></span>
    </div>
  );
  const lastFailed = !!last && !last.emailed && !!last.email_reason && last.email_reason !== "pending";
  const bad = lastFailed || (e.pending ?? 0) > 0;
  return (
    <div className={"opscell " + (bad ? "warn" : "ok")}>
      <small>{t("ops.s.mail")}</small>
      <b>{"● " + t("ops.s.mailok", { to: e.to ?? "admin" })}</b>
      <span className="muted">
        {(e.pending ?? 0) > 0 ? <span className="warn">{t("ops.s.unsent", { n: fmt(e.pending ?? 0) })} · </span> : null}
        {last ? t(last.emailed ? "ops.s.lastrep" : "ops.s.lastrep.no", { t: ago(last.created_at) }) : t("ops.s.norep")}
        {lastFailed ? <> · <span title={last!.email_reason ?? ""}>{(last!.email_reason ?? "").slice(0, 80)}</span> <a href={url} target="_blank" rel="noreferrer noopener">{t("ops.s.runbook")}</a></> : null}
      </span>
    </div>
  );
}

/* ================= Incidents ================= */
function IncRow({ x, onOpen, current }: { x: OpsIncident; onOpen: () => void; current?: boolean }) {
  const { t, fmt, ago, date } = useI18n();
  return (
    <button type="button" className={"opsinc-r s-" + x.severity + (x.status === "resolved" ? " done" : "")} aria-current={current || undefined} onClick={onOpen}>
      <span className="opsinc-sev"><SevPill s={x.severity} /></span>
      <span className="opsinc-t"><b>{x.title}</b><small className="mono muted">{x.check_id}</small></span>
      <span className="opsinc-st"><StPill s={x.status} /></span>
      <span className="opsinc-m" title={date(x.opened_at, true)}><small>{t("ops.i.since")}</small>{ago(x.opened_at)}</span>
      <span className="opsinc-m" title={x.last_seen_at ? date(x.last_seen_at, true) : ""}><small>{t("ops.i.seen")}</small>{x.last_seen_at ? ago(x.last_seen_at) : "–"}</span>
      <span className="opsinc-m num"><small>{t("ops.i.count")}</small>{fmt(x.count)}×</span>
    </button>
  );
}

function Incidents() {
  const { t } = useI18n();
  const [sp, setSp] = useSearchParams();
  const sel = sp.get("id");
  const [filter, setFilter] = useState<"open" | "all" | "resolved">("open");
  const list = useAsync(() => opsApi.incidents("all"), [], REFRESH);
  const now = useNow(1000);
  const [got, setGot] = useState(Date.now());
  useEffect(() => { if (list.data) setGot(Date.now()); }, [list.data]);
  const all = list.data ?? [];
  const rows = all.filter((x) => filter === "all" || (filter === "open" ? x.status !== "resolved" : x.status === "resolved"))
    .sort((a, b) => (a.status === "resolved" ? 1 : 0) - (b.status === "resolved" ? 1 : 0) || sevRank(a.severity) - sevRank(b.severity) || Date.parse(b.opened_at) - Date.parse(a.opened_at));
  const nOpen = all.filter((x) => x.status !== "resolved").length;
  const setSel = (id: string | number | null) => { const n = new URLSearchParams(sp); if (id == null) n.delete("id"); else n.set("id", String(id)); setSp(n, { replace: id == null }); };
  if (!list.data) return list.error ? <ErrorBox error={list.error} retry={list.reload} /> : <p className="note">{t("common.loading")}</p>;
  return (
    <div className="ops-sec">
      <div className="opsbar">
        <Ranges label={t("ops.i.filter")} value={filter} onChange={setFilter} opts={[[t("ops.i.f.open", { n: nOpen }), "open"], [t("ops.i.f.resolved"), "resolved"], [t("ops.i.f.all"), "all"]]} />
        <span className="muted opsupd">{t("ops.sb.meta", { s: Math.max(0, Math.round((now - got) / 1000)) })}</span>
      </div>
      {list.error ? <p className="banner warn" role="alert">{t("ops.err.stale")}</p> : null}
      {!rows.length ? <div className="pane"><p className="note">{filter === "open" ? t("ops.o.none") : t("ops.i.empty")}</p></div> : (
        <div className="pane opsinc">
          <div className="opsinc-h" aria-hidden="true"><span>{t("ops.i.sev")}</span><span>{t("ops.i.title")}</span><span>{t("ops.i.status")}</span><span>{t("ops.i.since")}</span><span>{t("ops.i.seen")}</span><span>{t("ops.i.count")}</span></div>
          {rows.map((x) => <IncRow key={x.id} x={x} current={String(x.id) === sel} onOpen={() => setSel(x.id)} />)}
        </div>
      )}
      {sel && <IncidentDrawer id={sel} onClose={() => setSel(null)} onChanged={() => void list.reload()} />}
    </div>
  );
}

function IncidentDrawer({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const { t, fmt, date, ago } = useI18n();
  const tx = useTx();
  const { me } = useAuth();
  const can = me?.role === "admin" && !me?.must_change;
  const d = useAsync(() => opsApi.incident(id), [id], REFRESH);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [toast, setToast] = useToast();
  const [note, setNote] = useState("");
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", k);
    const ov = document.body.style.overflow; document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", k); document.body.style.overflow = ov; prev?.focus?.(); };
  }, [onClose]);
  const act = async (fn: () => Promise<unknown>, msg: string) => {
    setBusy(true); setErr("");
    try { await fn(); setToast(msg); setNote(""); await d.reload(); onChanged(); } catch (e) { setErr(errText(e, t)); } finally { setBusy(false); }
  };
  const x = d.data;
  // "seen" events repeat every check round; the count is shown above instead
  const tl = (x?.timeline ?? []).filter((e) => e.kind !== "seen").sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  return (
    <div className="opsdrawer-wrap">
      <div className="opsdrawer-bg" onClick={onClose} aria-hidden="true" />
      <div className="opsdrawer" role="dialog" aria-modal="true" aria-labelledby="opsdrawer-h" ref={panel} tabIndex={-1}>
        <header>
          <div>
            {x && <div className="opsdrawer-pills"><SevPill s={x.severity} /><StPill s={x.status} /></div>}
            <h3 id="opsdrawer-h">{x?.title ?? t("common.loading")}</h3>
            {x && <small className="mono muted">{x.check_id}{x.fingerprint ? " · " + x.fingerprint : ""}</small>}
          </div>
          <button type="button" className="btn ghost sm" onClick={onClose} aria-label={t("ops.d.close")}>✕</button>
        </header>
        {!x ? (d.error ? <ErrorBox error={d.error} retry={d.reload} /> : <p className="note">{t("common.loading")}</p>) : (
          <div className="opsdrawer-body">
            {toast && <p className="banner ok" role="status">{toast}</p>}
            {x.summary && <p className="opsdrawer-sum">{x.summary}</p>}
            {x.impact && <div className="opsimpact"><small>{t("ops.d.impact")}</small><p>{x.impact}</p></div>}
            <dl className="opsfacts">
              <div><dt>{t("ops.i.since")}</dt><dd>{date(x.opened_at, true)} <span className="muted">({ago(x.opened_at)})</span></dd></div>
              <div><dt>{t("ops.i.seen")}</dt><dd>{x.last_seen_at ? ago(x.last_seen_at) : "–"}</dd></div>
              <div><dt>{t("ops.i.count")}</dt><dd className="num">{fmt(x.count)}×</dd></div>
              {x.acked_at && <div><dt>{t("ops.st.acknowledged")}</dt><dd>{ago(x.acked_at)}{x.acked_by ? " · " + x.acked_by : ""}</dd></div>}
              {x.resolved_at && <div><dt>{t("ops.st.resolved")}</dt><dd>{ago(x.resolved_at)}{x.resolved_by ? " · " + (x.resolved_by === "auto" ? t("ops.d.auto") : x.resolved_by) : ""}</dd></div>}
            </dl>

            {x.status !== "resolved" && can && (
              <div className="opsactions">
                {x.status === "open" && <button type="button" className="btn ghost sm" disabled={busy} onClick={() => act(() => opsApi.ack(x.id), t("ops.d.acked"))}>{t("ops.d.ack")}</button>}
                <label className="sr-only" htmlFor="opsnote">{t("ops.d.note")}</label>
                <input id="opsnote" className="opsnote" value={note} maxLength={300} placeholder={t("ops.d.note")} onChange={(e) => setNote(e.target.value)} disabled={busy} />
                <button type="button" className="btn sm" disabled={busy} onClick={() => act(() => opsApi.resolve(x.id, note.trim()), t("ops.d.resolved"))}>{t("ops.d.resolve")}</button>
                <p className="note">{t("ops.d.resolve.h")}</p>
              </div>
            )}
            {err && <p className="banner bad" role="alert">{err}</p>}

            <section>
              <div className="phead"><h4>{t("ops.d.fix")}</h4>{(x.runbook_url || x.runbook_id) && <a className="opslink" href={x.runbook_url || `${RUNBOOK}#${x.runbook_id}`} target="_blank" rel="noreferrer noopener">{t("ops.d.runbook")} ↗</a>}</div>
              {x.runbook_steps?.length ? <RunbookMd steps={x.runbook_steps} /> : <p className="note">{t("ops.d.nofix")}</p>}
            </section>

            {x.details && Object.keys(x.details).length > 0 && (
              <section>
                <h4>{t("ops.d.details")}</h4>
                <dl className="opsfacts">{Object.entries(x.details).map(([k, v]) => <div key={k}><dt className="mono">{k}</dt><dd>{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd></div>)}</dl>
              </section>
            )}

            <section>
              <h4>{t("ops.d.timeline")}</h4>
              {!tl.length ? <p className="note">–</p> : (
                <ol className="opstl">
                  {tl.map((e, i) => (
                    <li key={i} className={"k-" + e.kind}>
                      <i aria-hidden="true" />
                      <div><b>{tx("ops.tl." + e.kind, e.kind)}</b>{e.by ? <span className="muted"> · {e.by === "auto" ? t("ops.d.auto") : e.by}</span> : null}{e.text ? <p>{e.text}</p> : null}</div>
                      <time dateTime={e.at} title={date(e.at, true)}>{ago(e.at)}</time>
                    </li>
                  ))}
                </ol>
              )}
            </section>

            <section>
              <h4>{t("ops.d.emails")}</h4>
              <EmailLog rows={x.emails ?? []} />
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

function EmailLog({ rows }: { rows: OpsEmailLog[] }) {
  const { t, ago, date } = useI18n();
  const tx = useTx();
  if (!rows.length) return <p className="note">{t("ops.d.noemail")}</p>;
  return (
    <div className="opsmail">
      {rows.map((e, i) => (
        <div key={i}>
          <MailPill s={e.status} />
          <span><b>{tx("ops.mk." + e.kind, e.kind)}</b>{e.to ? <span className="muted"> → {e.to}</span> : null}{e.error ? <small className="bad">{e.error}</small> : null}</span>
          <time dateTime={e.at} title={date(e.at, true)}>{ago(e.at)}</time>
        </div>
      ))}
    </div>
  );
}

/* ================= Traffic & users ================= */
const METHOD_ORDER = ["google", "wallet", "guest", "demo", "password"];
function Traffic() {
  const { t, fmt, locale } = useI18n();
  const tx = useTx();
  const [days, setDays] = useState(30);
  const [table, setTable] = useState(false);
  const tr = useAsync(() => opsApi.traffic(days), [days]);
  const st = useAsync(() => opsApi.stats(days), [days]);
  const hostLabel = (h: string) => h.split(".")[0];
  const model = useMemo(() => {
    const d = tr.data;
    if (!d) return null;
    const dates = [...new Set(d.daily.map((x) => x.date))].sort();
    const at = new Map<string, OpsTrafficDay>(d.daily.map((x) => [x.date + "|" + x.host, x]));
    const ser = (f: (x: OpsTrafficDay) => number): Series[] => d.hosts.map((h, i) => ({ key: h, label: hostLabel(h), color: HOST_C[i] ?? "--c6", vals: dates.map((dt) => { const x = at.get(dt + "|" + h); return x ? f(x) : 0; }) }));
    return { hosts: d.hosts, dates, visitors: ser((x) => x.visitors), views: ser((x) => x.page_views) };
  }, [tr.data]);
  const s = st.data;
  const legend = model ? model.hosts.map((h, i) => ({ label: h, color: HOST_C[i] ?? "--c6" })) : [];
  const total = (x: Series[]) => x.reduce((a, y) => a + y.vals.reduce((b, v) => b + v, 0), 0);
  return (
    <div className="ops-sec">
      <div className="opsbar">
        <Ranges label={t("ops.t.range")} value={days} onChange={setDays} opts={[[t("ops.t.d", { n: 7 }), 7], [t("ops.t.d", { n: 30 }), 30], [t("ops.t.d", { n: 90 }), 90]]} />
        {tr.data?.updated_at ? <span className="muted opsupd">{t("ops.t.parsed", { t: new Date(tr.data.updated_at).toLocaleString(locale, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) })}</span> : null}
      </div>
      {tr.error ? <ErrorBox error={tr.error} retry={tr.reload} /> : !model || !tr.data ? <p className="note">{t("common.loading")}</p> : (
        <div className="pane">
          <div className="phead">
            <h4>{t("ops.t.traffic", { n: days })}</h4>
            {model.dates.length ? <button type="button" className="linkbtn" onClick={() => setTable(!table)} aria-pressed={table}>{table ? t("ops.t.chart") : t("ops.t.table")}</button> : null}
          </div>
          {!tr.data.available ? <p className="banner warn" role="status">{t("ops.t.unavail")}</p> : null}
          {!model.dates.length ? <p className="note">{t("ops.t.empty")}</p> : (
            <>
              {model.hosts.length > 1 ? <Legend items={legend} /> : null}
              {table ? (
                <div className="tbl opstblscroll"><table>
                  <thead><tr><th>{t("ops.t.date")}</th>{model.hosts.map((h) => <Fragment key={h}><th className="r">{hostLabel(h)} · {t("ops.t.vis")}</th><th className="r">{hostLabel(h)} · {t("ops.t.pvs")}</th></Fragment>)}</tr></thead>
                  <tbody>{model.dates.map((_, i) => i).reverse().map((i) => (
                    <tr key={model.dates[i]}><td>{shortDate(model.dates[i], locale)}</td>{model.hosts.map((h, k) => <Fragment key={h}><td className="r num">{fmt(model.visitors[k].vals[i])}</td><td className="r num">{fmt(model.views[k].vals[i])}</td></Fragment>)}</tr>
                  ))}</tbody>
                </table></div>
              ) : (
                <div className="opscharts2">
                  <figure>
                    <figcaption>{t("ops.t.visitors")} <span className="muted num">· {fmt(total(model.visitors))}</span></figcaption>
                    <LineChart dates={model.dates} series={model.visitors} ariaLabel={t("ops.t.visitors")} />
                  </figure>
                  <figure>
                    <figcaption>{t("ops.t.views")} <span className="muted num">· {fmt(total(model.views))}</span></figcaption>
                    <LineChart dates={model.dates} series={model.views} ariaLabel={t("ops.t.views")} />
                  </figure>
                </div>
              )}
            </>
          )}
          <p className="note">{t("ops.t.note")}{tr.data.bots_filtered ? " " + t("ops.t.bots", { n: fmt(tr.data.bots_filtered) }) : ""}</p>
        </div>
      )}

      {st.error ? <ErrorBox error={st.error} retry={st.reload} /> : !s ? <p className="note">{t("common.loading")}</p> : (
        <>
          <div className="opsstats four">
            <div className="opstat"><small>{t("ops.u.accounts")}</small><b>{fmt(s.accounts.total)}</b><span className="opstat-extra">{t("ops.u.newn", { n: fmt(s.accounts.new_period), d: s.days })}</span></div>
            <div className="opstat"><small>{t("ops.u.wallets")}</small><b>{fmt(s.wallets.linked_total)}</b><span className="opstat-extra">{t("ops.u.signedin", { n: fmt(s.wallets.signed_in_period), d: s.days })}</span></div>
            <div className="opstat"><small>{t("ops.u.a7")}</small><b>{fmt(s.active_users.d7)}</b>{s.active_users.d1 != null ? <span className="opstat-extra">{t("ops.u.today", { n: fmt(s.active_users.d1) })}</span> : null}</div>
            <div className="opstat"><small>{t("ops.u.a30")}</small><b>{fmt(s.active_users.d30)}</b></div>
          </div>
          <div className="opsgrid2">
            <div className="pane">
              <h4>{t("ops.u.reg")} <span className="muted num">· {fmt(s.registrations_daily.reduce((a, x) => a + x.accounts + x.wallets, 0))}</span></h4>
              <Legend items={[{ label: t("ops.u.reg.acc"), color: "--c1" }, { label: t("ops.u.reg.wal"), color: "--c3" }]} />
              {s.registrations_daily.length ? <Columns dates={s.registrations_daily.map((x) => x.day)} ariaLabel={t("ops.u.reg")}
                series={[{ key: "a", label: t("ops.u.reg.acc"), color: "--c1", vals: s.registrations_daily.map((x) => x.accounts) }, { key: "w", label: t("ops.u.reg.wal"), color: "--c3", vals: s.registrations_daily.map((x) => x.wallets) }]} /> : <p className="note">{t("ops.none")}</p>}
            </div>
            <div className="pane">
              <h4>{t("ops.u.signins", { n: s.days })}</h4>
              {Object.values(s.sign_ins.period).some((v) => v > 0) ? (
                <RankBars head={[t("ops.u.method"), t("ops.u.count")]} rows={Object.entries(s.sign_ins.period).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1] || METHOD_ORDER.indexOf(a[0]) - METHOD_ORDER.indexOf(b[0]))
                  .map(([m, v]) => ({ name: tx("ops.m." + m, m), sub: t("ops.u.in7", { n: fmt(s.sign_ins["7d"][m] ?? 0) }), v, tipText: `${tx("ops.m." + m, m)} · ${fmt(v)}` }))} />
              ) : <p className="note">{t("ops.none")}</p>}
            </div>
          </div>
          <ProductTable s={s} />
        </>
      )}

      {tr.data && (tr.data.top_pages.length || tr.data.referrers.length || tr.data.countries.length) ? (
        <div className="opsgrid3">
          <div className="pane">
            <h4>{t("ops.t.pages")}</h4>
            {tr.data.top_pages.length ? <RankBars head={[t("ops.t.page"), t("ops.t.pvs")]} rows={tr.data.top_pages.slice(0, 10).map((p) => ({ name: <span className="mono">{p.path}</span>, sub: model && model.hosts.length > 1 ? hostLabel(p.host) : undefined, v: p.views, tipText: `${p.host}${p.path} · ${fmt(p.views)}` }))} /> : <p className="note">{t("ops.none")}</p>}
          </div>
          <div className="pane">
            <h4>{t("ops.t.refs")}</h4>
            {tr.data.referrers.length ? <RankBars head={[t("ops.t.ref"), t("ops.t.visits")]} rows={tr.data.referrers.slice(0, 10).map((r) => ({ name: r.referrer, v: r.views, tipText: `${r.referrer} · ${fmt(r.views)}` }))} /> : <p className="note">{t("ops.none")}</p>}
          </div>
          {tr.data.countries.length ? (
            <div className="pane">
              <h4>{t("ops.t.countries")}</h4>
              <RankBars head={[t("ops.t.country"), t("ops.t.visits")]} rows={tr.data.countries.slice(0, 10).map((c) => ({ name: countryName(c.country, locale), sub: c.country, v: c.views, tipText: `${countryName(c.country, locale)} · ${fmt(c.views)}` }))} />
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function ProductTable({ s }: { s: OpsStats }) {
  const { t, fmt } = useI18n();
  const rows: [string, number | null, number | null, number | null][] = [
    ["valuations_started", s.valuations.started_7d, s.valuations.started_period, null],
    ["valuations_finished", s.valuations.finished_7d, s.valuations.finished_period, null],
    ["valuations_failed", s.valuations.failed_7d, s.valuations.failed_period, null],
    ["hr_reports", s.hr.teams_7d, s.hr.teams_period, null],
    ["companies", s.companies.created_7d, null, s.companies.total],
    ["offerings", s.offerings.created_7d, null, s.offerings.total],
    ["dividends", s.dividends.created_7d, null, s.dividends.total],
  ];
  const c = (v: number | null) => (v == null ? "–" : fmt(v));
  return (
    <div className="pane">
      <h4>{t("ops.p.h")}</h4>
      <div className="tbl"><table>
        <thead><tr><th>{t("ops.p.what")}</th><th className="r">{t("ops.p.week")}</th><th className="r">{t("ops.t.d", { n: s.days })}</th><th className="r">{t("ops.p.total")}</th></tr></thead>
        <tbody>{rows.map(([k, w, p, all]) => <tr key={k}><td>{t(("ops.p." + k) as DictKey)}</td><td className="r num"><b>{c(w)}</b></td><td className="r num">{c(p)}</td><td className="r num">{c(all)}</td></tr>)}</tbody>
      </table></div>
      <p className="note">{t("ops.p.note", { r: fmt(s.valuations.running), a: fmt(s.admin_actions_7d ?? 0) })}</p>
    </div>
  );
}
function countryName(code: string, locale: string) {
  try { return new Intl.DisplayNames([locale], { type: "region" }).of(code.toUpperCase()) ?? code; } catch { return code; }
}

/* ================= Errors ================= */
function Errors() {
  const { t, fmt, ago, date } = useI18n();
  const { me } = useAuth();
  const admin = me?.role === "admin";
  const [days, setDays] = useState(7);
  const [open, setOpen] = useState<string | null>(null);
  const [copied, setCopied] = useState("");
  const e = useAsync(() => opsApi.errors(days), [days], 60000);
  const rows = [...(e.data?.rows ?? [])].sort((a, b) => Date.parse(b.last_seen) - Date.parse(a.last_seen));
  const copy = async (x: OpsError) => { try { await navigator.clipboard.writeText(`${x.message}\n${x.method ?? ""} ${x.route ?? ""}\n\n${x.stack ?? ""}`); setCopied(x.fingerprint); setTimeout(() => setCopied(""), 2000); } catch { /* clipboard blocked */ } };
  return (
    <div className="ops-sec">
      <div className="opsbar">
        <Ranges label={t("ops.t.range")} value={days} onChange={setDays} opts={[[t("ops.e.24h"), 1], [t("ops.t.d", { n: 7 }), 7], [t("ops.t.d", { n: 30 }), 30]]} />
        {e.data ? <span className="muted opsupd">{t("ops.e.n", { n: e.data.total, c: fmt(rows.reduce((a, x) => a + x.count, 0)) })}</span> : null}
      </div>
      {e.error ? <ErrorBox error={e.error} retry={e.reload} /> : !e.data ? <p className="note">{t("common.loading")}</p> : !rows.length ? <div className="pane"><p className="note">{t("ops.e.none")}</p></div> : (
        <div className="pane opserrs">
          {rows.map((x) => {
            const isOpen = open === x.fingerprint;
            return (
              <div key={x.fingerprint} className={"opserr" + (isOpen ? " open" : "")}>
                <button type="button" className="opserr-h" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : x.fingerprint)}>
                  <span className="opserr-c num" title={t("ops.i.count")}>{fmt(x.count)}×</span>
                  <span className="opserr-m">
                    <b>{x.message.length > 160 ? x.message.slice(0, 160) + "…" : x.message}</b>
                    <small className="muted">
                      {x.route ? <span className="mono">{x.method ? x.method + " " : ""}{x.route}</span> : null}
                      {x.service ? <>{x.route ? " · " : ""}{x.service}</> : null}{x.logger ? <> · <span className="mono">{x.logger}</span></> : null}
                    </small>
                    <small className="muted"><span title={date(x.first_seen, true)}>{t("ops.e.first", { t: ago(x.first_seen) })}</span> · <span title={date(x.last_seen, true)}>{t("ops.e.last", { t: ago(x.last_seen) })}</span> · <span className="mono">{x.fingerprint}</span></small>
                  </span>
                  <span className="opserr-x" aria-hidden="true">{isOpen ? "−" : "+"}</span>
                </button>
                {isOpen && (
                  <div className="opserr-b">
                    {x.message.length > 160 && <p className="opserr-full">{x.message}</p>}
                    {x.request_id && <p className="note">{t("ops.e.req")} <span className="mono">{x.request_id}</span></p>}
                    {!admin ? <p className="note">{t("ops.e.adminonly")}</p> : x.stack ? (
                      <>
                        <div className="phead"><small className="muted">{t("ops.e.stack")}</small><button type="button" className="linkbtn" onClick={() => void copy(x)}>{copied === x.fingerprint ? t("ops.e.copied") : t("ops.e.copy")}</button></div>
                        <pre className="opsstack"><code>{x.stack}</code></pre>
                      </>
                    ) : <p className="note">{t("ops.e.nostack")}</p>}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      <p className="note">{t("ops.e.keep")}</p>
    </div>
  );
}

/* ================= Weekly reports ================= */
function Reports() {
  const { t, date, ago } = useI18n();
  const tx = useTx();
  const { me } = useAuth();
  const can = me?.role === "admin" && !me?.must_change;
  const list = useAsync(() => opsApi.reports(), []);
  const [sel, setSel] = useState<string | number | null>(null);
  const cur = sel ?? list.data?.[0]?.id ?? null;
  const rep = useAsync(() => (cur == null ? Promise.resolve(null) : opsApi.report(cur)), [cur]);
  const [busy, setBusy] = useState<"" | "send" | "test">("");
  const [res, setRes] = useState<{ tone: "ok" | "warn" | "bad"; text: string; link?: boolean } | null>(null);
  const show = (r: OpsSendResult, okMsg: string, test = false) => {
    const nc = r.status === "not_configured" || /smtp not configured/i.test(r.error ?? "");
    setRes(r.sent ? { tone: "ok", text: okMsg } : nc ? { tone: "warn", text: t(test ? "ops.r.test.nosmtp" : "ops.r.nosmtp"), link: true } : { tone: "bad", text: t("ops.r.fail", { e: r.error ?? "?" }) });
  };
  const go = async (k: "send" | "test") => {
    setBusy(k); setRes(null);
    try {
      if (k === "send") { const r = await opsApi.sendNow(); show(r, t("ops.r.sent", { to: r.to ?? "admin@blockid.au" })); await list.reload(); if (r.id != null) setSel(r.id); }
      else { const r = await opsApi.testEmail(); show(r, t("ops.r.tested", { to: r.to ?? "admin@blockid.au" }), true); }
    } catch (e) { setRes({ tone: "bad", text: errText(e, t) }); } finally { setBusy(""); }
  };
  const r: OpsReport | null | undefined = rep.data;
  return (
    <div className="ops-sec">
      <div className="pane">
        <div className="phead">
          <div><h4>{t("ops.r.h")}</h4><p className="note">{t("ops.r.sched")}</p></div>
          {can && (
            <div className="opsactions">
              <button type="button" className="btn sm" disabled={!!busy} onClick={() => void go("send")}>{busy === "send" ? t("ops.r.sending") : t("ops.r.send")}</button>
              <button type="button" className="btn ghost sm" disabled={!!busy} onClick={() => void go("test")}>{busy === "test" ? t("ops.r.sending") : t("ops.r.test")}</button>
            </div>
          )}
        </div>
        {res && <p className={"banner " + res.tone} role="status">{res.text}{res.link ? <> <a href={RUNBOOK + "#email-delivery"} target="_blank" rel="noreferrer noopener">{t("ops.s.runbook")}</a></> : null}</p>}
      </div>
      <div className="opsrep">
        <div className="pane opsrep-list">
          <h4>{t("ops.r.hist")}</h4>
          {list.error ? <ErrorBox error={list.error} retry={list.reload} /> : !list.data ? <p className="note">{t("common.loading")}</p> : !list.data.length ? <p className="note">{t("ops.r.none")}</p> : (
            <ul>
              {list.data.map((x) => (
                <li key={x.id}>
                  <button type="button" aria-current={String(x.id) === String(cur) || undefined} onClick={() => setSel(x.id)}>
                    <b>{t(x.kind === "daily" ? "ops.r.day" : "ops.r.week", { d: date(x.week_start) })}{x.trigger === "manual" ? <span className="muted"> · {t("ops.r.manual")}</span> : null}</b>
                    <span className="opsrep-meta"><MailPill s={x.status} /><small className="muted" title={date(x.created_at, true)}>{x.sent_at ? t("ops.r.sentat", { t: ago(x.sent_at) }) : t("ops.r.madeat", { t: ago(x.created_at) })}</small></span>
                    {x.error && x.status !== "not_configured" ? <small className="muted">{x.error}</small> : null}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="pane opsrep-view">
          <div className="phead">
            <h4>{r?.subject ?? t("ops.r.preview")}</h4>
            {r?.to ? <small className="muted">→ {r.to}</small> : null}
          </div>
          {rep.error ? <ErrorBox error={rep.error} retry={rep.reload} /> : cur == null ? <p className="note">{t("ops.r.none")}</p> : !r ? <p className="note">{t("common.loading")}</p> : r.html ? (
            <iframe className="opsframe" title={t("ops.r.preview")} sandbox="" srcDoc={r.html} referrerPolicy="no-referrer" />
          ) : r.text ? <pre className="opsstack">{r.text}</pre> : <p className="note">{t("ops.r.nohtml")}</p>}
          {r ? <p className="note">{tx("ops.mail." + r.status, r.status)}{r.error && r.status !== "not_configured" ? " · " + r.error : ""}</p> : null}
        </div>
      </div>
    </div>
  );
}

/* ================= shell ================= */
export function OpsTab() {
  const { t } = useI18n();
  const { item } = useParams();
  const nav = useNavigate();
  const tab: Tab = (TABS as readonly string[]).includes(item ?? "") ? (item as Tab) : "overview";
  const go = (x: Tab, id?: string | number) => nav(`/admin/ops/${x}${id != null ? "?id=" + encodeURIComponent(String(id)) : ""}`);
  const label: Record<Tab, string> = { overview: t("ops.tab.overview"), incidents: t("ops.tab.incidents"), traffic: t("ops.tab.traffic"), errors: t("ops.tab.errors"), reports: t("ops.tab.reports") };
  return (
    <div className="ops">
      <div className="atabs" role="tablist" aria-label={t("ad.t.ops")}>
        {TABS.map((x) => <button key={x} type="button" role="tab" id={"opstab-" + x} aria-selected={x === tab} aria-controls="opspanel" onClick={() => go(x)}>{label[x]}</button>)}
      </div>
      <div role="tabpanel" id="opspanel" aria-labelledby={"opstab-" + tab}>
        {tab === "overview" && <Overview go={go} />}
        {tab === "incidents" && <Incidents />}
        {tab === "traffic" && <Traffic />}
        {tab === "errors" && <Errors />}
        {tab === "reports" && <Reports />}
      </div>
    </div>
  );
}
