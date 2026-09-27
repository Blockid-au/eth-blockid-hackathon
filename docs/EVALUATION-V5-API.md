# Evaluation v5 — API and result shapes (backend contract for the UI and the valuation engine)

Status: implemented behind `VALUATION_V5=1` (default **off**). With the flag off nothing below appears: results,
stored JSON and report hashes are exactly v4. Plan: [PLAN-EVALUATION-V5.md](PLAN-EVALUATION-V5.md); owner decisions:
[DECISIONS-V5.md](DECISIONS-V5.md).

Code map

| Piece | File |
|---|---|
| Stage rules, stage profiles (weights, benchmarks, AU round medians, share price) | `agents/src/blockid_agents/tools/stage.py` |
| Deterministic v5 evaluator (sub-metrics, dimensions, levels, confidence, "what would raise this score") | `tools/evaluation.py` |
| v5 index / weights by stage (`WEIGHTS_V5`, `score_v5`, `apply_v5`, `recompute_v5`) | `tools/svi.py` |
| Metric maths (growth, CMGR, NRR/GRR, burn multiple, payback, LTV/CAC, runway) | `tools/metrics_calc.py` |
| Metrics CSV parser (template + Stripe / Baremetrics / ChartMogul aliases) + forensics | `tools/csv_metrics.py` |
| Anti-gaming checks | `tools/consistency.py` |
| Free lookups (Tranco, Wayback CDX, iTunes Search, ABS counts table, ABN Lookup), 7-day cache | `tools/lookups.py`, `agents/data/abs_business_counts_2025.csv` |
| Analysts (LLM extracts cited claims only; code verifies) | `agents/traction.py`, `agents/market_size.py`, `agents/moat.py`, `agents/retention.py`, `agents/deck_reader.py`, shared `agents/analysts.py` |
| Graph step `analysts` (parallel, between `market` and `svi`) | `graph.py` |
| Founder inputs v2, documents, re-score, metric verification, KPI revaluation | `studio/evaluation.py` (router), `studio/schema.sql` |

## 1. Where the data lives

`GET /v1/studio/valuations/{id}` is unchanged in shape. v5 adds, **inside `svi`** (so it is covered by the anchored
report hash):

```jsonc
svi: {
  index, band, dimensions, weights, valuation_*, method, needs_human_review, report_sha256, narrative, triangulation,
  "weights_profile": "v5:seed",          // only on v5 reports
  "analysis": Analysis                   // only on v5 reports (see §2)
}
```

`svi.dimensions` on a v5 report has the **9 v5 keys** (each a `DimensionScore {score, basis, rationale, sources}`, as
before, so existing components keep working): `founder_quality, traction, market, moat, retention, efficiency,
product_strength, investment_readiness, trust_verification`. `svi.weights` = the stage column (sums to 1).
`index = round(Σ weights[k] × dimensions[k].score, 2)` — same arithmetic as v4.

A v4 report has no `analysis` / `weights_profile` keys at all: the UI must treat `svi.analysis` as optional and
fall back to the current v4 rendering.

## 2. `Analysis` (schemas.py)

```jsonc
Analysis {
  version: "v5",
  stage: StageDecision,
  stage_profile: {...},          // tools/stage.profile_snapshot(): the exact weights / benchmarks used (for /verify)
  sector_key: "saas" | "marketplace" | "fintech" | "consumer" | "enterprise" | "services" | "hardware" | "ai",
  revenue_model: "subscription" | "transactional" | "marketplace" | "services" | "hardware" | "other" | "",
  dimensions: { [key]: DimensionDetail },   // all 9 keys
  metrics: { [metric]: MetricValue },       // resolved inputs (after consistency rules)
  claims: VerifiedClaim[],                  // every verified claim from the analysts / deck
  dropped: string[],                        // claims rejected by verification, with the reason
  flags: ConsistencyFlag[],                 // anti-gaming / consistency flags (admin "consistency" panel)
  powers: MoatPower[],                      // 7-Powers grid (6 powers + competition)
  market_sizing: MarketSizing | null,       // TAM / SAM / SOM
  lookups: {tranco?, wayback?, app_store?, abs?, abn?},  // free public lookups (cached 7 days)
  trust_share: 0..1,                        // share of scored weight at level >= 2
  confidence: "high" | "medium" | "low",   // overall evaluation confidence
  top_improvements: string[],               // "Top 3 things that would raise this score" (Overview tab)
  documents: [{doc_id, kind, filename, sha256}],
  analysts: {traction|market_size|moat|retention|deck: {model, claims, dropped, searches, error}}
}

StageDecision {
  stage: "idea"|"pre-seed"|"seed"|"series-a"|"growth",
  basis: "listing"|"round"|"revenue"|"raised"|"hint"|"human"|"default",
  reasons: string[],                 // plain sentences, first = the deciding rule
  sources: string[], signals: {round?, revenue?, raised?, hint?, listing?}, conflict: bool, table_version
}

DimensionDetail {
  key, label, weight,
  score,                 // used in the index
  score_raw,             // weighted mean of scored sub-metrics (before the coverage cap), null if none
  coverage: 0..1, cap,   // cap = 40 + 60 × coverage (code-computed dims); coverage 0 -> score 40 "Not enough data"
  level: 0..4,           // weighted mean verification level
  confidence: "high"|"medium"|"low",
  status: "scored"|"not_enough_data"|"not_applicable"|"ai_suggested"|"team_report"|"human",
  basis,                 // DimensionScore basis ("computed" for traction/market/moat/retention/efficiency/trust)
  sub_metrics: SubMetric[], evidence: VerifiedClaim[], flags: string[], improve: string[], rationale
}

SubMetric {
  key: "T1".."T4" | "M1".."M5" | "R1".."R5" | "E1".."E6" | "Mo:<power>",
  metric, label, weight,
  value: MetricValue | null,
  benchmark: [P25, P50, P75, P90] | null,   // for THIS stage + sector; lower_is_better rows are listed worst -> best
  lower_is_better: bool,
  score_raw: 0..100 | null,  // 25 at P25, 50 at P50, 75 at P75, 90 at P90 (piecewise-linear; log for money/counts)
  score: 0..100 | null,      // after the level shrink: 50 + (raw − 50) × {L1 .6, L2 .8, L3 .9, L4 1}
  status: "scored"|"missing"|"not_benchmarked"|"not_applicable"|"capped", note
}

MetricValue { value, unit: "AUD"|"%"|"count"|"months"|"x"|"rating"|"rank", as_of: "YYYY-MM",
              level: 0..4, source: "self_reported"|"csv"|"deck"|"site"|"cited"|"kpi"|"registry"|"lookup"|
              "computed"|"connector"|"competitors", source_url, quote, note }

VerifiedClaim { metric, value, unit, period, as_of, value_aud, source_url, quote,
                subject: "company"|"market"|"competitor", level, analyst }

ConsistencyFlag { code, severity: "info"|"warning"|"high", message, metrics: string[],
                  action: "lower_used"|"capped"|"review"|"" }

MoatPower { key: network_effects|switching_costs|ip_data|scale|brand|counter_positioning|competition, label, weight,
            level: 0..3, level_cap, points (0/35/70/100; competition computed 0..100), evidence: VerifiedClaim[], note }

MarketSizing { sam_aud, target_customer, target_customers, target_customers_source ("abs:<div>:<band>" | URL |
               "self_reported"), annual_price_aud, annual_price_source, tam_aud, tam_source_url, tam_quote, cagr_pct,
               cagr_source_url, som_share: [lo, hi], som_aud_5y: [lo, hi], source_tier (1 gov … 4 blog, 0 unknown),
               warnings }
```

Verification level badges (EN): L0 Missing · L1 Self-reported · L2 Document-backed · L3 Publicly corroborated ·
L4 Connected (`tools/stage.LEVEL_LABELS`).

Sub-metrics per dimension (keys are stable):

| Dimension | Sub-metrics (weight) |
|---|---|
| traction | T1 `arr_aud` revenue scale (.30) · T2 `yoy_growth_pct` or `cmgr_pct` (.40) · T3 `paying_customers` / `active_users` (.15) · T4 `backlog_ratio` or pre-seed signals `pilots_paid`/`lois`/`waitlist` (.15) |
| market | M1 `sam_aud` (.40) · M2 `tam_aud` (.15) · M3 `market_cagr_pct` (.25) · M4 `som_realism` (.10) · M5 `source_tier` (.10) |
| moat | `Mo:network_effects` .20 · `Mo:switching_costs` .20 · `Mo:ip_data` .15 · `Mo:scale` .10 · `Mo:brand` .10 · `Mo:counter_positioning` .10 · `Mo:competition` .15 |
| retention | R1 `nrr_pct` (.30) · R2 `grr_pct` / logo retention (.25) · R3 `m3_retention_pct` / `dau_mau_pct` (.20) · R4 `review_rating` / `nps` (.15) · R5 `top_customer_share_pct` (.10) |
| efficiency | E1 `burn_multiple` (.30) · E2 `runway_months` (.25) · E3 `gross_margin_pct` (.25) · E4 `cac_payback_months` (.10) · E5 `ltv_cac` (.05) · E6 `rule_of_40` (.05, growth only) |

## 3. Endpoints (all under the Studio session; JSON)

| Method | Path | Who | Body → Response |
|---|---|---|---|
| POST | `/v1/studio/valuations` | user | `metrics` accepts the **v2** keys (`SelfReportedMetricsV2`, §3.1 of the plan) when `VALUATION_V5=1`; v1 keys always |
| GET | `/v1/studio/evaluation/config` | public | `{enabled, stages, table_version, weights_by_stage, benchmarks_by_stage, level_labels, dimension_labels, fields: [{key, group, unit, min_stage}], documents: {kinds, max_per_valuation, max_chars, csv_max_rows}, share_price_by_stage, au_round_medians}` — drives the wizard tabs and the benchmark bars |
| POST | `/v1/studio/evaluation/stage-preview` | user | `{metrics}` → `StageDecision` ("Looks like: Seed — change") |
| PUT | `/v1/studio/valuations/{id}/metrics` | owner / admin | `{metrics: SelfReportedMetricsV2}` → re-score (no web) → the valuation view. 409 once a company was created from the valuation |
| POST | `/v1/studio/valuations/{id}/documents` | owner / admin | `{kind: "deck"|"metrics_csv"|"financials", filename, sha256 (hex of the original bytes), text?: string (≤ 60k chars), rows?: string[][] or csv text (≤ 120 rows)}` → `{doc_id, kind, filename, sha256, parsed}`; max 5 per valuation; 409 when locked |
| GET | `/v1/studio/valuations/{id}/documents` | owner / admin | `[{doc_id, kind, filename, sha256, parsed, uploaded_by, created_at}]` (text is not returned) |
| DELETE | `/v1/studio/valuations/{id}/documents/{doc_id}` | owner / admin | `{deleted: true}` |
| POST | `/v1/studio/valuations/{id}/rescore` | owner / admin | `{}` → re-runs the deterministic v5 evaluation from stored evidence + typed metrics + documents (deck text extraction runs once per new deck: 1 LLM call, no web) → the valuation view (`svi.analysis` updated). 409 when locked |
| POST | `/v1/studio/valuations/{id}/metrics/verify` | admin | `{metric, level: 2|3, note}` → marks one input as verified (audited) and re-scores |
| POST | `/v1/admin/companies/{cid}/revalue-suggestion` | company admin / platform admin | `{}` → deterministic re-score from **approved KPI updates** (level L3 "disclosed"), stage re-evaluated → `{suggested_valuation_aud, previous_valuation_aud, stage, previous_stage, stage_changed, note, analysis_summary}`; nothing is applied — the admin then calls the existing `/revalue` with the number |

`parsed` for a metrics CSV: `{rows, months: ["2025-10", ...], series: {revenue_aud: [...], mrr_aud: [...], ...},
metrics: {yoy_growth_pct, cmgr_pct, nrr_pct, grr_pct, logo_churn_monthly_pct, burn_multiple, arr_aud, ...},
flags: ConsistencyFlag[], errors: ["row 7: revenue_aud is not a number", ...], mapped_headers: {...}}`.
For a deck: `{chars, facts: DeckFacts-verified claims (after /rescore)}`.

## 4. For the valuation engine (tools/valuation_methods.py, triangulate.py)

```python
from blockid_agents.tools import stage
d = stage.classify_stage(stage.evidence_from_result(result))      # StageDecision
p = stage.profile(d.stage)          # .weights .bench .pre_money_aud .round_size_aud .stage_method_weight_with_others
stage.au_round_medians(d.stage)     # AU round size + pre-money P25/P50/P75 + basis/sources (AU_ROUND_ADJ = 0.5)
stage.recommended_share_price(d.stage)   # 0.10 / 0.10 / 0.25 / 1.00 / 1.00
stage.SELF_REPORTED_FACTOR          # 0.6 ; stage.LEVEL_SHRINK {0:0,1:.6,2:.8,3:.9,4:1}
# v5 dimension scores for the scorecard factor: svi["dimensions"][k]["score"] with svi["weights"] (stage column)
# per-metric evidence levels: svi["analysis"]["metrics"][m]["level"] (e.g. "arr_aud", "yoy_growth_pct", "nrr_pct",
# "gross_margin_pct") for the quality-adjusted multiple and its shrink.
```

Graph contract: when `VALUATION_V5=1`, the `analysts` step stores `state["analysis"]` (a partial `Analysis` with the
code-computed dimensions); the `svi` step runs the existing `valuation.score` and then `svi.apply_v5(...)`, which
merges the LLM / team dimensions, sets the v5 weights, index, band, `analysis`, `weights_profile` and recomputes the
report hash; the gate re-applies v5 after overrides. Anyone re-scoring a stored v5 result (team score, overrides,
rescore) calls `svi.apply_v5(svi_dict, analysis_dict, qualitative_dict)` after `svi.score`.

## 5. Implementation notes (27 Sep 2026)

- **Cost per evaluation (paid fallback, worst case)**: 4 analyst `extract_json` calls, each digest ≤ 14k chars
  (~4.5k tokens in, ≤ 1.5k out) on DeepInfra DeepSeek-V4-Flash (US$0.09 / 0.18 per M) ≈ **US$0.0027**; a deck read
  (≤ 60k chars, once per deck, only on `/rescore`) ≈ US$0.002; conditional analyst searches (typically 1–2, paid Brave
  capped by `ANALYST_PAID_SEARCH_MAX=2`) ≈ US$0.005 each → **≈ US$0.013 typical, ≤ US$0.015 worst** extra; US$0 on
  the free SambaNova / bridge path. Re-scores (typed numbers, CSV, admin verification, KPI suggestion) cost US$0.
- **Lookups cache**: Tranco / Wayback / iTunes / ABN results are cached 7 days in the evidence store's cache table
  (key `lookup:<kind>:<arg>`, same store as the 72 h search cache) instead of a new `studio.lookup_cache` table.
  `LOOKUPS_OFFLINE=1` disables network lookups; ABN Lookup needs `ABN_LOOKUP_GUID` (free registration).
- **ABS table**: `agents/data/abs_business_counts_2025.csv` = ABS 8165.0 data cube 2 (June 2025, released
  16 Dec 2025), businesses operating at end of FY by ANZSIC division and class × employment size, summed over states
  (ABS perturbation: division sums differ from the published total by < 0.01 %).
- **Stage in the valuation**: the valuation engine reads `svi.analysis.stage` (StageDecision) when present.
- **Team score blend** (`valuation.apply_team_score`, called by `studio/hr_store.py`) and admin overrides must call
  `agents.analysts.rescore_v5(result, svi_dict=..., qualitative=...)` after `svi.score` when the stored svi has an
  `analysis`; the graph gate already does this.
