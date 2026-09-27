import type { DictKey } from "../dict";
import type { Svi } from "../api";
import type { DimRow } from "../components/charts";

const DIM_ALIASES: [RegExp, DictKey][] = [
  [/found|team/i, "dim.founder"],
  [/product|tech/i, "dim.product"],
  [/market/i, "dim.market"],
  [/revenue|traction/i, "dim.revenue"],
  [/growth/i, "dim.growth"],
  [/ready|readiness|invest/i, "dim.ready"],
  [/trust|govern/i, "dim.trust"],
];
const ORDER: DictKey[] = ["dim.founder", "dim.product", "dim.market", "dim.revenue", "dim.growth", "dim.ready", "dim.trust"];

/** Dimensions the admin may override (backend QualitativeScores); revenue/growth are computed from numbers. */
export const OVERRIDABLE = new Set(["founder_quality", "product_strength", "market_attractiveness", "investment_readiness", "trust_verification"]);

export function dimKey(name: string): DictKey | null {
  for (const [re, k] of DIM_ALIASES) if (re.test(name)) return k;
  return null;
}

const humanize = (s: string) => s.replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());

/** Normalise the SVI dimensions + weights into ordered rows (weights as fractions). */
export function dimRows(svi: Svi, t: (k: DictKey) => string, overrides?: Record<string, number>): DimRow[] {
  const rows = Object.entries(svi.dimensions || {}).map(([name, d]) => {
    const k = dimKey(name);
    let w = Number(svi.weights?.[name] ?? 0);
    if (w > 1) w = w / 100;
    const score = overrides && overrides[name] != null ? overrides[name] : Number(d?.score ?? 0);
    return { key: name, label: k ? t(k) : humanize(name), score, weight: w, basis: d?.basis, rationale: d?.rationale, order: k ? ORDER.indexOf(k) : 99 };
  });
  rows.sort((a, b) => a.order - b.order);
  return rows.map(({ order: _o, ...r }) => r);
}

export function gradeOf(index: number): string {
  return index >= 80 ? "A" : index >= 65 ? "B" : index >= 50 ? "C" : index >= 35 ? "D" : "E";
}

/** Grade letter from svi.band ("B", "grade B", …) or from the index. */
export function bandGrade(svi: Pick<Svi, "band" | "index">): string {
  const m = /\b([A-E])\b/.exec(String(svi.band ?? "").toUpperCase());
  return m ? m[1] : gradeOf(Number(svi.index));
}

const STEP_ALIASES: [RegExp, DictKey][] = [
  [/^analysts$/i, "log.analysts"],
  [/^valuation_methods$/i, "log.methods"],
  [/fetch|site|crawl|read_?web|website/i, "log.1"],
  [/profile|intake|extract/i, "log.2"],
  [/compet/i, "log.3"],
  [/market|research/i, "log.4"],
  [/svi|score|valu/i, "log.5"],
  [/narrat|report|summary/i, "log.6"],
];
export function stepLabel(key: string, t: (k: DictKey) => string): string {
  for (const [re, k] of STEP_ALIASES) if (re.test(key)) return t(k);
  return humanize(key);
}
