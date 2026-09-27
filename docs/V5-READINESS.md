# Evaluation + valuation v5 — readiness to switch on (27 Sep 2026)

Scope: the v5 evaluation and valuation shipped behind `VALUATION_V5` (off) in fef89c4, plus the readiness work in this
change (not deployed, not committed). Owner criteria: [DECISIONS-V5.md](DECISIONS-V5.md) #10. Numbers:
[valuation-reference.md](valuation-reference.md) "Valuation v5 backtest".

## 1. Checklist

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Test suite passes with the flag **off and on** | ✅ 552 passed / 1 skipped in each mode | `VALUATION_V5=0 pytest` and `VALUATION_V5=1 pytest` (throwaway Postgres). Tests whose expectations differ branch on `conftest.v5_on()`: v4 when off, v5 when on; the flag-off contract test pins the flag off in both runs |
| 2 | `/verify` recomputes v5 **index and band** (not only the value) | ✅ | `studio/verify.recompute` → `recompute_index_v5`: sub-metrics rebuilt (`tools/svi.recompute_v5`, now also `trust_verification` from the verification levels), weights must equal `analysis.stage_profile.weights`, `svi.weights` and the published stage column; `matches_report` gains `weights`, `dimensions`; tamper tests for index / band / weights / sub-metric / trust |
| 3 | Damodaran January 2026 industry table | ✅ | new dataset `market_data/2026-09-27.json` (20 industries: unlevered beta corrected for cash, EV/Sales, EV/EBITDA of positive-EBITDA firms, EBITDA and gross margin; global rows used, Aus/NZ/Canada rows kept for reference; 12 source files with URL + sha256, data date 5 Jan 2026). `2026-09-26` unchanged. With `industries_status: verified` the EBITDA multiple uses the "industry table" factor 0.6 — the 0.5 placeholder penalty and its note are gone |
| 4 | Stage bases calibrated: DCF / VC / scorecard not dropped as 3x outliers on typical cases | ✅ | params **v5.1** (below). Synthetic seed-good: First Chicago, VC, scorecard and stage all used (before: scorecard + stage only; First Chicago was 91x away, VC 4.7x). Series A-good: all five used. A5 / A6 still pass |
| 5 | No-own-price case (target ≤ 45 %) | ⚠️ live ✅ 28.1 %, offline ❌ 69.4 % (was 78.4 %) | offline: 3 fixtures carry no revenue or funding evidence at all (−90 % whatever the method); on the 5 with revenue evidence 42.0 %. Changes: cited revenue now reaches v5 traction; listed-peer multiples blended by size; funding-implied stage benchmark; AU stage table |
| 6 | Front-end ↔ backend contracts | ✅ | metrics CSV `rows` accepts the CSV text (what the UI sends) or `string[][]`; `parsed.months/series` already matched (`revenue_aud`, `mrr_aud`, `customers`); `analysis.cohorts` not produced → UI hides the chart (already guarded); finalise takes optional `planned_raise_aud` (stored with new shares, post-money, dilution; kept through the four-eyes request; column `valuation_price_requests.planned_raise_aud`); v5 progress steps `analysts` / `valuation_methods` labelled EN/VI; web typecheck clean |
| 7 | Gateway routing + precedents search | ✅ | `ai_gateway.SCHEMA_PROFILES`: `IndustryPick`, `DealClaims` → extract_json, `StartupFactors` → reason_score. `tools/search`: kind `precedents` (`VALUATION_QUERY_PLAN`, after the analysts' kinds: 7 + 4 + 1 = 12 = production budget), run once by the valuation agent for Series A / growth; policy allows `web_search`/`fetch_url`/`store_evidence` for `valuation_methods` (chain tools still forbidden) |
| 8 | Live backtest | ✅ | reference companies: median **17.0 %** (7 of 8; Linktree blocked by robots.txt), in range 6/7; SMEs as if private: **14.3 %** live / 13.1 % offline, in range 3/5; spend **US$0.00** (free tiers) |
| 9 | All 14 on-chain reports verify; flag-off hashes unchanged | ✅ | `test_verify_onchain` (flag 0 and 1), `test_verify_snapshots`; nothing in the flag-off path changed (the only shared-code edits are v5-gated or additive: a nullable column, a new search kind that only v5 runs, schema routing) |

Owner criteria (#10): live median ≤ 25 % ✅ · SMEs ≤ 30 % ✅ · 100 % of new reports recompute ✅ (A5 + index/band)
· all 14 on-chain reports verify ✅.

## 2. Calibration (params v5.1, market dataset 2026-09-27)

`v5` is frozen; `v5.1` only adds keys (`test_params_v5_frozen_and_v5_1_adds_calibration_only`). Every number a method
uses is stored in its inputs, so reports made with either version recompute exactly.

| Rule | v5 (fef89c4) | v5.1 | Source / reasoning |
|---|---|---|---|
| VC method target | 20–30x money multiple, retention 1.0 | target IRR = the class's venture rate (seed 50 %, A 40 %, growth 30 %, pre-seed 60 %) ± 10 pp over the projection years; retention to exit seed 0.63, A 0.77, growth 0.90, idea/pre-seed 0.51 | Sahlman, *The Venture Capital Method*, HBS 9-288-006 (seed 50–70 %, first stage 40–60 %, second 35–50 %); [Carta dilution medians 2025](https://carta.com/data/linkedin-dilution-by-venture-round-medians/) (software: seed 19.5 %, A 18 %, B 14 %, C 10 %) |
| Venture-rate DCF / First Chicago terminal | Gordon growth at the venture rate | exit at listed peers' EV/EBITDA (Damodaran) less the 25 % DLOM | a 30–60 % rate is a return to exit, not a perpetual cost of capital; Gordon at 50 % gave near-zero values (seed First Chicago A$0.14M vs scorecard A$13M) |
| Stage benchmark (`stage_scorecard`) | v3 placeholder range (seed 2 / 5 / 10M) | AU stage pre-money P25/P50/P75 (tools/stage, owner decision 4), or funding raised × 3.5 / 4.5 / 6 when a figure is known (cited > self-reported > website) | post-money ≈ capital raised ÷ (1.6 × last-round dilution 10–18 %); the 1.6 (cumulative capital ≈ 1.6 × last round when rounds step up ~2.5x) is a BlockID judgement |
| Revenue multiple | cited sector figure / default table as is | geometric blend with Damodaran EV/Sales (less DLOM), listed share 0 at ≤ A$10M revenue → 0.5 at ≥ A$1B; ≥ 3 comps untouched | listed aggregates describe listed-scale companies; small private companies trade on private multiples |
| EBITDA multiple | Damodaran/placeholder listed EV/EBITDA less DLOM | same size blend with the AU private transaction range for the size and sector | small listed and private businesses trade well below large-cap aggregates (Machinery 16.9x, Business services 14.1x). **Calibrated in-sample** on the 5 SMEs |
| Scorecard / RFS base | AU = ½ US median (owner decision 4) | unchanged | no AU pre-money medians found in free sources |

Synthetic cases (scripts/fixtures/valuation-v5-cases.json, SYNTHETIC): seed-good A$10.7M (VC 8.7M, First Chicago 5.7M,
scorecard 13.0M, stage 13.2M; revenue multiple 3.0M still excluded — 7.4x listed-peer EV/Sales on A$400k ARR is
meaningless at seed, base weight 0.4); series A-good A$43.3M (revenue 29.7M, First Chicago 46.8M, VC 69.9M, scorecard
39.1M, stage 39.6M). Hockey-stick files keep their projection weight ≤ 0.4 × base; broken files run no projection
method.

## 3. Remaining risks

1. **Industry pick drives SME multiples.** Live, the model mapped Prime Financial (accounting) to *fintech* (+120 %)
   and Pureprofile to *information services* (+76 %). The pick is AI-suggested and shown at the gate; reviewers must
   confirm it (admin assumption `industry`). A deterministic cross-check against the keyword map could flag
   disagreements (not done).
2. **In-sample size calibration.** The EBITDA/revenue size blend was fitted on the same 5 SMEs it is judged on; the
   first 20–30 real SME valuations should be compared with the gate reviewer's view before trusting the ±range.
3. **No-own-price offline 69 %.** Growth companies with no revenue or funding found can only be valued by the stage
   benchmark (tens to hundreds of millions): confidence is low and the report says so, but the number can be far off.
4. **Search availability.** Brave's monthly quota is exhausted; all live searches ran on the Claude bridge. Attach
   the Brave paid credit (owner decision 9) before switching on. Airtasker's market cap was found in one live run and
   not in the next (+10 % vs +54 %): listed-company market-cap discovery is not yet reliable.
5. **Model timeouts.** SambaNova DeepSeek timed out (60 s) on several analyst calls; the analysts degrade to "no
   claims" (lower coverage), the valuation still completes. Watch the gateway fallback rate after switch-on.
6. **Precedents are broker composites.** Verified deals are rarely found; the precedent method mostly uses cited AU
   ranges (factor 0.7). The new `precedents` search should raise that, but it has only been tested offline.
7. **Market parameters age.** Damodaran rows are January data; AU rf 5.385 % is from 26 Sep 2026. Refresh rf monthly
   (new dated file) and Damodaran each January.
8. **Backtest harness**: one live run hit "file is not a database" on a temporary cache file (re-run passed); not seen
   in the worker, which uses Postgres.

## 4. Before switching on

- Deploy with the schema migration (`ALTER TABLE studio.valuation_price_requests ADD COLUMN IF NOT EXISTS
  planned_raise_aud`) — applied automatically by `apply_schema` at start-up — and rebuild the web app.
- Attach the Brave credit; keep `SEARCH_MAX_QUERIES=12`.
- Keep `VALUATION_V5_REQUIRE_FINAL=0` for the first weeks (finals optional), and brief gate reviewers to confirm the
  stage, the **industry** and the startup ratings on every v5 report.
- CI: run the suite twice (`VALUATION_V5=0` and `=1`).

## 5. Recommendation

**Switch on `VALUATION_V5=1` for new valuations**, with the conditions in §4. The owner's acceptance criteria are met
(live median 17 %, SMEs 14 %, every v5 report recomputes including its index and band, all 14 on-chain reports verify,
flag-off behaviour unchanged), and the switch is reversible: turning the flag off returns to v4 for new valuations
while v5 reports keep verifying. Do not yet make finalising mandatory, and treat the no-own-price and industry-pick
risks (§3.1–3.3) as gate-review items rather than blockers.
