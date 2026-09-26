import type { DictKey } from "../dict";
import type { SelfReported } from "../api";

export type SrKind = "aud" | "pct" | "int" | "months";
export interface SrField { key: keyof SelfReported; label: DictKey; kind: SrKind; min: number; max: number }

/** Mirrors backend schemas.SelfReportedMetrics (same bounds). */
export const SR_FIELDS: SrField[] = [
  { key: "revenue_ttm_aud", label: "sr.revenue", kind: "aud", min: 0, max: 1e12 },
  { key: "revenue_growth_yoy_pct", label: "sr.growth", kind: "pct", min: -100, max: 10_000 },
  { key: "gross_margin_pct", label: "sr.margin", kind: "pct", min: -100, max: 100 },
  { key: "customers", label: "sr.customers", kind: "int", min: 0, max: 1e9 },
  { key: "raised_to_date_aud", label: "sr.raised", kind: "aud", min: 0, max: 1e12 },
  { key: "runway_months", label: "sr.runway", kind: "months", min: 0, max: 600 },
  { key: "employees", label: "sr.employees", kind: "int", min: 0, max: 1e7 },
];

/** Keep what the user may type: digits (and for % / months one "." ; for % a leading "-"). */
export function cleanInput(kind: SrKind, s: string): string {
  if (kind === "aud" || kind === "int") return s.replace(/\D/g, "").replace(/^0+(?=\d)/, "");
  let x = s.replace(/,/g, ".").replace(kind === "pct" ? /[^\d.-]/g : /[^\d.]/g, "");
  x = (x.startsWith("-") ? "-" : "") + x.replace(/-/g, "");
  const i = x.indexOf(".");
  return i < 0 ? x : x.slice(0, i + 1) + x.slice(i + 1).replace(/\./g, "");
}

/** Parse raw inputs -> {metrics, bad: field keys out of range}. Empty fields are omitted. */
export function parseSelfReported(raw: Partial<Record<keyof SelfReported, string>>): { metrics: SelfReported; bad: SrField[] } {
  const metrics: SelfReported = {};
  const bad: SrField[] = [];
  for (const f of SR_FIELDS) {
    const s = (raw[f.key] ?? "").trim();
    if (!s) continue;
    const n = Number(s);
    if (!Number.isFinite(n) || n < f.min || n > f.max || ((f.kind === "int") && !Number.isInteger(n))) bad.push(f);
    else metrics[f.key] = n;
  }
  return { metrics, bad };
}
