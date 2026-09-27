/**
 * Browser-side parsing of the two v5 uploads, with inline checks (the server re-checks everything):
 *  - metrics CSV  (docs/PLAN-EVALUATION-V5.md §3.2, template docs/templates/metrics-monthly.csv)
 *  - projections  (docs/PLAN-VALUATION-V5.md §6.1 sheet "Projections" + "Company", CSV flavour)
 * Checks carry a code + vars; the UI turns them into EN/VI text (dict.v5.ts "v5.chk.*").
 */
import type { ProjectionIn, ProjectionYearIn } from "./api5";

export interface LocalCheck { code: string; severity: "error" | "warning" | "info"; vars?: Record<string, string | number> }

/** RFC-4180-ish CSV → rows of cells (quotes, escaped quotes, CRLF). */
export function parseCsv(text: string): string[][] {
  const out: string[][] = [];
  let row: string[] = [], cell = "", q = false;
  const s = text.replace(/^﻿/, "");
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (q) {
      if (c === '"') { if (s[i + 1] === '"') { cell += '"'; i++; } else q = false; }
      else cell += c;
    } else if (c === '"') q = true;
    else if (c === ",") { row.push(cell); cell = ""; }
    else if (c === "\n" || c === "\r") { if (c === "\r" && s[i + 1] === "\n") i++; row.push(cell); out.push(row); row = []; cell = ""; }
    else cell += c;
  }
  if (cell || row.length) { row.push(cell); out.push(row); }
  return out.filter((r) => r.some((x) => x.trim() !== ""));
}

const toNum = (s: string | undefined): number | null => {
  if (s == null) return null;
  const x = s.trim().replace(/[$,\s]|A\$|AUD/gi, "");
  if (!x || x === "-") return null;
  const neg = /^\(.*\)$/.test(x);
  const n = Number(neg ? x.slice(1, -1) : x);
  return Number.isFinite(n) ? (neg ? -n : n) : NaN;
};

/* ---------------- metrics CSV ---------------- */
export const METRIC_COLS = ["month", "revenue_aud", "mrr_aud", "new_mrr", "expansion_mrr", "contraction_mrr", "churned_mrr", "customers", "new_customers", "churned_customers", "active_users", "cash_aud", "burn_aud"] as const;
const ALIASES: Record<string, (typeof METRIC_COLS)[number]> = {
  month: "month", date: "month", period: "month",
  revenue: "revenue_aud", revenue_aud: "revenue_aud", mrr: "mrr_aud", mrr_aud: "mrr_aud", "total mrr": "mrr_aud", "ending mrr": "mrr_aud",
  new_mrr: "new_mrr", "new mrr": "new_mrr", expansion_mrr: "expansion_mrr", "expansion mrr": "expansion_mrr", contraction_mrr: "contraction_mrr", "contraction mrr": "contraction_mrr",
  churned_mrr: "churned_mrr", "churned mrr": "churned_mrr", "churn mrr": "churned_mrr", customers: "customers", "active customers": "customers", subscribers: "customers",
  new_customers: "new_customers", churned_customers: "churned_customers", active_users: "active_users", mau: "active_users", cash_aud: "cash_aud", cash: "cash_aud", burn_aud: "burn_aud", burn: "burn_aud", "net burn": "burn_aud",
};
export interface MetricsParsed {
  rows: Record<string, string | number | null>[];
  checks: LocalCheck[];
  months: number;
  last?: { month: string; mrr: number | null; revenue: number | null; customers: number | null };
  cmgr_pct: number | null;
  yoy_pct: number | null;
  nrr_pct: number | null;
  grr_pct: number | null;
}
export function parseMetricsCsv(text: string): MetricsParsed {
  const grid = parseCsv(text);
  const checks: LocalCheck[] = [];
  const empty: MetricsParsed = { rows: [], checks, months: 0, cmgr_pct: null, yoy_pct: null, nrr_pct: null, grr_pct: null };
  if (grid.length < 2) { checks.push({ code: "csv.empty", severity: "error" }); return empty; }
  const head = grid[0].map((h) => ALIASES[h.trim().toLowerCase()] ?? null);
  if (!head.includes("month")) { checks.push({ code: "csv.nomonth", severity: "error" }); return empty; }
  if (!head.includes("mrr_aud") && !head.includes("revenue_aud")) checks.push({ code: "csv.norev", severity: "error" });
  if (grid.length - 1 > 120) checks.push({ code: "csv.rows", severity: "error", vars: { n: 120 } });
  const rows: Record<string, string | number | null>[] = [];
  const seen = new Set<string>();
  const now = new Date().toISOString().slice(0, 7);
  grid.slice(1, 121).forEach((r, i) => {
    const o: Record<string, string | number | null> = {};
    head.forEach((k, j) => {
      if (!k) return;
      if (k === "month") {
        const m = /^(\d{4})[-/](\d{1,2})/.exec(r[j]?.trim() ?? "");
        if (!m) { checks.push({ code: "csv.badmonth", severity: "error", vars: { r: i + 2, v: r[j] ?? "" } }); o.month = null; return; }
        o.month = `${m[1]}-${m[2].padStart(2, "0")}`;
        return;
      }
      const n = toNum(r[j]);
      if (Number.isNaN(n)) checks.push({ code: "csv.nan", severity: "error", vars: { r: i + 2, c: k } });
      else if (n != null && n < 0 && k !== "burn_aud") checks.push({ code: "csv.neg", severity: "warning", vars: { r: i + 2, c: k } });
      o[k] = n == null || Number.isNaN(n) ? null : n;
    });
    if (typeof o.month === "string") {
      if (seen.has(o.month)) checks.push({ code: "csv.dup", severity: "warning", vars: { r: i + 2, m: o.month } });
      if (o.month > now) checks.push({ code: "csv.future", severity: "warning", vars: { r: i + 2, m: o.month } });
      seen.add(o.month);
    }
    rows.push(o);
  });
  rows.sort((a, b) => String(a.month).localeCompare(String(b.month)));
  const key = head.includes("mrr_aud") ? "mrr_aud" : "revenue_aud";
  const ser = rows.map((r) => (typeof r[key] === "number" ? (r[key] as number) : null));
  const n = ser.length;
  const at = (k: number) => ser[n - 1 - k];
  let cmgr: number | null = null, yoy: number | null = null;
  const k = Math.min(6, n - 1);
  if (k >= 3 && (at(k) ?? 0) > 0 && (at(0) ?? 0) > 0) cmgr = (Math.pow(at(0)! / at(k)!, 1 / k) - 1) * 100;
  if (n >= 13 && (at(12) ?? 0) > 0 && at(0) != null) yoy = (at(0)! / at(12)! - 1) * 100;
  // smooth-series forensics: coefficient of variation of month-on-month growth ≈ 0
  const g = ser.slice(1).map((x, i) => (x != null && ser[i] ? x / ser[i]! - 1 : null)).filter((x): x is number => x != null);
  if (g.length >= 6) {
    const mu = g.reduce((a, b) => a + b, 0) / g.length;
    const sd = Math.sqrt(g.reduce((a, b) => a + (b - mu) ** 2, 0) / g.length);
    if (mu !== 0 && Math.abs(sd / mu) < 0.02) checks.push({ code: "csv.smooth", severity: "warning" });
  }
  // NRR / GRR over the last 12 months from MRR movements
  let nrr: number | null = null, grr: number | null = null;
  if (head.includes("expansion_mrr") && head.includes("churned_mrr") && n >= 13) {
    const last12 = rows.slice(-12);
    const start = Number(rows[n - 13].mrr_aud ?? 0);
    const sum = (c: string) => last12.reduce((a, r) => a + Number(r[c] ?? 0), 0);
    if (start > 0) {
      grr = ((start - sum("contraction_mrr") - sum("churned_mrr")) / start) * 100;
      nrr = ((start + sum("expansion_mrr") - sum("contraction_mrr") - sum("churned_mrr")) / start) * 100;
      if (nrr < grr - 1e-6) checks.push({ code: "csv.nrrgrr", severity: "warning" });
    }
  }
  const l = rows[n - 1];
  if (n < 6) checks.push({ code: "csv.short", severity: "info", vars: { n } });
  return {
    rows, checks, months: n, cmgr_pct: cmgr, yoy_pct: yoy, nrr_pct: nrr, grr_pct: grr,
    last: l ? { month: String(l.month), mrr: typeof l.mrr_aud === "number" ? l.mrr_aud : null, revenue: typeof l.revenue_aud === "number" ? l.revenue_aud : null, customers: typeof l.customers === "number" ? l.customers : null } : undefined,
  };
}

export function metricsTemplate(): string {
  const head = METRIC_COLS.join(",");
  const d = new Date();
  const lines: string[] = [];
  for (let i = 12; i >= 1; i--) {
    const m = new Date(d.getFullYear(), d.getMonth() - i, 1);
    const ym = `${m.getFullYear()}-${String(m.getMonth() + 1).padStart(2, "0")}`;
    lines.push(ym + ",".repeat(METRIC_COLS.length - 1));
  }
  return head + "\n" + lines.join("\n") + "\n";
}

/* ---------------- projections ---------------- */
export const PROJ_ROWS = ["year", "actual", "revenue", "cogs", "opex", "ebitda", "d_and_a", "tax", "capex", "nwc", "headcount", "customers"] as const;
const REQUIRED = ["year", "actual", "revenue", "cogs", "opex", "d_and_a", "capex"];
export const COMPANY_ROWS = ["currency", "fiscal_year_end", "cash", "debt", "shares_fd", "planned_raise", "audited"] as const;
/** Y1 growth caps over the last actual year (valuation plan §6.4). */
export const GROWTH_CAP: Record<string, number> = { idea: 300, "pre-seed": 300, seed: 200, "series-a": 150, growth: 80, established: 25 };
export const GM_BAND: Record<string, [number, number]> = { saas: [55, 90], marketplace: [10, 80], services: [20, 60], hardware: [15, 55], retail: [15, 50] };

export function projectionTemplate(labels: Record<string, string>): string {
  const y = new Date().getFullYear();
  const years = [y - 2, y - 1, y, y + 1, y + 2, y + 3, y + 4];
  const esc = (s: string) => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
  const rows = [
    ["key", "label", ...years.map(String)].join(","),
    ["year", esc(labels.year), ...years.map(String)].join(","),
    ["actual", esc(labels.actual), ...years.map((x) => (x < y ? "A" : "P"))].join(","),
    ...PROJ_ROWS.slice(2).map((k) => [k, esc(labels[k] ?? k), ...years.map(() => "")].join(",")),
    "",
    ["key", "label", "value"].join(","),
    ...COMPANY_ROWS.map((k) => [k, esc(labels[k] ?? k), k === "currency" ? "AUD" : k === "fiscal_year_end" ? "06-30" : k === "audited" ? "N" : ""].join(",")),
  ];
  return rows.join("\n") + "\n";
}

export interface ProjParsed { data: ProjectionIn | null; checks: LocalCheck[] }
export function parseProjectionCsv(text: string, stage: string, sector = "saas"): ProjParsed {
  const grid = parseCsv(text);
  const checks: LocalCheck[] = [];
  const byKey = new Map<string, string[]>();
  for (const r of grid) { const k = (r[0] ?? "").trim().toLowerCase(); if (k && k !== "key" && !byKey.has(k)) byKey.set(k, r.slice(2)); }
  for (const k of REQUIRED) if (!byKey.has(k)) checks.push({ code: "pj.missingrow", severity: "error", vars: { k } });
  if (checks.length) return { data: null, checks };
  const yearsRaw = byKey.get("year")!.map((s) => s.trim()).filter(Boolean);
  const years: ProjectionYearIn[] = [];
  yearsRaw.forEach((ys, j) => {
    const year = Number(ys);
    if (!Number.isInteger(year)) { checks.push({ code: "pj.badyear", severity: "error", vars: { v: ys } }); return; }
    const cell = (k: string) => toNum(byKey.get(k)?.[j]);
    const need = (k: string) => { const n = cell(k); if (n == null || Number.isNaN(n)) { checks.push({ code: "pj.missing", severity: "error", vars: { k, y: year } }); return 0; } if (n < 0) checks.push({ code: "pj.neg", severity: "error", vars: { k, y: year } }); return n; };
    const opt = (k: string) => { const n = cell(k); return n == null || Number.isNaN(n) ? null : n; };
    const a = (byKey.get("actual")?.[j] ?? "").trim().toUpperCase();
    if (a !== "A" && a !== "P") checks.push({ code: "pj.ap", severity: "error", vars: { y: year } });
    years.push({ year, actual: a === "A", revenue: need("revenue"), cogs: need("cogs"), opex: need("opex"), ebitda: opt("ebitda"), d_and_a: need("d_and_a"), tax: opt("tax"), capex: need("capex"), nwc: opt("nwc"), headcount: opt("headcount"), customers: opt("customers") });
  });
  years.sort((x, y) => x.year - y.year);
  years.forEach((y, i) => { if (i && y.year !== years[i - 1].year + 1) checks.push({ code: "pj.gap", severity: "error", vars: { y: y.year } }); });
  const proj = years.filter((y) => !y.actual);
  if (proj.length < 3) checks.push({ code: "pj.few", severity: "error", vars: { n: proj.length } });
  if (!years.some((y) => y.actual)) checks.push({ code: "pj.noactual", severity: "info" });
  for (const y of years) {
    if (y.ebitda != null) {
      const calc = y.revenue - y.cogs - y.opex;
      if (Math.abs(y.ebitda - calc) > Math.max(1, Math.abs(calc) * 0.01)) checks.push({ code: "pj.identity", severity: "error", vars: { y: y.year, g: Math.round(y.ebitda), c: Math.round(calc) } });
    }
    if (y.revenue > 0) {
      const gm = ((y.revenue - y.cogs) / y.revenue) * 100;
      const band = GM_BAND[sector];
      if (band && (gm < band[0] || gm > band[1])) checks.push({ code: "pj.gm", severity: "warning", vars: { y: y.year, p: Math.round(gm), lo: band[0], hi: band[1] } });
    }
  }
  const lastA = [...years].reverse().find((y) => y.actual);
  const cap0 = GROWTH_CAP[stage] ?? 200;
  let cap = cap0, prev = lastA?.revenue ?? null;
  for (const y of proj) {
    if (prev && prev > 0) {
      const g = (y.revenue / prev - 1) * 100;
      if (g > cap) checks.push({ code: "pj.growth", severity: "warning", vars: { y: y.year, g: Math.round(g), c: Math.round(cap) } });
    }
    if (lastA && y === proj[0] && lastA.revenue > 0 && y.revenue > 3 * lastA.revenue) checks.push({ code: "pj.jump", severity: "warning", vars: { y: y.year } });
    prev = y.revenue; cap *= 0.8;
  }
  const lr = proj.slice(-2);
  if (lr.length && lr.every((y) => y.capex < 0.5 * y.d_and_a) && lr[0].d_and_a > 0) checks.push({ code: "pj.capex", severity: "warning" });
  if (!byKey.has("tax")) checks.push({ code: "pj.tax", severity: "info" });
  const cv = (k: string) => { const r = grid.find((x) => (x[0] ?? "").trim().toLowerCase() === k); return (r?.[2] ?? "").trim(); };
  const currency = (cv("currency") || "AUD").toUpperCase();
  if (!["AUD", "USD", "VND", "SGD", "NZD", "EUR", "GBP"].includes(currency)) checks.push({ code: "pj.currency", severity: "error", vars: { c: currency } });
  const data: ProjectionIn = {
    currency, fiscal_year_end: cv("fiscal_year_end") || "06-30", cash: Math.max(0, toNum(cv("cash")) || 0), debt: Math.max(0, toNum(cv("debt")) || 0),
    shares_fd: toNum(cv("shares_fd")) || null, planned_raise: Math.max(0, toNum(cv("planned_raise")) || 0), audited: /^y/i.test(cv("audited")), years,
  };
  return { data, checks };
}

export function downloadText(name: string, text: string, type = "text/csv") {
  const url = URL.createObjectURL(new Blob([text], { type: type + ";charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
