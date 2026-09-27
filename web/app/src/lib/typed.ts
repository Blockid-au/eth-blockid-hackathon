/* Strict reading of numbers and periods typed into forms (the API applies the same rules; see
 * agents/src/blockid_agents/studio/updates.py, offerings.py, dividend_policy.py). */
import type { Cadence } from "../api";

/** What a person typed into a number field: nothing, something unreadable, or a number (dp = decimals that matter,
 * trailing zeros not counted: "10.500" has 1). */
export type Typed = { kind: "empty" } | { kind: "bad" } | { kind: "ok"; n: number; dp: number };

/** Plain decimal numbers only: an optional "-", digits, an optional "." part. Commas / spaces as thousands separators
 * are ignored. No exponents ("1e5"), no "--5", nothing that is not finite. */
export function readNumber(raw: string): Typed {
  const s = raw.trim().replace(/[,\s]/g, "");
  if (s === "") return { kind: "empty" };
  if (!/^-?(\d+\.?\d*|\.\d+)$/.test(s)) return { kind: "bad" };
  const n = Number(s);
  if (!Number.isFinite(n)) return { kind: "bad" };
  const dot = s.indexOf(".");
  return { kind: "ok", n, dp: dot < 0 ? 0 : s.slice(dot + 1).replace(/0+$/, "").length };
}

/** A whole number typed plainly ("1,000" is fine; no decimals, no exponent). null when not. */
export function readWhole(raw: string): number | null {
  const r = readNumber(raw);
  return r.kind === "ok" && r.dp === 0 && Number.isSafeInteger(r.n) ? r.n : null;
}

/* ---------- periods (same rules as update_draft.period_end_problem) ---------- */
const pad = (n: number) => String(n).padStart(2, "0");
export const isoDay = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
/** Local calendar date from "YYYY-MM-DD" (no time-zone shift). */
export const fromIso = (s: string) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return d.getMonth() === Number(m[2]) - 1 ? d : null;
};
/** Last day of the month "YYYY-MM". */
export const monthEnd = (ym: string) => {
  const m = /^(\d{4})-(\d{2})$/.exec(ym);
  return m ? isoDay(new Date(Number(m[1]), Number(m[2]), 0)) : "";
};
export const quarterEnd = (year: number, q: number) => isoDay(new Date(year, q * 3, 0));
export const todayIso = () => isoDay(new Date());

/** The most recent period of this cadence that has fully ended (local date). */
export function lastFinishedEnd(c: Cadence): string {
  const t = new Date();
  if (c === "weekly") return isoDay(new Date(t.getFullYear(), t.getMonth(), t.getDate() - 1));
  if (c === "quarterly") return isoDay(new Date(t.getFullYear(), Math.floor(t.getMonth() / 3) * 3, 0));
  if (c === "annual") {  // the Australian financial year ends on 30 June
    const y = t.getMonth() >= 6 ? t.getFullYear() : t.getFullYear() - 1;
    return `${y}-06-30`;
  }
  return isoDay(new Date(t.getFullYear(), t.getMonth(), 0));
}

/** First day of the period that ends on `end` (same maths as update_draft.period_start for aligned ends). */
export function periodStartOf(c: Cadence, end: string): string {
  const d = fromIso(end);
  if (!d) return "";
  if (c === "weekly") return isoDay(new Date(d.getFullYear(), d.getMonth(), d.getDate() - 6));
  const months = c === "monthly" ? 1 : c === "quarterly" ? 3 : 12;
  return isoDay(new Date(d.getFullYear(), d.getMonth() - months + 1, 1));
}

export type PeriodProblem = "none" | "bad" | "align_month" | "align_quarter" | "future";
export function periodProblem(c: Cadence, end: string): PeriodProblem {
  const d = fromIso(end);
  if (!d || d.getFullYear() < 2000) return "bad";
  const eom = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate() === d.getDate();
  if ((c === "monthly" || c === "annual") && !eom) return "align_month";
  if (c === "quarterly" && !(eom && (d.getMonth() + 1) % 3 === 0)) return "align_quarter";
  if (end >= todayIso()) return "future";
  return "none";
}
