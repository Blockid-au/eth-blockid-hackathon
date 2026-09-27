/* Small shared v5 pieces: level / confidence / stage badges, legends, expanders, table fallback, checks. */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useI18n } from "../../i18n";
import type { DictKey } from "../../dict";
import { tip } from "../../lib/tip";
import { STAGES, type Check, type Conf, type Level, type Stage, type Unit } from "./types";
import type { LocalCheck } from "./csv";
import "./v5.css";

export function useFmt5() {
  const i = useI18n();
  /** Format a metric value by unit. */
  const val = (v: number | null | undefined, unit: Unit | string): string => {
    if (v == null || !Number.isFinite(v)) return "–";
    if (unit === "aud") return i.money(v);
    if (unit === "pct") return i.pct(v, Math.abs(v) < 10 && !Number.isInteger(v) ? 1 : 0);
    if (unit === "months") return i.t("v5.u.months", { n: i.fmt(v, Number.isInteger(v) ? 0 : 1) });
    if (unit === "x") return i.fmt(v, 1) + "×";
    if (unit === "rating") return i.fmt(v, 1) + " ★";
    if (unit === "rank") return "#" + i.fmt(v);
    if (Math.abs(v) >= 1e6) return i.fmt(v / 1e6, 1) + "M";
    if (Math.abs(v) >= 1e4) return i.fmt(v / 1e3, 0) + "k";
    return i.fmt(v, Number.isInteger(v) ? 0 : 1);
  };
  const stage = (s: string) => i.t(("v5.stage." + s.replace("_", "-")) as DictKey);
  const dim = (k: string) => i.t(("v5.dim." + k) as DictKey);
  return { ...i, val, stage, dim };
}

export function LevelBadge({ level, short }: { level: Level | number; short?: boolean }) {
  const { t } = useI18n();
  const l = Math.max(0, Math.min(4, Math.round(level))) as Level;
  return (
    <span className={"lvl l" + l} {...tip(t(("v5.lv." + l + ".d") as DictKey))} aria-label={t(("v5.lv." + l) as DictKey)}>
      <i aria-hidden="true">{l ? "L" + l : "–"}</i>{short ? null : t(("v5.lv." + l) as DictKey)}
    </span>
  );
}

export function LevelLegend() {
  const { t } = useI18n();
  return (
    <div className="card">
      <h4>{t("v5.lv.h")}</h4>
      <p className="sub">{t("v5.lv.p")}</p>
      <ul className="checks" style={{ gap: 8 }}>
        {([0, 1, 2, 3, 4] as Level[]).map((l) => (
          <li key={l} className="info" style={{ gridTemplateColumns: "minmax(0, 170px) 1fr" }}>
            <LevelBadge level={l} />
            <span className="muted-sm">{t(("v5.lv." + l + ".d") as DictKey)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ConfPill({ c, label }: { c: Conf; label?: boolean }) {
  const { t } = useI18n();
  return <span className={"conf " + c} {...tip(t(("v5.conf." + c + ".d") as DictKey))}>{label === false ? "" : t("v5.conf") + ": "}{t(("v5.conf." + c) as DictKey)}</span>;
}

export function StageBadge({ stage }: { stage: Stage | string }) {
  const { t, stage: sl } = useFmt5();
  return <span className="stagebadge"><small>{t("v5.stage")}</small>{sl(stage)}</span>;
}

export function StageRail({ stage }: { stage: string }) {
  const { stage: sl } = useFmt5();
  const i = (STAGES as readonly string[]).indexOf(stage.replace("_", "-"));
  return (
    <div className="stagerail" aria-hidden="true">
      {STAGES.map((s, k) => <span key={s} className={k === i ? "on" : k < i ? "past" : ""}>{sl(s)}</span>)}
    </div>
  );
}

export function SeeHow({ label, children, open }: { label?: string; children: ReactNode; open?: boolean }) {
  const { t } = useI18n();
  return (
    <details className="seehow" open={open}>
      <summary>{label ?? t("v5.seehow")}</summary>
      <div>{children}</div>
    </details>
  );
}

/** Accessible table view of a chart (every value reachable without hover). */
export function TableView({ head, rows, caption }: { head: ReactNode[]; rows: ReactNode[][]; caption: string }) {
  const { t } = useI18n();
  return (
    <details className="tblview">
      <summary>{t("v5.astable")}</summary>
      <div className="tbl">
        <table>
          <caption className="sr-only">{caption}</caption>
          <thead><tr>{head.map((h, i) => <th key={i} className={i ? "r" : undefined}>{h}</th>)}</tr></thead>
          <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className={j ? "r" : undefined}>{c}</td>)}</tr>)}</tbody>
        </table>
      </div>
    </details>
  );
}

const ICON: Record<string, string> = { error: "!", warning: "!", info: "i", ok: "✓" };
/** Checks from the server (plain `message`) or from the browser (`code` + vars → dict "v5.chk.<code>"). */
export function Checks({ items, empty }: { items: (Check | LocalCheck)[]; empty?: string }) {
  const { t } = useI18n();
  if (!items.length) return empty ? <ul className="checks"><li className="ok"><span className="ic" aria-hidden="true">✓</span><span>{empty}</span></li></ul> : null;
  const order = { error: 0, warning: 1, info: 2 };
  const sorted = [...items].sort((a, b) => order[a.severity] - order[b.severity]);
  return (
    <ul className="checks">
      {sorted.map((c, i) => (
        <li key={i} className={c.severity}>
          <span className="ic" aria-hidden="true">{ICON[c.severity]}</span>
          <span><span className="sr-only">{t(("v5.sev." + c.severity) as DictKey)}: </span>{"message" in c && c.message ? c.message : t(("v5.chk." + c.code) as DictKey, "vars" in c ? c.vars : undefined)}</span>
        </li>
      ))}
    </ul>
  );
}

/** Tabs bound to the URL hash (#traction …), so a tab can be linked and /verify is untouched. */
export function useHashTab<T extends string>(keys: readonly T[], def: T): [T, (k: T) => void] {
  const read = () => { const h = decodeURIComponent(location.hash.replace(/^#/, "")) as T; return keys.includes(h) ? h : def; };
  const [cur, setCur] = useState<T>(read);
  useEffect(() => { const on = () => setCur(read()); window.addEventListener("hashchange", on); return () => window.removeEventListener("hashchange", on); }); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k: T) => { setCur(k); history.replaceState(history.state, "", location.pathname + location.search + "#" + k); };
  return [cur, set];
}

export function Tabs5<T extends string>({ tabs, cur, set, label }: { tabs: { key: T; label: string; badge?: string }[]; cur: T; set: (k: T) => void; label: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const onKey = (e: React.KeyboardEvent) => {
    const i = tabs.findIndex((x) => x.key === cur);
    const n = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : null;
    if (n == null) return;
    e.preventDefault();
    const k = tabs[(n + tabs.length) % tabs.length].key;
    set(k);
    ref.current?.querySelector<HTMLButtonElement>(`[data-k="${k}"]`)?.focus();
  };
  // keep the current tab visible inside the strip (horizontal only; never scrolls the page)
  useEffect(() => {
    const box = ref.current, el = box?.querySelector<HTMLButtonElement>(`[data-k="${cur}"]`);
    if (!box || !el) return;
    if (el.offsetLeft < box.scrollLeft) box.scrollLeft = el.offsetLeft - 8;
    else if (el.offsetLeft + el.offsetWidth > box.scrollLeft + box.clientWidth) box.scrollLeft = el.offsetLeft + el.offsetWidth - box.clientWidth + 8;
  }, [cur]);
  return (
    <div className="v5tabs" role="tablist" aria-label={label} ref={ref} onKeyDown={onKey}>
      {tabs.map((x, i) => (
        <button key={x.key} data-k={x.key} id={"v5t-" + x.key} role="tab" type="button" aria-selected={x.key === cur} aria-controls={"v5p-" + x.key} tabIndex={x.key === cur ? 0 : -1} onClick={() => set(x.key)}>
          <span className="tn">{String(i + 1).padStart(2, "0")}</span>{x.label}{x.badge ? <span className="sc">{x.badge}</span> : null}
        </button>
      ))}
    </div>
  );
}

export function KTile({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return <div className="kt"><small>{label}</small><b>{value}</b>{sub ? <em>{sub}</em> : null}</div>;
}

export function hostOf(u: string | null | undefined): string {
  if (!u) return "";
  if (u.startsWith("doc:")) return u;
  try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; }
}

export function SrcLink({ url, label }: { url?: string | null; label?: string | null }) {
  const { t } = useI18n();
  if (!url) return <span className="muted-sm">{label || t("v5.src.self")}</span>;
  if (url.startsWith("doc:")) return <span className="muted-sm">{t("v5.src.doc")}</span>;
  return <a href={url} target="_blank" rel="noopener noreferrer nofollow">{label || hostOf(url)}</a>;
}
