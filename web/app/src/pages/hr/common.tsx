import { useEffect, type ReactNode } from "react";
import { useI18n } from "../../i18n";
import type { DictKey } from "../../dict";
import type { PersonSubScore, TeamStatus } from "../../api";
import type { Tone } from "../../components/StatusBar";
import "../../components/hr.css";

export function useHrTitle(title: string) {
  useEffect(() => {
    document.title = title ? `${title} · BlockID HR` : "BlockID HR · Founding team review";
  }, [title]);
}

export const ACTIVE_HR: TeamStatus[] = ["queued", "running"];
export const hrGrade = (x: number) => (x >= 80 ? "A" : x >= 65 ? "B" : x >= 50 ? "C" : x >= 35 ? "D" : "E");
export const STATUS_TONE: Record<TeamStatus, Tone> = { draft: "idle", queued: "run", running: "run", done: "ok", failed: "bad" };
export const statusPill = (s: TeamStatus) => (s === "done" ? " ok" : s === "failed" ? " bad" : s === "draft" ? "" : " gold");

export function initials(name: string): string {
  const w = name.trim().split(/\s+/).filter(Boolean);
  return ((w[0]?.[0] ?? "") + (w.length > 1 ? w[w.length - 1][0] : "")).toUpperCase() || "?";
}
export function Avatar({ name, size = "" }: { name: string; size?: "" | "md" | "lg" }) {
  return <span className={"hr-avatar" + (size ? " " + size : "")} aria-hidden="true">{initials(name)}</span>;
}

export function hostOf(u: string): string {
  try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; }
}

/** Label of a sub-score / fit component / team component key, falling back to a readable key. */
export function partLabel(t: (k: DictKey) => string, prefix: "hr.sub." | "hr.fit." | "hr.comp.", key: string): string {
  const k = (prefix + key) as DictKey;
  const s = t(k);
  return s === k ? key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()) : s;
}

/** Horizontal score bars (0–100) with weight; capped parts are drawn in gold with a note. */
export function ScoreBars({ parts, prefix, cap = 50 }: { parts: Record<string, PersonSubScore>; prefix: "hr.sub." | "hr.fit."; cap?: number }) {
  const { t, fmt } = useI18n();
  const rows = Object.entries(parts ?? {});
  return (
    <div className="hr-bars">
      {rows.map(([k, s]) => {
        const v = Math.max(0, Math.min(100, Number(s.score) || 0));
        return (
          <div className="hr-bar" key={k} title={s.rationale || undefined}>
            <span>{partLabel(t, prefix, k)}{s.weight ? <span className="muted-sm"> · {fmt(s.weight > 1 ? s.weight : s.weight * 100)}%</span> : null}
              {s.capped && <small>{t("hr.r.capped", { c: cap })}</small>}
              {!s.capped && s.self_reported && <small><span className="pill hr-self">{t("hr.r.self")}</span></small>}
            </span>
            <span className="t" role="img" aria-label={`${partLabel(t, prefix, k)} ${fmt(v)}/100`}><i className={s.capped ? "cap" : v < 45 ? "low" : ""} style={{ width: v + "%" }} /></span>
            <span className="v">{fmt(v)}</span>
          </div>
        );
      })}
    </div>
  );
}

/** Simple list block; renders nothing when empty. */
export function ListBlock({ title, items, q = false }: { title: ReactNode; items?: string[] | null; q?: boolean }) {
  if (!items?.length) return null;
  return (
    <div>
      <h5>{title}</h5>
      <ul className={"hr-ul" + (q ? " q" : "")}>{items.map((x, i) => <li key={i}>{x}</li>)}</ul>
    </div>
  );
}

/** A small completeness / score ring. */
export function Ring({ value, size = 64, label }: { value: number; size?: number; label: string }) {
  const r = size / 2 - 6, C = 2 * Math.PI * r, v = Math.max(0, Math.min(100, value));
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--sunken)" strokeWidth={7} />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--accent)" strokeWidth={7} strokeLinecap="round" strokeDasharray={`${(v / 100) * C} ${C}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      <text x="50%" y="50%" dominantBaseline="central" textAnchor="middle" fontSize={size / 4.2} fontWeight={700} fill="var(--ink)" fontFamily="var(--display)">{Math.round(v)}%</text>
    </svg>
  );
}
