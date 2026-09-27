/* Mock backend for evaluation + valuation v5 (?mock=1). Shapes follow docs/EVALUATION-V5-API.md and
   docs/VALUATION-V5-API.md. Two sample reports: /v/demo5/report (seed, rich data) and /v/demo5-pre/report (pre-seed,
   thin data, low confidence). `v5Decorate` turns any finished mock valuation into a v5 one so /start → report works. */
import { getAddress, keccak256, toHex } from "viem";
import { ApiError, type Valuation } from "./api";

export const NO_V5 = Symbol("no-v5");
type Obj = Record<string, unknown>;
const DAY = 864e5;
const iso = (t: number) => new Date(t).toISOString();
const addr = (seed: string) => getAddress(keccak256(toHex(seed)).slice(0, 42) as `0x${string}`);
const MOCK_USER = addr("mock-user-wallet");
let ctx: { actor: () => string; isAdmin: () => boolean } = { actor: () => MOCK_USER, isAdmin: () => false };
export function v5Init(c: typeof ctx) { ctx = c; }

/* ---------------- builders ---------------- */
const mv = (value: number | null, unit: string, level: number, source = "self_reported", extra: Obj = {}) => (value == null ? null : { value, unit, as_of: "2026-08", level, source, source_url: "", quote: "", note: "", ...extra });
const shrink = [0, 0.6, 0.8, 0.9, 1];
function rawScore(v: number, b: number[], lower = false): number {
  const pts: [number, number][] = [[b[0], 25], [b[1], 50], [b[2], 75], [b[3], 90]];
  const xs = lower ? pts.map(([x, s]) => [-x, s] as [number, number]) : pts;
  const x = lower ? -v : v;
  if (x <= xs[0][0]) return Math.max(5, 25 - ((xs[0][0] - x) / Math.max(Math.abs(xs[1][0] - xs[0][0]), 1e-9)) * 25);
  for (let i = 1; i < xs.length; i++) if (x <= xs[i][0]) return xs[i - 1][1] + ((x - xs[i - 1][0]) / (xs[i][0] - xs[i - 1][0])) * (xs[i][1] - xs[i - 1][1]);
  return Math.min(98, 90 + ((x - xs[3][0]) / Math.max(Math.abs(xs[3][0] - xs[2][0]), 1e-9)) * 8);
}
function sm(key: string, metric: string, label: string, weight: number, value: Obj | null, bench: number[] | null, lower = false, status?: string): Obj {
  const v = value ? Number(value.value) : null;
  const raw = v != null && bench ? rawScore(v, bench, lower) : null;
  const score = raw == null ? null : 50 + (raw - 50) * shrink[Number(value!.level)];
  return { key, metric, label, weight, value, benchmark: bench, lower_is_better: lower, score_raw: raw == null ? null : +raw.toFixed(1), score: score == null ? null : +score.toFixed(1), status: status ?? (v == null ? "missing" : bench ? "scored" : "not_benchmarked"), note: "" };
}
function dim(key: string, label: string, weight: number, subs: Obj[], extra: Obj = {}): Obj {
  const have = subs.filter((s) => s.score != null);
  const cov = subs.reduce((a, s) => a + (s.score != null ? Number(s.weight) : 0), 0) / (subs.reduce((a, s) => a + Number(s.weight), 0) || 1);
  const rawM = have.length ? have.reduce((a, s) => a + Number(s.score) * Number(s.weight), 0) / have.reduce((a, s) => a + Number(s.weight), 0) : null;
  const cap = 40 + 60 * cov;
  const score = rawM == null ? 40 : Math.min(rawM, cap);
  const lvl = have.length ? have.reduce((a, s) => a + Number((s.value as Obj).level) * Number(s.weight), 0) / have.reduce((a, s) => a + Number(s.weight), 0) : 0;
  const top = [...subs].sort((a, b) => Number(b.weight) - Number(a.weight))[0];
  const conf = cov >= 0.7 && top?.value && Number((top.value as Obj).level) >= 2 ? "high" : cov >= 0.4 ? "medium" : "low";
  return { key, label, weight, score: +score.toFixed(1), score_raw: rawM == null ? null : +rawM.toFixed(1), coverage: +cov.toFixed(2), cap: +cap.toFixed(1), level: +lvl.toFixed(2), confidence: conf, status: rawM == null ? "not_enough_data" : "scored", basis: "computed", sub_metrics: subs, evidence: [], flags: [], improve: [], rationale: "", ...extra };
}

/* ---------------- sample A: Harbourline Logistics, seed, rich data ---------------- */
function seedAnalysis(host: string): Obj {
  const traction = dim("traction", "Commercial traction", 0.18, [
    sm("T1", "arr_aud", "Revenue scale (ARR)", 0.3, mv(456000, "AUD", 2, "csv"), [90e3, 450e3, 750e3, 1.5e6]),
    sm("T2", "yoy_growth_pct", "Growth, year on year", 0.4, mv(118, "%", 2, "csv"), [40, 75, 150, 250]),
    sm("T3", "paying_customers", "Paying customers", 0.15, mv(120, "count", 3, "site", { source_url: "https://" + host + "/about", quote: "We move 40,000 pallets a month for 120 customers across Australia." }), [15, 40, 120, 300]),
    sm("T4", "backlog_ratio", "Signed backlog ÷ ARR", 0.15, mv(0.22, "x", 1), [0.05, 0.15, 0.3, 0.5]),
  ], { improve: ["Upload 12 months of MRR movements to back the growth figure with more history"] });
  const market = dim("market", "Market size & timing", 0.15, [
    sm("M1", "sam_aud", "Market you can serve (SAM)", 0.4, mv(182_400_000, "AUD", 3, "lookup"), [20e6, 80e6, 300e6, 1e9]),
    sm("M2", "tam_aud", "Total market (TAM)", 0.15, mv(2_150_000_000, "AUD", 3, "cited", { source_url: "https://www.ibisworld.com/au/industry/road-freight-transport/", quote: "Road freight transport in Australia: revenue of $62.7bn…" }), [200e6, 1e9, 5e9, 20e9]),
    sm("M3", "market_cagr_pct", "Market growth per year", 0.25, mv(2.1, "%", 3, "cited", { source_url: "https://www.ibisworld.com/au/industry/road-freight-transport/" }), [3, 8, 15, 25]),
    sm("M4", "som_realism", "Share of SAM already won", 0.1, mv(0.25, "%", 2, "computed"), [0.05, 0.3, 1, 3]),
    sm("M5", "source_tier", "Source quality", 0.1, mv(1, "rank", 3, "computed"), [4, 3, 2, 1], true),
  ], { improve: ["A cited growth figure for freight software specifically (not all road freight) would lift market timing"] });
  const moat = dim("moat", "Competitive moat", 0.12, [
    sm("Mo:network_effects", "network_effects", "Network effects", 0.2, mv(35, "count", 1), [0, 35, 70, 100]),
    sm("Mo:switching_costs", "switching_costs", "Switching costs", 0.2, mv(70, "count", 2, "site"), [0, 35, 70, 100]),
    sm("Mo:ip_data", "ip_data", "IP & data", 0.15, mv(35, "count", 1), [0, 35, 70, 100]),
    sm("Mo:scale", "scale", "Scale", 0.1, null, [0, 35, 70, 100]),
    sm("Mo:brand", "brand", "Brand", 0.1, mv(70, "count", 3, "lookup"), [0, 35, 70, 100]),
    sm("Mo:counter_positioning", "counter_positioning", "Counter-positioning", 0.1, null, [0, 35, 70, 100]),
    sm("Mo:competition", "competition", "Competition", 0.15, mv(46, "count", 3, "competitors"), [25, 50, 75, 90]),
  ], { improve: ["Add your trade mark or patent numbers so they can be checked in IP Australia"] });
  const retention = dim("retention", "Customer retention", 0.09, [
    sm("R1", "nrr_pct", "Net revenue retention", 0.3, mv(104, "%", 2, "csv"), [90, 100, 110, 120]),
    sm("R2", "grr_pct", "Gross revenue retention", 0.25, mv(88, "%", 2, "csv"), [80, 85, 90, 95]),
    sm("R3", "m3_retention_pct", "Still active after 3 months", 0.2, null, null),
    sm("R4", "review_rating", "Review rating", 0.15, mv(4.6, "rating", 3, "lookup", { source_url: "https://www.capterra.com.au/" }), [3.8, 4.2, 4.5, 4.8]),
    sm("R5", "top_customer_share_pct", "Largest customer's share", 0.1, mv(24, "%", 1), [50, 20, 10, 5], true),
  ], { improve: ["Month-3 and month-12 retention by starting month (a cohort table)"], flags: ["The largest customer is 24% of revenue (above 20%)"] });
  const efficiency = dim("efficiency", "Capital efficiency", 0.05, [
    sm("E1", "burn_multiple", "Burn multiple", 0.3, mv(1.8, "x", 2, "csv"), [4, 3, 2, 1.5], true),
    sm("E2", "runway_months", "Runway", 0.25, mv(16, "months", 1), [9, 15, 21, 27]),
    sm("E3", "gross_margin_pct", "Gross margin", 0.25, mv(61, "%", 1), [50, 65, 72, 80]),
    sm("E4", "cac_payback_months", "CAC payback", 0.1, mv(14, "months", 1), null, true, "not_benchmarked"),
    sm("E5", "ltv_cac", "LTV ÷ CAC", 0.05, mv(3.1, "x", 1), null, false, "not_benchmarked"),
  ]);
  return {
    version: "v5",
    stage: { stage: "seed", basis: "revenue", reasons: ["ARR A$456k (document-backed) is in the seed band (A$150k–1.5M).", "No priced round in the last 30 months.", "Raised A$1.2M to date, consistent with seed."], sources: [], signals: {}, conflict: false, table_version: "2026-09" },
    stage_profile: {}, sector_key: "saas", revenue_model: "subscription",
    dimensions: {
      founder_quality: { key: "founder_quality", label: "Founding team", weight: 0.3, score: 72, coverage: 1, cap: 100, level: 3, confidence: "high", status: "team_report", basis: "team_report", sub_metrics: [], evidence: [], flags: [], improve: [], rationale: "Two founders with a prior logistics exit; CTO shipped fleet software at scale." },
      traction, market, moat, retention, efficiency,
      product_strength: { key: "product_strength", label: "Product", weight: 0.06, score: 68, coverage: 1, level: 2, confidence: "medium", status: "ai_suggested", basis: "ai_suggested", sub_metrics: [], evidence: [], flags: [], improve: [], rationale: "Live product with public pricing and integrations." },
      investment_readiness: { key: "investment_readiness", label: "Investment readiness", weight: 0.03, score: 70, coverage: 1, level: 2, confidence: "medium", status: "ai_suggested", basis: "ai_suggested", sub_metrics: [], evidence: [], flags: [], improve: [], rationale: "" },
      trust_verification: { key: "trust_verification", label: "Verification", weight: 0.02, score: 64, coverage: 1, level: 2, confidence: "medium", status: "scored", basis: "computed", sub_metrics: [], evidence: [], flags: [], improve: [], rationale: "64% of scored weight is document-backed or better." },
    },
    metrics: { arr_aud: mv(456000, "AUD", 2, "csv"), nrr_pct: mv(104, "%", 2, "csv"), grr_pct: mv(88, "%", 2, "csv"), gross_margin_pct: mv(61, "%", 1), yoy_growth_pct: mv(118, "%", 2, "csv") },
    claims: [], dropped: ["revenue 'A$2m run rate' on the careers page: a run rate, not ARR", "market size 'A$4bn logistics tech' — the quote does not name the segment"],
    flags: [
      { code: "cross_source_gap", severity: "warning", message: "Typed revenue (A$820k) and the metrics CSV (A$456k ARR) differ by more than 20%: the lower figure was used.", metrics: ["revenue_ttm_aud", "arr_aud"], action: "lower_used" },
      { code: "concentration", severity: "info", message: "The largest customer is 24% of revenue.", metrics: ["top_customer_share_pct"], action: "" },
    ],
    powers: [
      { key: "network_effects", label: "Network effects", weight: 0.2, level: 1, level_cap: 2, points: 35, evidence: [{ quote: "The more carriers join, the faster loads get matched.", source_url: "https://" + host + "/" }], note: "" },
      { key: "switching_costs", label: "Switching costs", weight: 0.2, level: 2, level_cap: 2, points: 70, evidence: [{ quote: "Integrates with 14 TMS and accounting tools including Xero and MYOB.", source_url: "https://" + host + "/integrations" }], note: "" },
      { key: "ip_data", label: "IP & data", weight: 0.15, level: 1, level_cap: 3, points: 35, evidence: [], note: "Claimed proprietary routing data; no registry number yet." },
      { key: "scale", label: "Scale", weight: 0.1, level: 0, level_cap: 1, points: 0, evidence: [], note: "" },
      { key: "brand", label: "Brand", weight: 0.1, level: 2, level_cap: 2, points: 70, evidence: [{ quote: "4.6 stars from 212 reviews", source_url: "https://www.capterra.com.au/" }], note: "" },
      { key: "counter_positioning", label: "Counter-positioning", weight: 0.1, level: 0, level_cap: 3, points: 0, evidence: [], note: "" },
      { key: "competition", label: "Competition", weight: 0.15, level: 0, level_cap: 3, points: 46, evidence: [], note: "4 direct competitors; the best funded raised A$12M." },
    ],
    market_sizing: { sam_aud: 182_400_000, target_customer: "Australian freight carriers with 5–200 trucks", target_customers: 38000, target_customers_source: "abs:I:20-199", annual_price_aud: 4800, annual_price_source: "https://" + host + "/pricing", tam_aud: 2_150_000_000, tam_source_url: "https://www.ibisworld.com/au/industry/road-freight-transport/", tam_quote: "Logistics software spend by Australian transport operators is estimated at $2.15bn.", cagr_pct: 2.1, cagr_source_url: "https://www.ibisworld.com/au/industry/road-freight-transport/", som_share: [0.01, 0.04], som_aud_5y: [1_824_000, 7_296_000], source_tier: 1, warnings: [] },
    lookups: { tranco_rank: 412_004, wayback_first_seen: "2019-06", app_store: { rating: 4.6, count: 212 }, abn: "Active since 2019" },
    trust_share: 0.64, confidence: "medium",
    top_improvements: ["Upload 12 months of MRR movements to back the growth figure with more history", "Add your trade mark or patent numbers so they can be checked in IP Australia", "Month-3 and month-12 retention by starting month (a cohort table)"],
    documents: [{ doc_id: "d1", kind: "metrics_csv", filename: "metrics-2025-2026.csv", sha256: "9f2c4ab0d1e5c7a8b3f60e1d2c9a7b4e5f6a1c2d3e4f5a6b7c8d9e0f1a2b3c4d" }],
    analysts: { traction: { model: "gpt-oss-120b", claims: 4, dropped: 1, searches: 2 }, market_size: { model: "gpt-oss-120b", claims: 3, dropped: 1, searches: 3 }, moat: { model: "gpt-oss-120b", claims: 5, dropped: 0, searches: 1 }, retention: { model: "gpt-oss-120b", claims: 2, dropped: 0, searches: 1 } },
    cohorts: [{ label: "2025-10", pts: [100, 94, 90, 88, 86, 85, 84] }, { label: "2026-01", pts: [100, 96, 93, 91] }, { label: "2026-04", pts: [100, 95, 92] }],
  };
}
const M = (method: string, label: string, value: number, low: number, high: number, raw: number, inputs: Obj, extra: Obj = {}): Obj => ({ method, label, value_aud: value, low_aud: low, high_aud: high, raw_weight: raw, weight: 0, inputs, sources: [], notes: [], checks: [], ...extra });
function finishTri(methods: Obj[], stage: string, cls: string, conf: string, reasons: string[], extra: Obj = {}): Obj {
  const tot = methods.reduce((a, m) => a + Number(m.raw_weight), 0) || 1;
  methods.forEach((m) => { m.weight = +(Number(m.raw_weight) / tot).toFixed(4); });
  const value = Math.round(methods.reduce((a, m) => a + Number(m.value_aud) * Number(m.weight), 0));
  const hw = conf === "high" ? 0.1 : conf === "medium" ? 0.2 : 0.35;
  const low = Math.round(value * (1 - hw)), high = Math.round(value * (1 + hw));
  const price = ({ idea: 0.1, "pre-seed": 0.1, seed: 0.25 } as Record<string, number>)[stage] ?? 1;
  const raw = value / price, step = Math.pow(10, Math.max(Math.floor(Math.log10(raw)) - 2, 0));
  const shares = Math.round(raw / step) * step;
  const rec = +(value / shares).toFixed(4);
  return {
    version: "v5", params_version: "v5", market_dataset: "2026-09-26", value_aud: value, low_aud: low, high_aud: high, confidence: conf, confidence_reasons: reasons,
    valuation_class: cls, stage: { stage, basis: "revenue", reasons: [] }, methods,
    football_field: methods.map((m) => ({ method: m.method, label: m.label, low_aud: m.low_aud, mid_aud: m.value_aud, high_aud: m.high_aud, weight: m.weight, used: Number(m.weight) > 0, reason: Number(m.weight) > 0 ? null : (m.notes as string[]).find((n) => n.startsWith("not used")) ?? "not used at this stage", projection_based: ["dcf", "vc_method", "first_chicago"].includes(String(m.method)) })),
    without_projections: null, projections: null,
    tokenisation: { pre_money_aud: value, low_aud: low, high_aud: high, stage, basis: "new_company", fd_shares_existing: null, default_price_for_stage_aud: price, recommended_price_per_share_aud: rec, total_shares: shares, offer_price_low_aud: +(low / shares).toFixed(4), offer_price_high_aud: rec, raise_aud: 0, new_shares: 0, post_money_aud: 0, dilution_pct: 0 },
    listed: false, listing: "", as_of: "2026-09-27", fx_as_of: "2026-09-26", ...extra,
  };
}
function sens(base: number, rate: number, g: number): Obj {
  const rates = [-2, -1, 0, 1, 2].map((i) => +(rate + i * 0.01).toFixed(4)), gs = [-2, -1, 0, 1, 2].map((i) => +(g + i * 0.005).toFixed(4));
  return { rates, gs, values: rates.map((r) => gs.map((gg) => (r <= gg ? null : Math.round(base * ((rate - g) / (r - gg)) ** 0.85)))) };
}
function seedTri(withProj: boolean): Obj {
  const methods = [
    M("scorecard", "scorecard vs typical seed company (base A$4,000,000 x 1.04)", 4_160_000, 3_328_000, 4_992_000, 0.6,
      { stage: "seed", base_pre_money_aud: 4_000_000, factor: 1.04, weights: { founder_quality: 0.3, traction: 0.18, market: 0.15, moat: 0.12, retention: 0.09, efficiency: 0.05, product_strength: 0.06, investment_readiness: 0.03, trust_verification: 0.02 }, lines: { founder_quality: { score: 72 }, traction: { score: 71 }, market: { score: 58 }, moat: { score: 43 }, retention: { score: 58 }, efficiency: { score: 55 }, product_strength: { score: 68 }, investment_readiness: { score: 70 }, trust_verification: { score: 64 } } }),
    M("vc_method", "venture capital method (exit A$27,360,000 in 5 years, target 10x-20x)", 4_050_000, 2_236_000, 7_170_000, withProj ? 0.8 * 0.7 : 0.8 * 0.4,
      { exit_metric_aud: 4_560_000, exit_multiple: 6, investment_aud: 1_000_000, years_to_exit: 5, retention: 0.75, target_multiples: [10, 15, 20], projection_based: true }, { notes: ["based on management projections (unaudited, not verified by BlockID)"] }),
    M("revenue_multiple", "revenue × cited sector multiple (5.5x median, 3 verified comps)", 4_390_000, 3_150_000, 5_880_000, 0.4 * 0.8 * 0.9,
      { revenue_aud: 456_000, revenue_source: "csv", median_multiple: 9.6, low_multiple: 6.9, high_multiple: 12.9, discount: 0.25, n: 3, multiple_source: "comps", multiples: [{ name: "WiseTech Global", multiple: 14.2, source_url: "https://www.asx.com.au/" }, { name: "MachShip", multiple: 8.1, source_url: "https://www.afr.com/" }, { name: "Transvirtual", multiple: 6.9, source_url: "https://www.smartcompany.com.au/" }] }),
    M("dcf", "discounted cash flow (venture discount rate 38.0%, 5 years)", 4_900_000, 3_600_000, 6_400_000, withProj ? 0.2 * 0.4 : 0,
      { rows: [2026, 2027, 2028, 2029, 2030, 2031].map((y, i) => ({ year: y, actual: i === 0, revenue: [456e3, 1.05e6, 2.2e6, 3.8e6, 5.6e6, 7.3e6][i] })), rate_build: { rate: 0.38, rf: 0.043, beta: 1.6, erp: 0.06, size_premium: 0.035 }, rate_kind: "venture", g: 0.025, terminal: "gordon", net_debt_aud: -250_000, projection_based: true,
        result: { fcff: [-620e3, -410e3, 60e3, 520e3, 1.1e6, 1.6e6], ebitda: [-540e3, -300e3, 210e3, 760e3, 1.4e6, 2e6], ev: 4_650_000, tv_share: 0.71, terminal_used: "gordon", uncapped_value_aud: 6_300_000, sensitivity: sens(4_900_000, 0.38, 0.025) } },
      { checks: [{ code: "growth_cap", severity: "warning", message: "Revenue grows 130% in 2027; we used 130% (within the seed limit of 200%).", year: 2027, row: "revenue", used_value: null }, { code: "hockey_stick", severity: "info", message: "71% of the value comes from after 2031 (terminal value).", year: null, row: null, used_value: null }], notes: withProj ? ["based on management projections (unaudited, not verified by BlockID)"] : ["not used: no confirmed forecast"] }),
    M("rfs", "risk factor summation (12 risks, net +1 steps of A$200,000 on A$4,000,000)", 4_200_000, 3_360_000, 5_040_000, 0.5 * 0.5,
      { base_pre_money_aud: 4_000_000, step_ratio: 0.05, net_steps: 1, ratings: { management: 1, stage: 0, legislation: 0, manufacturing: 0, sales_marketing: 1, funding: 0, competition: -1, technology: 1, litigation: 0, international: -1, reputation: 1, exit: -1 }, evidence: ["ai_suggested"] }, { notes: ["risk ratings suggested, not yet confirmed: weight reduced"] }),
    M("berkus", "Berkus method (5 milestones, up to A$750,000 each)", 2_550_000, 2_040_000, 3_060_000, 0,
      { cap_per_factor_aud: 750_000, scores: { sound_idea: 80, prototype: 90, quality_team: 75, strategic_relationships: 45, product_rollout: 50 } }, { notes: ["not used: revenue above A$250k — Berkus is for pre-revenue companies"] }),
    M("stage_scorecard", "typical seed value (fallback)", 3_900_000, 2_700_000, 5_400_000, 0, { stage: "seed" }, { notes: ["not used: the scorecard has inputs"] }),
  ];
  const tri = finishTri(methods, "seed", "seed", "medium", ["Key traction and retention figures are backed by an uploaded metrics CSV (document-backed).", "Gross margin and runway are self-reported.", "Three verified comparable companies."], withProj ? { projections: { sha256: "4be1…", attested_by: MOCK_USER, attested_at: iso(Date.now() - 3 * DAY), label: "Based on management projections (unaudited, not verified by BlockID)." } } : {});
  if (withProj) {
    const noProj = methods.filter((m) => !["dcf", "vc_method"].includes(String(m.method)));
    const tot = noProj.reduce((a, m) => a + Number(m.raw_weight), 0);
    tri.without_projections = { value_aud: Math.round(noProj.reduce((a, m) => a + Number(m.value_aud) * Number(m.raw_weight), 0) / tot), low_aud: 0, high_aud: 0 };
  }
  return tri;
}

/* ---------------- sample B: pre-seed, thin data, low confidence ---------------- */
function preAnalysis(): Obj {
  const empty = (key: string, label: string, w: number, subs: Obj[], extra: Obj = {}) => dim(key, label, w, subs, extra);
  return {
    version: "v5", stage: { stage: "pre-seed", basis: "raised", reasons: ["No revenue figures were given or found.", "Raised A$350k to date (below A$1M): pre-seed."], conflict: false, table_version: "2026-09" },
    sector_key: "consumer", revenue_model: "subscription",
    dimensions: {
      founder_quality: { key: "founder_quality", label: "Founding team", weight: 0.3, score: 50, coverage: 0.5, level: 1, confidence: "low", status: "ai_suggested", basis: "ai_suggested", sub_metrics: [], evidence: [], flags: [], improve: ["Add the founding team for a full team review"], rationale: "Suggested from the website only; capped at 50 without a team review." },
      traction: empty("traction", "Commercial traction", 0.16, [
        sm("T1", "arr_aud", "Revenue scale", 0.3, null, [0, 15e3, 60e3, 150e3]), sm("T2", "cmgr_pct", "Monthly growth", 0.4, null, [5, 10, 20, 30]),
        sm("T3", "active_users", "Active users", 0.15, mv(900, "count", 1), [50, 300, 1000, 5000]), sm("T4", "waitlist", "Waitlist", 0.15, mv(2400, "count", 1), [0, 200, 1000, 5000]),
      ], { improve: ["Monthly active users for the last 6 months (a CSV) would show your growth rate"] }),
      market: empty("market", "Market size & timing", 0.15, [sm("M1", "sam_aud", "SAM", 0.4, null, [20e6, 80e6, 300e6, 1e9]), sm("M3", "market_cagr_pct", "Market growth", 0.25, mv(11, "%", 3, "cited"), [3, 8, 15, 25])], { improve: ["Tell us who you sell to and your price, so the market can be sized bottom-up"] }),
      moat: empty("moat", "Competitive moat", 0.12, [sm("Mo:brand", "brand", "Brand", 0.1, null, [0, 35, 70, 100])]),
      retention: { key: "retention", label: "Customer retention", weight: 0.07, score: 40, coverage: 0, cap: 40, level: 0, confidence: "low", status: "not_applicable", basis: "computed", sub_metrics: [], evidence: [], flags: [], improve: [], rationale: "At pre-seed, product evidence stands in for retention." },
      efficiency: empty("efficiency", "Capital efficiency", 0.04, [sm("E2", "runway_months", "Runway", 0.25, mv(11, "months", 1), [6, 12, 18, 24])]),
      product_strength: { key: "product_strength", label: "Product", weight: 0.1, score: 62, coverage: 1, level: 2, confidence: "medium", status: "ai_suggested", basis: "ai_suggested", sub_metrics: [], evidence: [], flags: [], improve: [], rationale: "Beta app live on the App Store." },
      investment_readiness: { key: "investment_readiness", label: "Investment readiness", weight: 0.04, score: 48, coverage: 1, level: 1, confidence: "low", status: "ai_suggested", basis: "ai_suggested", sub_metrics: [], evidence: [], flags: [], improve: [], rationale: "" },
      trust_verification: { key: "trust_verification", label: "Verification", weight: 0.02, score: 20, coverage: 1, level: 1, confidence: "low", status: "scored", basis: "computed", sub_metrics: [], evidence: [], flags: [], improve: [], rationale: "" },
    },
    metrics: {}, claims: [], dropped: [], flags: [], powers: [], market_sizing: null, lookups: {}, trust_share: 0.2, confidence: "low",
    top_improvements: ["Add the founding team for a full team review", "Tell us who you sell to and your price, so the market can be sized bottom-up", "Monthly active users for the last 6 months (a CSV) would show your growth rate"],
    documents: [], analysts: {},
  };
}
function preTri(): Obj {
  const methods = [
    M("scorecard", "scorecard vs typical pre-seed company (base A$1,500,000 x 0.86)", 1_290_000, 1_032_000, 1_548_000, 1.0 * 0.5, { stage: "pre-seed", base_pre_money_aud: 1_500_000, factor: 0.86, weights: { founder_quality: 0.3, traction: 0.16, market: 0.15, moat: 0.12, product_strength: 0.1, retention: 0.07 }, lines: { founder_quality: { score: 50 }, traction: { score: 42 }, market: { score: 47 }, moat: { score: 40 }, product_strength: { score: 62 }, retention: { score: 40 } }, evidence: ["ai_suggested"] }, { notes: ["some scores are suggested and not yet confirmed by a reviewer: weight reduced"] }),
    M("berkus", "Berkus method (5 milestones, up to A$750,000 each)", 1_425_000, 1_140_000, 1_710_000, 0.8 * 0.5, { cap_per_factor_aud: 750_000, scores: { sound_idea: 60, prototype: 70, quality_team: 40, strategic_relationships: 10, product_rollout: 10 }, evidence: ["ai_suggested"] }, { notes: ["milestone ratings suggested, not yet confirmed: weight reduced"] }),
    M("rfs", "risk factor summation (12 risks, net −3 steps of A$75,000 on A$1,500,000)", 1_275_000, 1_020_000, 1_530_000, 0.8 * 0.5, { base_pre_money_aud: 1_500_000, step_ratio: 0.05, net_steps: -3, ratings: { management: 0, stage: -1, legislation: 0, manufacturing: 0, sales_marketing: -1, funding: -1, competition: -1, technology: 1, litigation: 0, international: 0, reputation: 0, exit: 0 } }),
    M("vc_method", "venture capital method", 0, 0, 0, 0, {}, { notes: ["not used: needs a forecast (none uploaded)"] }),
  ];
  return finishTri(methods, "pre-seed", "pre_seed", "low", ["No revenue: only startup methods apply.", "Most inputs are suggested from the website and not yet confirmed.", "Team not reviewed."]);
}

/* ---------------- store ---------------- */
interface Rec { v: Valuation; tok: { final: Obj | null; pending: Obj | null; history: Obj[] }; docs: Obj[]; proj: Obj[]; hasProj: boolean }
const store = new Map<string, Rec>();
let reqId = 7, docId = 10, projId = 20;
function mkVal(id: string, url: string, name: string, stage: "seed" | "pre-seed", status: Valuation["status"]): Rec {
  const host = url.replace(/^https?:\/\//, "");
  const a = stage === "seed" ? seedAnalysis(host) : preAnalysis();
  const tri = stage === "seed" ? seedTri(true) : preTri();
  const dims = a.dimensions as Record<string, Obj>;
  const weights = Object.fromEntries(Object.entries(dims).map(([k, d]) => [k, d.weight]));
  const index = +Object.values(dims).reduce((s, d) => s + Number(d.score) * Number(d.weight), 0).toFixed(2);
  const band = index >= 80 ? "A" : index >= 65 ? "B" : index >= 50 ? "C" : index >= 35 ? "D" : "E";
  const v = {
    id, url, status, steps: ["read_site", "profile", "competitors", "market", "analysts", "svi", "narrative"].map((k, i) => ({ key: k, status: "done", detail: null, at: iso(Date.now() - 20 * DAY + i * 20e3) })),
    counters: { pages: 12, competitors: 4, sources: 21 }, profile: { name }, requested_by: MOCK_USER, created_at: iso(Date.now() - 20 * DAY),
    competitors: stage === "seed" ? [
      { name: "Shipit Freight", url: "https://shipit.example", raised_aud: 12_000_000, note: "Series B 2024", sources: 4 },
      { name: "Loadlink AU", url: "https://loadlink.example", raised_aud: 5_500_000, note: "Series A", sources: 3 },
      { name: "Freightmate", url: "https://freightmate.example", raised_aud: 3_200_000, note: "Seed + grant", sources: 2 },
      { name: "Cargo Hub", url: "https://cargohub.example", raised_aud: null, note: "Private", sources: 1 },
    ] : [],
    self_reported: stage === "seed" ? { revenue_ttm_aud: 820_000, gross_margin_pct: 61, customers: 120, employees: 18 } : { raised_to_date_aud: 350_000 },
    team_id: stage === "seed" ? "t_demo" : null,
    svi: {
      index, band, weights, weights_profile: "v5:" + stage,
      dimensions: Object.fromEntries(Object.entries(dims).map(([k, d]) => [k, { score: d.score, basis: d.basis, rationale: d.rationale }])),
      valuation_low_aud: tri.low_aud, valuation_mid_aud: tri.value_aud, valuation_high_aud: tri.high_aud,
      method: "v5 blend", narrative: `${name} ${stage === "seed" ? "sells freight-matching software to Australian carriers on subscription." : "is a consumer app in beta with a waitlist."}`,
      analysis: a, triangulation: tri,
    },
  } as unknown as Valuation;
  const r: Rec = { v, tok: { final: null, pending: null, history: [] }, docs: stage === "seed" ? [{ doc_id: "d1", kind: "metrics_csv", filename: "metrics-2025-2026.csv", sha256: "9f2c4ab0d1e5c7a8b3f60e1d2c9a7b4e5f6a1c2d3e4f5a6b7c8d9e0f1a2b3c4d", created_at: iso(Date.now() - 19 * DAY), parsed: demoSeries() }] : [], proj: [], hasProj: stage === "seed" };
  store.set(id, r);
  return r;
}
function demoSeries(): Obj {
  const months: string[] = [], mrr: number[] = [];
  let m = 17_400;
  for (let i = 13; i >= 0; i--) { const d = new Date(2026, 8 - i, 1); months.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`); mrr.push(Math.round(m)); m *= 1.068 + (i % 3 === 0 ? -0.02 : 0.01); }
  return { rows: 14, months, series: { mrr_aud: mrr, customers: mrr.map((x) => Math.round(x / 316)) }, metrics: { yoy_growth_pct: 118, cmgr_pct: 6.2, nrr_pct: 104, grr_pct: 88 }, flags: [], errors: [] };
}
mkVal("demo5", "https://harbourline.com.au", "Harbourline Logistics", "seed", "approved");
mkVal("demo5-pre", "https://brightpath.app", "Brightpath", "pre-seed", "approved");

/** Valuations started in this session from the v5 /start flow (any v2-only key in `metrics`, or none at all). */
const tracked = new Set<string>();
const V1 = ["revenue_ttm_aud", "revenue_growth_yoy_pct", "gross_margin_pct", "customers", "raised_to_date_aud", "runway_months", "employees"];
export function v5Track(id: string, metrics: unknown) {
  const keys = metrics && typeof metrics === "object" ? Object.keys(metrics) : [];
  if (!keys.length || keys.some((k) => !V1.includes(k))) tracked.add(id);
}
/** A finished mock valuation started from the v5 flow becomes v5 (so /start → report shows the v5 report in mock mode). */
export function v5Decorate(v: Valuation): void {
  if (!tracked.has(v.id) || !v.svi || (v.svi as unknown as Obj).analysis) return;
  const host = v.url.replace(/^https?:\/\//, "");
  const a = seedAnalysis(host), tri = seedTri(false);
  const dims = a.dimensions as Record<string, Obj>;
  const s = v.svi as unknown as Obj;
  s.analysis = a; s.triangulation = tri; s.weights_profile = "v5:seed";
  s.weights = Object.fromEntries(Object.entries(dims).map(([k, d]) => [k, d.weight]));
  s.dimensions = Object.fromEntries(Object.entries(dims).map(([k, d]) => [k, { score: d.score, basis: d.basis, rationale: d.rationale }]));
  s.index = +Object.values(dims).reduce((x, d) => x + Number(d.score) * Number(d.weight), 0).toFixed(2);
  s.valuation_low_aud = tri.low_aud; s.valuation_mid_aud = tri.value_aud; s.valuation_high_aud = tri.high_aud;
  if (!store.has(v.id)) store.set(v.id, { v, tok: { final: null, pending: null, history: [] }, docs: [], proj: [], hasProj: false });
}

function tokView(r: Rec): Obj {
  const tri = (r.v.svi as unknown as Obj).triangulation as Obj;
  const f = r.tok.final;
  const state = !f ? "none" : +new Date(String(f.valid_until)) < Date.now() ? "expired" : "valid";
  const conf = String(tri.confidence);
  const blockers: string[] = [];
  if (r.v.status !== "approved") blockers.push("The valuation must be approved first.");
  if (conf === "low") blockers.push("Confidence is low: a platform admin must finalise it with a reason.");
  return {
    valuation_id: r.v.id, valuation_status: r.v.status, confidence: conf, proposal: tri.tokenisation, final: f, final_state: state, pending_request: r.tok.pending,
    can_finalise: blockers.length === 0 && state !== "valid", blockers,
    rules: { free_band_pct: 20, hard_min_ratio: 0.2, hard_max_ratio: 5, validity_days: 90, min_confidence: "medium", default_price_by_stage: { idea: 0.1, "pre-seed": 0.1, seed: 0.25, "series-a": 1, growth: 1 } },
  };
}
function makeFinal(r: Rec, price: number, note: string | null, reason: string | null, approvedBy: string | null, reqIdN: number | null, override: Obj | null): Obj {
  const tri = (r.v.svi as unknown as Obj).triangulation as Obj;
  const tk = tri.tokenisation as Obj;
  const rec = Number(tk.recommended_price_per_share_aud);
  const same = Math.abs(price - rec) < 1e-9;
  const shares = same ? Number(tk.total_shares) : Math.round(Number(tk.pre_money_aud) / price);
  return {
    version: 1, valuation_id: r.v.id, report_hash: keccak256(toHex("report:" + r.v.id)), formula_version: "v5", params_version: "v5", stage: tk.stage, valuation_class: tri.valuation_class, confidence: tri.confidence,
    pre_money_aud: tk.pre_money_aud, low_aud: tk.low_aud, high_aud: tk.high_aud, recommended_price_per_share_aud: rec, price_per_share_aud: +price.toFixed(4),
    price_deviation_pct: +((price / rec - 1) * 100).toFixed(2), price_note: note, price_reason: reason, price_request_id: reqIdN, price_approved_by: approvedBy,
    total_shares: shares, fd_shares_existing: null, implied_value_aud: Math.round(shares * price), offer_price_low_aud: +(Number(tk.low_aud) / shares).toFixed(4), offer_price_high_aud: +price.toFixed(4),
    revenue_used_aud: 456000, based_on_projections: r.hasProj, projection_sha256: null, finalised_by: ctx.actor(), finalised_at: iso(Date.now()), valid_until: iso(Date.now() + 90 * DAY), low_confidence_override: override,
  };
}

/* ---------------- routes ---------------- */
const get = (id: string) => { const r = store.get(decodeURIComponent(id)); if (!r) throw new ApiError(404, "Valuation not found"); return r; };
export function v5Handle(method: string, path: string, body: unknown): unknown {
  const b = (body ?? {}) as Obj;
  let m: RegExpMatchArray | null;
  if (method === "GET" && path === "/v1/studio/evaluation/config") return { enabled: true, stages: ["idea", "pre-seed", "seed", "series-a", "growth"], table_version: "2026-09", share_price_by_stage: { idea: 0.1, "pre-seed": 0.1, seed: 0.25, "series-a": 1, growth: 1 } };
  if (method === "POST" && path === "/v1/studio/evaluation/stage-preview") {
    const x = (b.metrics ?? {}) as Obj;
    const rev = Number(x.arr_aud ?? x.revenue_ttm_aud ?? (x.mrr_aud != null ? Number(x.mrr_aud) * 12 : NaN));
    const round = String(x.last_round_type ?? "");
    const byRound = ({ "pre-seed": "pre-seed", angel: "pre-seed", safe: "pre-seed", seed: "seed", "series-a": "series-a", "series-b": "growth", "series-c": "growth" } as Record<string, string>)[round];
    const stage = byRound ?? (Number.isFinite(rev) ? (rev <= 0 ? "idea" : rev < 150e3 ? "pre-seed" : rev < 1.5e6 ? "seed" : rev < 15e6 ? "series-a" : "growth") : "pre-seed");
    return { stage, basis: byRound ? "round" : Number.isFinite(rev) ? "revenue" : "default", reasons: byRound ? [`Latest round: ${round}.`] : Number.isFinite(rev) ? [`Revenue A$${Math.round(rev).toLocaleString("en-AU")} is in the ${stage} band.`] : ["No revenue or round given yet."], conflict: false, table_version: "2026-09" };
  }
  if (method === "GET" && (m = path.match(/^\/v1\/studio\/valuations\/([^/]+)$/)) && store.has(decodeURIComponent(m[1])) && ["demo5", "demo5-pre"].includes(decodeURIComponent(m[1]))) return structuredClone(get(m[1]).v);
  if (method === "GET" && (m = path.match(/^\/v1\/studio\/valuations\/([^/]+)\/evidence$/)) && ["demo5", "demo5-pre"].includes(decodeURIComponent(m[1]))) {
    return [
      { url: "https://www.ibisworld.com/au/industry/road-freight-transport/", title: "Road Freight Transport in Australia – Market Size", snippet: "Industry revenue is expected to grow at an annualised 2.1%…", retrieved_at: iso(Date.now() - 20 * DAY), kind: "web" },
      { url: "https://www.capterra.com.au/", title: "Capterra – reviews", snippet: "4.6 stars from 212 reviews", retrieved_at: iso(Date.now() - 20 * DAY), kind: "web" },
      { url: get(m[1]).v.url + "/about", title: "Company website – About", snippet: "We move 40,000 pallets a month for 120 customers across Australia.", retrieved_at: iso(Date.now() - 20 * DAY), kind: "site" },
    ];
  }
  if ((m = path.match(/^\/v1\/studio\/valuations\/([^/]+)\/(tokenisation|finalise|documents|rescore|projections)(?:\/(.*))?$/))) {
    const r = get(m[1]);
    const sub = m[2], rest = m[3] ?? "";
    if (sub === "tokenisation" && method === "GET") return tokView(r);
    if (sub === "finalise" && method === "POST") {
      const tri = (r.v.svi as unknown as Obj).triangulation as Obj;
      const tk = tri.tokenisation as Obj;
      const rec = Number(tk.recommended_price_per_share_aud);
      const price = b.price_per_share_aud == null ? rec : Number(b.price_per_share_aud);
      if (r.v.status !== "approved") throw new ApiError(409, "The valuation must be approved first.");
      if (r.tok.final && tokView(r).final_state === "valid") throw new ApiError(409, "Already finalised.");
      if (price < rec * 0.2 || price > rec * 5) throw new ApiError(422, "Price must be between 0.2× and 5× the recommended price.");
      let override: Obj | null = null;
      if (tri.confidence === "low") {
        if (!ctx.isAdmin() || !b.allow_low_confidence || String(b.override_reason ?? "").trim().length < 10) throw new ApiError(409, "Confidence is low: only a platform admin can finalise, with a reason (10+ characters).");
        override = { by: ctx.actor(), reason: String(b.override_reason) };
      }
      const dev = price / rec - 1;
      if (Math.abs(dev) > 0.2 + 1e-9) {
        if (String(b.reason ?? "").trim().length < 20) throw new ApiError(422, "A reason of at least 20 characters is needed for a price more than 20% away.");
        r.tok.pending = { id: reqId++, valuation_id: r.v.id, status: "pending", recommended_price_aud: rec, requested_price_aud: price, deviation_pct: +(dev * 100).toFixed(2), reason: String(b.reason), note: b.note ?? null, requested_by: ctx.actor(), report_hash: null, decided_by: null, decided_at: null, decision_reason: null, created_at: iso(Date.now()), _override: override };
        return tokView(r);
      }
      if (Math.abs(dev) > 1e-9 && String(b.note ?? "").trim().length < 3) throw new ApiError(422, "A short note (3+ characters) is needed when the price differs from the recommendation.");
      r.tok.final = makeFinal(r, price, (b.note as string) ?? null, null, null, null, override);
      return tokView(r);
    }
    if (sub === "documents") {
      if (method === "GET") return structuredClone(r.docs);
      if (method === "DELETE") { r.docs = r.docs.filter((d) => d.doc_id !== rest); return { deleted: true }; }
      if (method === "POST") {
        if (r.docs.length >= 5) throw new ApiError(409, "At most 5 documents per valuation.");
        let parsed: Obj = { chars: String(b.text ?? "").length };
        if (b.kind === "metrics_csv") {
          const lines = String(b.rows ?? "").trim().split(/\r?\n/);
          const head = (lines[0] ?? "").split(",").map((h) => h.trim().toLowerCase());
          const mi = head.indexOf("month"), ri = head.indexOf("mrr_aud") >= 0 ? head.indexOf("mrr_aud") : head.indexOf("revenue_aud");
          const rows = lines.slice(1).map((l) => l.split(","));
          const errors = rows.flatMap((c, i) => (ri >= 0 && c[ri] && !Number.isFinite(Number(c[ri])) ? [`row ${i + 2}: ${head[ri]} is not a number`] : []));
          parsed = { rows: rows.length, months: rows.map((c) => c[mi]), series: ri >= 0 ? { [head[ri]]: rows.map((c) => (c[ri] ? Number(c[ri]) : null)) } : {}, metrics: {}, flags: [], errors };
        }
        const d = { doc_id: "d" + docId++, kind: b.kind, filename: b.filename, sha256: b.sha256, parsed, uploaded_by: ctx.actor(), created_at: iso(Date.now()) };
        r.docs.push(d);
        return structuredClone(d);
      }
    }
    if (sub === "rescore" && method === "POST") return structuredClone(r.v);
    if (sub === "projections") {
      if (method === "GET" && !rest) return { latest: r.proj[r.proj.length - 1] ?? null, history: r.proj, label: "Based on management projections (unaudited, not verified by BlockID)." };
      if (method === "POST" && !rest) {
        const ys = ((b.years ?? []) as Obj[]);
        const checks: Obj[] = [];
        if (b.xlsx) checks.push({ code: "growth_cap", severity: "warning", message: "Revenue grows 240% in 2028; we used 160% (seed limit after year one).", year: 2028, row: "revenue", used_value: 3_900_000 });
        const proj = ys.filter((y) => !y.actual);
        if (!b.xlsx && proj.length < 3) checks.push({ code: "structure", severity: "error", message: "At least 3 projected years are needed.", year: null, row: null, used_value: null });
        let prev = ys.filter((y) => y.actual).map((y) => Number(y.revenue)).pop() ?? null, cap = 200;
        for (const y of proj) { if (prev && Number(y.revenue) / prev - 1 > cap / 100) checks.push({ code: "growth_cap", severity: "warning", message: `Revenue grows ${Math.round((Number(y.revenue) / prev - 1) * 100)}% in ${y.year}; we used ${Math.round(cap)}% (seed limit).`, year: y.year, row: "revenue", used_value: Math.round(prev * (1 + cap / 100)) }); prev = Number(y.revenue); cap *= 0.8; }
        if (!ys.some((y) => y.tax != null)) checks.push({ code: "tax_default", severity: "info", message: "No tax row: 25% company tax on positive EBIT was used.", year: null, row: "tax", used_value: null });
        const pv = { id: projId++, valuation_id: r.v.id, status: "draft", filename: b.xlsx ?? "forecast.csv", size_bytes: 4096, sha256: keccak256(toHex("proj" + projId)).slice(2), template_version: 1, uploaded_by: ctx.actor(), attested_by: null, attested_at: null, created_at: iso(Date.now()), parsed: b.xlsx ? { ...b, years: [] } : b, checks, can_confirm: !checks.some((c) => c.severity === "error"), errors: checks.filter((c) => c.severity === "error").length, warnings: checks.filter((c) => c.severity === "warning").length };
        r.proj.push(pv);
        return structuredClone(pv);
      }
      if (method === "POST" && (m = rest.match(/^(\d+)\/confirm$/))) {
        const p = r.proj.find((x) => x.id === +m![1]);
        if (!p) throw new ApiError(404, "Projection not found");
        if (!p.can_confirm) throw new ApiError(409, "Fix the errors first.");
        p.status = "confirmed"; p.attested_by = ctx.actor(); p.attested_at = iso(Date.now());
        const tri = (r.v.svi as unknown as Obj).triangulation as Obj;
        const before = Number(tri.value_aud);
        if (!r.hasProj && store.get(r.v.id)) { const nt = seedTri(true); (r.v.svi as unknown as Obj).triangulation = nt; r.hasProj = true; }
        const after = Number(((r.v.svi as unknown as Obj).triangulation as Obj).value_aud);
        const moved = +((after / before - 1) * 100).toFixed(2);
        const back = r.v.status === "approved" && Math.abs(moved) > 5;
        if (back) r.v.status = "waiting_approval";
        return { projection: structuredClone(p), valuation_status: r.v.status, value_before_aud: before, value_after_aud: after, moved_pct: moved, back_to_review: back };
      }
      if (method === "DELETE") { r.proj = r.proj.filter((x) => String(x.id) !== rest); return { ok: true }; }
    }
  }
  if ((m = path.match(/^\/v1\/studio\/valuations\/([^/]+)\/price-requests\/(\d+)\/cancel$/)) && method === "POST") {
    const r = get(m[1]);
    if (r.tok.pending && Number(r.tok.pending.id) === +m[2]) { r.tok.pending.status = "cancelled"; r.tok.history.push(r.tok.pending); r.tok.pending = null; }
    return tokView(r);
  }
  if (method === "GET" && path === "/v1/admin/price-requests") {
    if (!ctx.isAdmin()) throw new ApiError(403, "admin only");
    return [...store.values()].filter((r) => r.tok.pending?.status === "pending").map((r) => ({ ...r.tok.pending, url: r.v.url, company_name: (r.v.profile?.name as string) ?? null }));
  }
  if ((m = path.match(/^\/v1\/admin\/price-requests\/(\d+)\/(approve|reject)$/)) && method === "POST") {
    if (!ctx.isAdmin()) throw new ApiError(403, "admin only");
    const r = [...store.values()].find((x) => x.tok.pending && Number(x.tok.pending.id) === +m![1]);
    if (!r || !r.tok.pending) throw new ApiError(404, "Request not found");
    const p = r.tok.pending;
    if (String(p.requested_by).toLowerCase() === ctx.actor().toLowerCase()) throw new ApiError(403, "You sent this request: another admin must decide it.");
    if (m[2] === "reject" && String(b.reason ?? "").trim().length < 5) throw new ApiError(422, "reason must be at least 5 characters");
    p.status = m[2] === "approve" ? "approved" : "rejected"; p.decided_by = ctx.actor(); p.decided_at = iso(Date.now()); p.decision_reason = (b.reason ?? b.note ?? null) as string | null;
    if (m[2] === "approve") r.tok.final = makeFinal(r, Number(p.requested_price_aud), (p.note as string) ?? null, String(p.reason), ctx.actor(), Number(p.id), (p._override as Obj) ?? null);
    r.tok.history.push(p); r.tok.pending = null;
    return tokView(r);
  }
  return NO_V5;
}

/* one pending price request so the admin queue has an item */
{
  const r = store.get("demo5-pre")!;
  r.tok.pending = { id: reqId++, valuation_id: "demo5-pre", status: "pending", recommended_price_aud: 0.1, requested_price_aud: 0.15, deviation_pct: 50, reason: "Our SAFE converts at a A$1.8M cap, which prices shares at about A$0.15.", note: null, requested_by: addr("brightpath-founder"), created_at: iso(Date.now() - 5 * 3600e3) };
}
