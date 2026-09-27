/**
 * Evaluation + valuation v5 — front-end view model.
 *
 * Source contracts: docs/EVALUATION-V5-API.md (`svi.analysis`, `svi.weights_profile`) and docs/VALUATION-V5-API.md
 * (`svi.triangulation` v5, TokenisationView). Every screen reads ONLY the output of `readV5(v)` / `readTok(view)`, so a
 * contract change means editing this file, not the screens. `readV5` returns null when the valuation carries no v5
 * data → callers render today's (v4) screens unchanged.
 */
import type { Valuation } from "../../api";

export const STAGES = ["idea", "pre-seed", "seed", "series-a", "growth"] as const;
export type Stage = (typeof STAGES)[number] | "established" | "listed";
export type Level = 0 | 1 | 2 | 3 | 4;
export type Conf = "high" | "medium" | "low";
export type Sev = "error" | "warning" | "info";
export interface Check { code: string; severity: Sev; message: string; year?: number | null; row?: string | null; used_value?: number | null }

/* ---------------- evaluation (SVI v5) ---------------- */
export type Unit = "aud" | "pct" | "count" | "months" | "x" | "rating" | "rank" | "text";
export interface SubMetric {
  key: string;              // T1..T4, M1..M5, R1..R5, E1..E6, Mo:<power>
  metric: string;           // arr_aud, yoy_growth_pct, …
  label?: string;
  value: number | null;
  unit: Unit;
  score: number | null;     // after the evidence shrink; null = missing
  weight: number;
  level: Level;
  bench?: [number, number, number, number] | null;
  lower_better?: boolean;
  status?: string;
  source?: string | null;
  source_url?: string | null;
  quote?: string | null;
  note?: string | null;
  as_of?: string | null;
}
export type DimKey5 = "founder_quality" | "traction" | "market" | "moat" | "retention" | "efficiency" | "product_strength" | "investment_readiness" | "trust_verification";
export const DIMS5: DimKey5[] = ["founder_quality", "traction", "market", "moat", "retention", "efficiency", "product_strength", "investment_readiness", "trust_verification"];
export interface Dim5 {
  key: string;
  label?: string;
  score: number;
  weight: number;
  coverage: number;
  cap?: number;
  level: number;
  confidence: Conf;
  status?: string;
  basis?: string;
  rationale?: string;
  improve: string[];
  flags: string[];
  submetrics: SubMetric[];
}
export interface StageInfo { stage: Stage; basis: string; reasons: string[]; table_version?: string; conflict?: boolean }
export interface MarketSizing {
  tam_aud: number | null; sam_aud: number | null; som_aud: [number, number] | null; cagr_pct: number | null;
  target_customer?: string; customers: number | null; customers_source?: string; price_aud: number | null; price_source?: string;
  tam_source_url?: string; tam_quote?: string; cagr_source_url?: string; som_share: [number, number] | null; source_tier: number; warnings: string[];
}
export interface Power { key: string; label?: string; level: 0 | 1 | 2 | 3; points: number; weight: number; cap: number; quote?: string | null; source_url?: string | null; note?: string; computed: boolean }
export interface Cohort { label: string; pts: (number | null)[] }
export interface Series { months: string[]; revenue?: (number | null)[]; mrr?: (number | null)[]; customers?: (number | null)[]; level?: Level }
export interface Flag { code: string; severity: "info" | "warning" | "high"; message: string; action?: string }
export interface AnalystRun { name: string; model?: string; claims?: number; dropped?: number; searches?: number; error?: string | null }
export interface Eval5 {
  version: string;
  stage: StageInfo;
  sector?: string;
  revenue_model?: string;
  index: number;
  band: string;
  confidence: Conf;
  trust_share: number;
  dims: Dim5[];
  metrics: Record<string, SubMetric>;
  market: MarketSizing | null;
  powers: Power[];
  cohorts: Cohort[];
  series: Series | null;
  top_raise: string[];
  flags: Flag[];
  dropped: string[];
  analysts: AnalystRun[];
  lookups: Record<string, unknown>;
  docs: { doc_id: string; kind: string; filename: string; sha256: string }[];
}

/* ---------------- valuation v5 ---------------- */
export type MethodKey = "market_anchor" | "revenue_multiple" | "stage_scorecard" | "ebitda_multiple" | "precedents" | "dcf" | "vc_method" | "scorecard" | "berkus" | "rfs" | "first_chicago" | string;
export const PROJECTION_METHODS = ["dcf", "vc_method", "first_chicago"];
export interface Method5 {
  method: MethodKey; label: string; value_aud: number; low_aud: number; high_aud: number; weight: number; raw_weight?: number;
  inputs: Record<string, unknown>; sources: string[]; notes: string[]; checks: Check[]; excluded_reason?: string | null; uses_projections?: boolean;
}
export interface FieldBar { method: MethodKey; label: string; low_aud: number; mid_aud: number; high_aud: number; weight: number; excluded_reason?: string | null; uses_projections?: boolean; uncapped_mid_aud?: number | null }
export interface Tokenisation {
  pre_money_aud: number; low_aud: number; high_aud: number; stage: string; basis: string; fd_shares_existing: number | null;
  default_price_aud: number; recommended_price_aud: number; total_shares: number; offer_price_low_aud: number; offer_price_high_aud: number;
  raise_aud: number; new_shares: number; post_money_aud: number; dilution_pct: number;
}
export interface Tri5 {
  version: string; value_aud: number; low_aud: number; high_aud: number; confidence: Conf; confidence_reasons: string[];
  methods: Method5[]; field: FieldBar[];
  stage_class: { cls: string; stage?: string; reasons: string[] } | null;
  tokenisation: Tokenisation | null;
  params_version?: string; market_dataset?: string;
  uses_projections: boolean; projection_label?: string | null; without_projections_aud: number | null;
}
export interface ValuationFinal {
  pre_money_aud: number; low_aud: number; high_aud: number; stage: string; confidence?: Conf;
  recommended_price_aud: number; price_per_share_aud: number; deviation_pct: number; note?: string | null; reason?: string | null;
  approved_by?: string | null; total_shares: number; fd_shares_existing?: number | null; offer_price_low_aud: number; offer_price_high_aud: number;
  based_on_projections?: boolean; report_hash?: string | null; params_version?: string; finalised_by?: string | null; finalised_at?: string | null; valid_until?: string | null;
  low_confidence_override?: { by: string; reason: string } | null;
}
export interface PriceRequest {
  id: number; valuation_id: string; status: "pending" | "approved" | "rejected" | "cancelled"; recommended_price_aud: number; requested_price_aud: number;
  deviation_pct: number; reason: string; note?: string | null; requested_by?: string | null; decided_by?: string | null; decided_at?: string | null;
  decision_reason?: string | null; created_at?: string | null; url?: string | null; company_name?: string | null;
}
export type FinalState = "none" | "valid" | "expired" | "stale";
export interface TokView {
  valuation_status?: string; confidence: Conf; proposal: Tokenisation | null; final: ValuationFinal | null; final_state: FinalState;
  pending: PriceRequest | null; can_finalise: boolean; blockers: string[];
  rules: { free_band_pct: number; hard_min_ratio: number; hard_max_ratio: number; validity_days: number; min_confidence: string; default_price_by_stage: Record<string, number> };
}
export interface V5 { eval: Eval5 | null; tri: Tri5 | null }

/* ---------------- normaliser ---------------- */
type Obj = Record<string, unknown>;
const isObj = (x: unknown): x is Obj => !!x && typeof x === "object" && !Array.isArray(x);
const num = (x: unknown, d = 0): number => { const n = Number(x); return x != null && x !== "" && Number.isFinite(n) ? n : d; };
const numOrNull = (x: unknown): number | null => (x == null || x === "" ? null : Number.isFinite(Number(x)) ? Number(x) : null);
const arr = <T = unknown>(x: unknown): T[] => (Array.isArray(x) ? (x as T[]) : []);
const str = (x: unknown, d = ""): string => (typeof x === "string" ? x : d);
const lvl = (x: unknown): Level => Math.max(0, Math.min(4, Math.round(num(x)))) as Level;
const conf = (x: unknown): Conf => (x === "high" || x === "low" ? x : "medium");
const pair = (x: unknown): [number, number] | null => { const a = arr<number>(x); return a.length === 2 && a.every((v) => Number.isFinite(Number(v))) ? [Number(a[0]), Number(a[1])] : null; };
const UNIT: Record<string, Unit> = { AUD: "aud", "%": "pct", count: "count", months: "months", x: "x", rating: "rating", rank: "rank" };

function readSub(x: Obj): SubMetric {
  const mv = isObj(x.value) ? x.value : null;
  const b = arr<number>(x.benchmark);
  return {
    key: str(x.key), metric: str(x.metric), label: str(x.label) || undefined,
    value: mv ? numOrNull(mv.value) : numOrNull(x.value), unit: UNIT[str(mv?.unit)] ?? "count",
    score: numOrNull(x.score), weight: num(x.weight), level: lvl(mv?.level ?? 0),
    bench: b.length === 4 ? (b.map(Number) as SubMetric["bench"]) : null, lower_better: !!x.lower_is_better, status: str(x.status) || undefined,
    source: str(mv?.source) || null, source_url: str(mv?.source_url) || null, quote: str(mv?.quote) || null,
    note: str(x.note) || str(mv?.note) || null, as_of: str(mv?.as_of) || null,
  };
}
const dimOrder = (k: string) => { const i = DIMS5.indexOf(k as DimKey5); return i < 0 ? 99 : i; };

function readEval(v: Valuation): Eval5 | null {
  const svi = v.svi as unknown as Obj;
  const a = isObj(svi.analysis) ? svi.analysis : null;
  const wp = str(svi.weights_profile);
  if (!a && !wp.startsWith("v5")) return null;
  const src = a ?? {};
  const st = isObj(src.stage) ? src.stage : {};
  const detail = isObj(src.dimensions) ? src.dimensions : {};
  const dimsIn = isObj(svi.dimensions) ? svi.dimensions : {};
  const weights = isObj(svi.weights) ? svi.weights : {};
  const keys = Array.from(new Set([...Object.keys(dimsIn), ...Object.keys(detail)]));
  const dims: Dim5[] = keys.map((k) => {
    const s = isObj(dimsIn[k]) ? dimsIn[k] : {}, d = isObj(detail[k]) ? detail[k] : {};
    let w = num(weights[k] ?? d.weight);
    if (w > 1) w /= 100;
    return {
      key: k, label: str(d.label) || undefined, score: num(s.score ?? d.score), weight: w, coverage: num(d.coverage, 1), cap: numOrNull(d.cap) ?? undefined,
      level: num(d.level, 1), confidence: conf(d.confidence), status: str(d.status) || undefined, basis: str(s.basis ?? d.basis) || undefined,
      rationale: str(d.rationale) || str(s.rationale) || undefined, improve: arr<string>(d.improve), flags: arr<string>(d.flags),
      submetrics: arr(d.sub_metrics).filter(isObj).map(readSub),
    };
  }).sort((x, y) => dimOrder(x.key) - dimOrder(y.key));
  const metrics: Record<string, SubMetric> = {};
  if (isObj(src.metrics)) for (const [k, mv] of Object.entries(src.metrics)) if (isObj(mv)) metrics[k] = readSub({ key: k, metric: k, value: mv });
  const ms = isObj(src.market_sizing) ? src.market_sizing : null;
  const analysts = isObj(src.analysts) ? Object.entries(src.analysts).filter(([, r]) => isObj(r)).map(([name, r]) => {
    const o = r as Obj;
    return { name, model: str(o.model) || undefined, claims: numOrNull(o.claims) ?? arr(o.claims).length, dropped: numOrNull(o.dropped) ?? arr(o.dropped).length, searches: numOrNull(o.searches) ?? arr(o.searches).length, error: str(o.error) || null };
  }) : [];
  const ser = isObj(src.series) ? (src.series as unknown as Series) : null;
  return {
    version: str(src.version, "v5"),
    stage: { stage: (str(st.stage) || wp.split(":")[1] || "seed") as Stage, basis: str(st.basis, "default"), reasons: arr<string>(st.reasons), table_version: str(st.table_version) || undefined, conflict: !!st.conflict },
    sector: str(src.sector_key) || undefined, revenue_model: str(src.revenue_model) || undefined,
    index: num(svi.index), band: str(svi.band), confidence: conf(src.confidence), trust_share: num(src.trust_share),
    dims, metrics,
    market: ms ? {
      tam_aud: numOrNull(ms.tam_aud), sam_aud: numOrNull(ms.sam_aud), som_aud: pair(ms.som_aud_5y), cagr_pct: numOrNull(ms.cagr_pct),
      target_customer: str(ms.target_customer) || undefined, customers: numOrNull(ms.target_customers), customers_source: str(ms.target_customers_source) || undefined,
      price_aud: numOrNull(ms.annual_price_aud), price_source: str(ms.annual_price_source) || undefined, tam_source_url: str(ms.tam_source_url) || undefined,
      tam_quote: str(ms.tam_quote) || undefined, cagr_source_url: str(ms.cagr_source_url) || undefined, som_share: pair(ms.som_share), source_tier: num(ms.source_tier), warnings: arr<string>(ms.warnings),
    } : null,
    powers: arr(src.powers).filter(isObj).map((p) => {
      const ev = arr(p.evidence).filter(isObj)[0];
      return { key: str(p.key), label: str(p.label) || undefined, level: Math.max(0, Math.min(3, num(p.level))) as Power["level"], points: num(p.points), weight: num(p.weight), cap: num(p.level_cap, 3), quote: ev ? str(ev.quote) || null : null, source_url: ev ? str(ev.source_url) || null : null, note: str(p.note) || undefined, computed: str(p.key) === "competition" };
    }),
    cohorts: arr(src.cohorts).filter(isObj).map((c) => ({ label: str(c.label), pts: arr(c.pts).map((x) => numOrNull(x)) })),
    series: ser && Array.isArray(ser.months) ? ser : null,
    top_raise: arr<string>(src.top_improvements).filter((x) => typeof x === "string"),
    flags: arr(src.flags).filter(isObj).map((f) => ({ code: str(f.code), severity: (["info", "warning", "high"].includes(str(f.severity)) ? str(f.severity) : "warning") as Flag["severity"], message: str(f.message), action: str(f.action) || undefined })),
    dropped: arr(src.dropped).map((x) => (typeof x === "string" ? x : isObj(x) ? `${str(x.metric)}: ${str(x.reason)}` : "")).filter(Boolean),
    analysts, lookups: isObj(src.lookups) ? src.lookups : {},
    docs: arr(src.documents).filter(isObj).map((d) => ({ doc_id: str(d.doc_id), kind: str(d.kind), filename: str(d.filename), sha256: str(d.sha256) })),
  };
}

function readTokenisation(tk: unknown): Tokenisation | null {
  if (!isObj(tk)) return null;
  return {
    pre_money_aud: num(tk.pre_money_aud), low_aud: num(tk.low_aud), high_aud: num(tk.high_aud), stage: str(tk.stage), basis: str(tk.basis, "new_company"),
    fd_shares_existing: numOrNull(tk.fd_shares_existing), default_price_aud: num(tk.default_price_for_stage_aud, 1),
    recommended_price_aud: num(tk.recommended_price_per_share_aud ?? tk.default_price_for_stage_aud, 1), total_shares: num(tk.total_shares),
    offer_price_low_aud: num(tk.offer_price_low_aud), offer_price_high_aud: num(tk.offer_price_high_aud),
    raise_aud: num(tk.raise_aud), new_shares: num(tk.new_shares), post_money_aud: num(tk.post_money_aud), dilution_pct: num(tk.dilution_pct),
  };
}

function readTri(v: Valuation): Tri5 | null {
  const svi = v.svi as unknown as Obj;
  const t = isObj(svi.triangulation) ? svi.triangulation : null;
  if (!t || !/^v5/.test(str(t.version))) return null;
  const methods: Method5[] = arr(t.methods).filter(isObj).map((m) => {
    const notes = arr<string>(m.notes);
    const w = num(m.weight);
    return {
      method: str(m.method), label: str(m.label), value_aud: num(m.value_aud), low_aud: num(m.low_aud), high_aud: num(m.high_aud), weight: w, raw_weight: numOrNull(m.raw_weight) ?? undefined,
      inputs: isObj(m.inputs) ? m.inputs : {}, sources: arr<string>(m.sources), notes, checks: arr<Check>(m.checks),
      excluded_reason: w > 0 ? null : notes.slice().reverse().find((n) => /^not used/i.test(n)) ?? null,
      uses_projections: PROJECTION_METHODS.includes(str(m.method)) && (isObj(m.inputs) ? m.inputs.projection_based !== false : true),
    };
  });
  const uncapped = (method: string) => { const m = methods.find((x) => x.method === method); const r = m && isObj(m.inputs.result) ? m.inputs.result : null; return r ? numOrNull(r.uncapped_value_aud) : null; };
  let field: FieldBar[] = arr(t.football_field).filter(isObj).map((b) => ({
    method: str(b.method), label: str(b.label), low_aud: num(b.low_aud), mid_aud: num(b.mid_aud), high_aud: num(b.high_aud), weight: num(b.weight),
    excluded_reason: str(b.reason) || null, uses_projections: !!b.projection_based, uncapped_mid_aud: uncapped(str(b.method)),
  }));
  if (!field.length) field = methods.map((m) => ({ method: m.method, label: m.label, low_aud: m.low_aud, mid_aud: m.value_aud, high_aud: m.high_aud, weight: m.weight, excluded_reason: m.excluded_reason, uses_projections: m.uses_projections }));
  const st = isObj(t.stage) ? t.stage : null;
  const wp = isObj(t.without_projections) ? t.without_projections : null;
  const pj = isObj(t.projections) ? t.projections : null;
  return {
    version: str(t.version), value_aud: num(t.value_aud), low_aud: num(t.low_aud), high_aud: num(t.high_aud), confidence: conf(t.confidence),
    confidence_reasons: arr<string>(t.confidence_reasons), methods, field,
    stage_class: str(t.valuation_class) || st ? { cls: str(t.valuation_class) || str(st?.stage), stage: str(st?.stage) || undefined, reasons: arr<string>(st?.reasons) } : null,
    tokenisation: readTokenisation(t.tokenisation), params_version: str(t.params_version) || undefined, market_dataset: str(t.market_dataset) || undefined,
    uses_projections: !!pj || field.some((b) => b.uses_projections && b.weight > 0), projection_label: pj ? str(pj.label) || null : null,
    without_projections_aud: wp ? numOrNull(wp.value_aud) : null,
  };
}

/** v5 view of a valuation, or null when it has none (flag off / an older report). */
export function readV5(v: Valuation | null | undefined): V5 | null {
  if (!v || !v.svi) return null;
  const e = readEval(v), t = readTri(v);
  if (!e && !t) return null;
  return { eval: e, tri: t };
}

export function readFinal(f: unknown): ValuationFinal | null {
  if (!isObj(f)) return null;
  return {
    pre_money_aud: num(f.pre_money_aud), low_aud: num(f.low_aud), high_aud: num(f.high_aud), stage: str(f.stage), confidence: conf(f.confidence),
    recommended_price_aud: num(f.recommended_price_per_share_aud), price_per_share_aud: num(f.price_per_share_aud), deviation_pct: num(f.price_deviation_pct),
    note: str(f.price_note) || null, reason: str(f.price_reason) || null, approved_by: str(f.price_approved_by) || null,
    total_shares: num(f.total_shares), fd_shares_existing: numOrNull(f.fd_shares_existing), offer_price_low_aud: num(f.offer_price_low_aud), offer_price_high_aud: num(f.offer_price_high_aud),
    based_on_projections: !!f.based_on_projections, report_hash: str(f.report_hash) || null, params_version: str(f.params_version) || undefined,
    finalised_by: str(f.finalised_by) || null, finalised_at: str(f.finalised_at) || null, valid_until: str(f.valid_until) || null,
    low_confidence_override: isObj(f.low_confidence_override) ? { by: str(f.low_confidence_override.by), reason: str(f.low_confidence_override.reason) } : null,
  };
}
export function readPriceRequest(r: unknown): PriceRequest | null {
  if (!isObj(r)) return null;
  return {
    id: num(r.id), valuation_id: str(r.valuation_id), status: (str(r.status, "pending") as PriceRequest["status"]), recommended_price_aud: num(r.recommended_price_aud),
    requested_price_aud: num(r.requested_price_aud), deviation_pct: num(r.deviation_pct), reason: str(r.reason), note: str(r.note) || null,
    requested_by: str(r.requested_by) || null, decided_by: str(r.decided_by) || null, decided_at: str(r.decided_at) || null, decision_reason: str(r.decision_reason) || null,
    created_at: str(r.created_at) || null, url: str(r.url) || null, company_name: str(r.company_name) || null,
  };
}
/** GET /v1/studio/valuations/{vid}/tokenisation → view model. */
export function readTok(x: unknown): TokView | null {
  if (!isObj(x)) return null;
  const r = isObj(x.rules) ? x.rules : {};
  const fs = str(x.final_state, "none");
  return {
    valuation_status: str(x.valuation_status) || undefined, confidence: conf(x.confidence), proposal: readTokenisation(x.proposal), final: readFinal(x.final),
    final_state: (["none", "valid", "expired", "stale"].includes(fs) ? fs : "none") as FinalState, pending: readPriceRequest(x.pending_request),
    can_finalise: x.can_finalise !== false, blockers: arr<string>(x.blockers),
    rules: {
      free_band_pct: num(r.free_band_pct, 20), hard_min_ratio: num(r.hard_min_ratio, 0.2), hard_max_ratio: num(r.hard_max_ratio, 5), validity_days: num(r.validity_days, 90),
      min_confidence: str(r.min_confidence, "medium"), default_price_by_stage: (isObj(r.default_price_by_stage) ? r.default_price_by_stage : STAGE_PRICE) as Record<string, number>,
    },
  };
}

/* ---------------- stage-dependent defaults (DECISIONS-V5 #5, #7; the server's `rules` win when present) ---------------- */
export const STAGE_PRICE: Record<string, number> = { idea: 0.1, "pre-seed": 0.1, seed: 0.25, "series-a": 1, growth: 1 };
export const stageKey = (s: string) => s.replace("_", "-").replace("profitable-sme", "growth");
