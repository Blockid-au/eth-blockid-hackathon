# Plan — Business evaluation v5: traction, market, moat, retention (27 Sep 2026)

Repo: `/home/dovanlong/blockid-eth-platform` · live: https://eth.blockid.au · status: **plan only, no code changed**.

Owner priorities, in order: **(1) management / founding team** (done: People Analyst + hr.blockid.au, 30% of the
score) → **(2) commercial traction** → **(3) market size** → **(4) competitive moat** → **(5) customer retention /
stickiness**. Each gets a dedicated analyst agent. Best quality at the lowest cost: free-tier-first routing, evidence
reuse, ≤ US$0.02 extra per evaluation. Every parameter (weights, benchmarks, valuation inputs) keys off one
**stage** value that is decided by evidence rules, and the same stage drives the valuation that prices the tokenised
shares.

Non-negotiable rules carried over from v3/v4 (docs/FACTS.md, docs/LLM-ROUTING.md):
- **The LLM never produces a number that is scored or valued.** It extracts typed claims with a verbatim quote and a
  source; code verifies the quote, converts units/FX, computes metrics, scores and the valuation.
- Every figure carries a provenance label and a verification level; self-reported is never shown as verified.
- `/verify` must still rebuild every old report (v1–v4) bit-for-bit; v5 adds a new formula version, never mutates old
  ones.
- Human gate unchanged: an admin approves the valuation before any issuance.

---

## 0. What exists today (read before building)

| Piece | File | Today | Gap for this plan |
|---|---|---|---|
| Graph | `agents/src/blockid_agents/graph.py` `build_site_valuation` | `read_site → profile → competitors → market → svi → narrative → gate` | No analyst steps for traction / market sizing / moat / retention |
| Site intake | `agents/site_intake.py` | ≤ 6 pages; `StartupProfile` (LLM) incl. `stage` = LLM "best judgement"; `apply_self_reported` | Stage is a guess, not evidence-based; metrics are 7 flat numbers |
| Competitors | `agents/competitors.py` | 1 search, ≤ 9 competitors, homepages, verified funding | No moat / competitive-position analysis beyond the list and funding bars |
| Research | `agents/research.py`, `agents/market_evidence.py` | market size/growth search, company revenue, anchors, comps, sector multiples (≤ 8 searches, 72 h cache) | Market size is prose in `MarketAnalysis.market_summary`; no TAM/SAM/SOM numbers, no bottom-up |
| Scoring | `tools/svi.py` (v4) | 7 dims: founder .30, product .15, market .15, revenue .15, growth .10, readiness .10, trust .05; revenue & growth computed from `Metrics`; the rest LLM-suggested (`QualitativeScores`) | Traction, moat and retention are not dimensions; market is an LLM opinion; benchmarks are "placeholder" (`STAGE_REVENUE_BENCHMARK`, `STAGE_PRE_REVENUE_RANGE`) |
| Valuation | `tools/triangulate.py` (v3) | anchor · revenue × multiple · stage × SVI factor (`0.5 + index/100`) | The multiple ignores growth, retention and margin; stage method is a flat range × a linear factor |
| Founder inputs | `schemas.SelfReportedMetrics`, `studio/routes.py` `ValuationBody.metrics`, `web/app/src/lib/selfReported.ts`, `NewWizard.tsx` `SelfReportedFields` | revenue TTM, YoY growth %, gross margin, customers, raised, runway, employees — all `self_reported` | No ARR/MRR history, churn, NRR, pipeline, usage, market inputs; no uploads; no verification levels |
| Report | `web/app/src/pages/Valuation.tsx` `Report` | grade, value, TeamCard, radar, contributions, self-reported table, methods, range, competitor bars, narrative, evidence | Single long page; no per-dimension drill-down or "what would raise this score" |
| Hash | `studio/report_hash.py` (`REPORT_KEYS = url, profile, competitors, market, svi, self_reported`), `tools/svi.report_hash` | Stored JSON is hashed as-is | New data must live inside `svi` (optional field, excluded when `None`) so old reports keep their hash |
| Company KPIs | `studio/updates.py`, `studio/update_draft.METRICS` | revenue, gross/net profit, cash, customers, headcount per period, approved + disclosed on-chain | Not fed back into the evaluation — this is the best "verified over time" traction source we already own |

---

## 1. New evaluation model (SVI v5)

### 1.1 Dimensions and weights

Nine dimensions. Team stays at **0.30** at every stage (owner decision). The owner's order (traction ≥ market ≥
moat ≥ retention) holds at every stage. Weights depend on the stage (§6) so a pre-seed company is not punished for
having no retention data, and a growth company is judged mostly on traction, retention and efficiency.

| Dimension (key) | Replaces | Idea / pre-seed | Seed | Series A | Growth (B+) | Computed by |
|---|---|---|---|---|---|---|
| `founder_quality` — team | same | **0.30** | **0.30** | **0.30** | **0.30** | People Analyst team score (`team_report`), else LLM suggestion capped at 50 |
| `traction` — commercial traction | `revenue_performance` + half of `growth_capability` | **0.16** | **0.18** | **0.20** | **0.20** | code, from Traction Analyst metrics |
| `market` — market size & timing | `market_attractiveness` | **0.15** | **0.15** | **0.13** | **0.12** | code, from Market Sizer TAM/SAM/SOM + growth |
| `moat` — competitive moat & position | part of `product_strength` | **0.12** | **0.12** | **0.12** | **0.12** | code rubric over Moat Analyst claims |
| `retention` — retention / stickiness | new | **0.07** | **0.09** | **0.10** | **0.12** | code, from Retention Analyst metrics |
| `efficiency` — capital efficiency & unit economics | runway half of `growth_capability` | 0.04 | 0.05 | 0.06 | 0.08 | code (burn multiple, runway, CAC payback, LTV/CAC, gross margin) |
| `product_strength` | same (narrowed: product live, technical risk) | 0.10 | 0.06 | 0.04 | 0.03 | LLM suggested (as today) |
| `investment_readiness` | same | 0.04 | 0.03 | 0.03 | 0.02 | LLM suggested (as today) |
| `trust_verification` | same, now mostly computed | 0.02 | 0.02 | 0.02 | 0.01 | code: share of scored inputs at level ≥ L2 (§4) |
| **Sum** | | 1.00 | 1.00 | 1.00 | 1.00 | |

Notes
- The scorecard method (Bill Payne) uses team 30 / opportunity size 25 / product 15 / competition 10 / sales & channels
  10 / funding need 5 / other 5 — our pre-seed column is the same shape, re-ordered to the owner's priorities
  (source in §9).
- `product_strength` at pre-seed (0.10) sits above retention because a pre-seed company has no retention data; it is
  the only exception to the priority order and is documented in the report ("at this stage, product evidence stands
  in for retention").
- Weights live in `tools/stage.py` `STAGE_PROFILES[stage].weights` and are recorded in `SVIResult.weights` as today, plus
  `SVIResult.weights_profile = "v5:<stage>"`. `WEIGHT_SETS` keeps `v4` and `v3` for `/verify`.

### 1.2 Sub-metrics per dimension (all computed by code)

Each dimension = weighted mean of the sub-metrics **that have data**, then shrunk by evidence level (§4.3) and capped
when coverage is thin. A sub-metric scores 0–100 against the stage benchmark: **50 at the stage median, 75 at the
top quartile, 90 at the top decile, 25 at the bottom quartile** (piecewise-linear between the table points, log scale
for money amounts). Missing sub-metrics are not zero — they drop out of the mean, and the dimension's **coverage**
(share of sub-metric weight with data) caps the dimension score: `cap = 40 + 60 × coverage` (no data at all → the
dimension is 40 = "unknown, below average", shown as "Not enough data").

**Traction (T)** — "is it selling, and how fast?"

| Sub-metric | Weight | Definition (code) | Preferred source |
|---|---|---|---|
| T1 revenue scale | 0.30 | ARR (recurring only — one-off services / implementation fees stripped; run-rate is not ARR) or revenue TTM, AUD, vs stage benchmark (log) | connector > CSV > deck > site/cited > typed |
| T2 growth | 0.40 | YoY growth of ARR/revenue; if < 12 months of history, CMGR over the last 3–6 months (MoM benchmark at pre-seed/seed, YC "slope"); pre-seed without revenue: CMGR of active users / waitlist | CSV / connector / KPI history > deck > typed |
| T3 customer base | 0.15 | paying customers (or active users for consumer) + notable logos verified on the site (case studies, "trusted by" with named logos) | site (verified quote) > CSV > typed |
| T4 forward signal | 0.15 | contracted bookings / backlog or qualified pipeline ÷ ARR; pre-seed: LOIs, paid pilots, waitlist | deck / typed (L1–L2 only; capped at 60 unless documented) |

Burn multiple is scored once, in Efficiency (no double counting).

Revenue model is detected (subscription / transactional / marketplace / services / hardware): for marketplaces T1 uses
**net revenue** (GMV × take rate) and T2 GMV growth is shown beside it; GMV is never used as revenue (existing rule).

**Market (M)** — "how big can this get, and is it growing?"

| Sub-metric | Weight | Definition (code) |
|---|---|---|
| M1 SAM (bottom-up) | 0.40 | `target customers in served geographies × annual price (ACV)`; both inputs quoted from sources (ABS counts / industry body / government registers; price from the company's pricing page or founder) |
| M2 TAM (top-down, cross-check) | 0.15 | cited market-size figure (analyst report / gov data), converted to AUD, dated; used only if the quote names the segment |
| M3 market growth | 0.25 | cited CAGR of the segment (verbatim) |
| M4 SOM realism | 0.10 | 5-year SOM implied = SAM × achievable share (stage table: 1–5%) vs current ARR — flags if current revenue already > 20% of SAM (SAM too small or mis-sized) |
| M5 source quality | 0.10 | government / statutory > industry association / listed-company filings > paid analyst report press release > blog / vendor PR (a lookup of domains in `config.MARKET_SOURCE_TIERS`) |

Rule: when bottom-up and top-down disagree by > 10×, M1 wins and the report shows both with a warning
("top-down figure covers a much wider market"). No figure without a quote → M1/M2 missing, not guessed.

**Moat (Mo)** — "why can't others take this?" (Hamilton Helmer's 7 Powers + NFX network effects)

| Power / signal | Weight | Observable evidence the analyst extracts (quote + URL) | Level cap without documents |
|---|---|---|---|
| Network effects | 0.20 | two-sided / multi-sided product, user-generated content, marketplace liquidity, "the more X the more Y" with numbers | 2 of 3 |
| Switching costs | 0.20 | integrations count, data migration, embedded workflows, multi-year contracts, API usage | 2 |
| Proprietary data / IP | 0.15 | granted patents (IP Australia / WIPO number), registered trade marks, proprietary datasets, licences | 3 (registry-verifiable) |
| Scale / cost advantage | 0.10 | unit-cost claims, infrastructure ownership, volume purchasing | 1 |
| Brand / reputation | 0.10 | review volume & rating, awards, press — also shared with Retention R4 | 2 |
| Counter-positioning / cornered resource / process | 0.10 | regulatory licences (AFSL, ACL, TGA), exclusive partnerships, unique talent | 3 if licence number verifiable |
| Competitive intensity (inverse) | 0.15 | computed from the competitor step: number of direct competitors, their verified funding vs the company's, presence of listed incumbents | computed |

Each power gets a level 0–3 (0 none, 1 claimed, 2 evidenced on public pages, 3 verified in a registry or document);
code maps levels to points (0/35/70/100) with the cap above; "claimed only by the founder" is level 1 at most.

**Retention (R)** — "do customers stay and spend more?"

| Sub-metric | Weight | Definition | Applies |
|---|---|---|---|
| R1 net revenue retention (NRR) | 0.30 | (start MRR of a cohort + expansion − contraction − churn) ÷ start MRR, trailing 12 months | B2B, Series A+ (seed if ≥ 12 months of data) |
| R2 gross revenue retention (GRR) / logo retention | 0.25 | GRR, else 1 − annual logo churn | B2B |
| R3 usage retention | 0.20 | month-3 / month-12 cohort retention, DAU/MAU for consumer apps | consumer, marketplace, PLG |
| R4 customer sentiment | 0.15 | review rating & count (App Store / Google Play / G2 / Capterra / Trustpilot / Product Hunt), NPS (typed or deck) | all |
| R5 concentration (inverse) | 0.10 | top-customer share of revenue (> 20% flag, > 50% high severity) | all with revenue |

Retention is benchmarked **by ACV band first, then stage** (SaaS Capital shows NRR/GRR depend more on ACV than on
stage): the NRR/GRR rows in §1.3 are shifted by `ACV_ADJ` — ACV < A$18k: −4 pts NRR / −2 GRR; A$18k–150k: 0;
> A$150k: +5 NRR / +4 GRR. Consumer / marketplace use R3 (cohort, DAU/MAU, supply-side GMV retention) instead of R1/R2.

Pre-seed without customers: R is "not applicable yet" (coverage 0 → capped 40, weight only 0.07).

**Efficiency (E)**: burn multiple (net burn ÷ net new ARR, Sacks bands), runway months, gross margin, CAC payback
months, LTV/CAC (shown, weighted low below Series A because 3:1 is a mature-company rule), Rule of 40 only at growth
stage (below ~A$15M ARR it is dominated by growth and unstable year to year). Replaces the runway half of today's
`growth_capability`.

### 1.3 Stage benchmarks (defaults; AUD; to be refreshed yearly in `tools/stage.py`, each row cites its source)

> Filled from the web research in §9. Values are **medians / top quartile** for venture-backed software unless a
> sector column says otherwise; a sector override table (`SECTOR_ADJ`) scales growth and margin thresholds for
> marketplace, fintech, consumer, hardware and services.

USD figures converted at the app's fixed FX (USD 1.50 AUD, `config.FX_TO_AUD`). Format: **P25 / P50 / P75 / P90**
(for "lower is better" metrics the order is worst → best). Source keys refer to §9. Rows marked *(set)* are
owner-set starting points without a direct source and are flagged `uncited` in `tools/stage.py` until calibration.

**B2B SaaS (default sector)**

| Metric | Idea / pre-seed | Seed | Series A | Growth (Series B+) | Sources |
|---|---|---|---|---|---|
| ARR / revenue (A$) | 0 / 15k / 60k / 150k *(set)* — team, market, story dominate | 90k / 450k / 750k / 1.5M | 1.5M / 3.0M / 6.0M / 9M | 7.5M / 15M / 40M / 100M | [S1][S5][S6][S7] |
| YoY growth % | n/a (use CMGR) | 40 / 75 / 150 / 250 | 40 / 100 / 200 / 250 | 30 / 75 / 100 / 125 | [S3][S4][S2][S8] |
| CMGR (MoM %, < 12 months data) | 5 / 10 / 20 / 30 | 5 / 10 / 15 / 20 | — | — | [S9][S5] (YC 5–7%/week = top decile) |
| NRR % (ACV A$18k–150k) | n/a | 90 / 100 / 110 / 120 (≥ 12 months data only) | 95 / 102 / 110 / 120 | 100 / 106 / 115 / 125 | [S2][S10][S11][S12] |
| GRR % | n/a | 80 / 85 / 90 / 95 | 85 / 90 / 93 / 95 | 88 / 91 / 95 / 97 | [S10][S2] |
| Monthly logo churn % (SMB) | n/a | 5 / 3.5 / 2 / 1.5 | 4 / 2.5 / 1.5 / 1 | 3 / 2 / 1.2 / 0.8 | [S13] |
| 6-month logo retention % (SMB SaaS) | — | 50 / 60 / 70 / 80 | — | — | [S14] |
| Burn multiple (×, lower better) | n/a (runway only) | 4 / 3 / 2 / 1.5 | 3 / 2 / 1.2 / 1 | 2 / 1.5 / 1 / 0.75 | [S15][S6] |
| CAC payback months (lower better) | n/a | *(shown only)* | 24 / 18 / 12 / 6 | 24 / 20 / 12 / 6 | [S2][S16] |
| Gross margin % | — | 50 / 65 / 72 / 80 | 55 / 68 / 75 / 82 | 60 / 70 / 78 / 85 | [S3][S17] |
| Runway months | 6 / 12 / 18 / 24 | 9 / 15 / 21 / 27 | 12 / 18 / 24 / 30 | 12 / 18 / 24 / 36 | [S2] |
| Pre-money for scorecard (A$, P25/P50/P75) | 1.5M / 3M / 6M *(set, AU)* | 4M / 8M / 15M *(set, AU)* | 20M / 40M / 72M | 80M / 200M / 500M *(set)* | [S6][S18] US medians × `AU_ROUND_ADJ` 0.5 until AU calibration |
| Pre-seed signals (count) | paid pilots 0 / 1 / 3 / 5; LOIs 0 / 2 / 5 / 10; waitlist 0 / 200 / 1k / 5k *(set)* | — | — | — | *(set)* |

**Sector overrides (`SECTOR_ADJ`)**

| Sector | What changes | Sources |
|---|---|---|
| Marketplace | T1 uses net revenue (GMV × take rate); take rate shown vs 5–30% band; R3 = supply-side GMV retention M12: P50 50%, P90 ≥ 100%; growth benchmarks on GMV × 1.0 | [S19][S20][S21] |
| Fintech | gross margin measured after pass-through payment costs (P50 50%, software-led P75 75%); balance-sheet lenders flagged "valued on a different model — admin review" | [S22] |
| Consumer app / subscription | T3 = MAU; R3 = DAU/MAU P50 20%, P75 40%, P90 50%; D30 25/30% good/great; 6-month retention 40/70% good/great (subscription), 25/45% (social); needs ≥ a few thousand users before scoring | [S14][S23][S24] |
| Enterprise (ACV > A$150k) | NRR +5, GRR +4, CAC payback benchmark +6 months | [S10][S16] |
| Services / hardware | growth benchmarks × 0.6, gross margin P50 35% / 40%, NRR not scored | *(set)* |
| AI-native | same scoring; valuation anchors / comps only from AI peers (AI rounds price very differently) | [S6] |

Growth-stage ARR above ~US$5–10M is a triangulation of T2D3 and High Alpha bands, not a single sourced figure; it is
marked as such in the table metadata.

### 1.4 How the scores map into the valuation (triangulation v4, deterministic)

The v3 blend stays (anchor · revenue × multiple · stage/scorecard). Three changes, each recorded in the method's
`inputs` so `/verify` recomputes them (`TRIANGULATION_VERSION = "v4"`, `recompute()` branches on `tri.version`):

1. **Quality-adjusted multiple** (revenue method). `multiple = base × adj`, with
   `adj = clamp(g × r × m, 0.5, 2.0)` from lookup tables in `config.MULTIPLE_ADJ`:
   - growth `g` by the company's YoY growth vs the stage table: bottom quartile 0.75 · median 1.0 · top quartile 1.30 ·
     top decile 1.55 (public-SaaS multiples are driven mostly by growth; §9);
   - retention `r` by NRR: < 90% 0.80 · 90–100% 0.92 · 100–110% 1.0 · 110–120% 1.12 · > 120% 1.25 (GRR if no NRR,
     shifted 10 points);
   - margin `m` by gross margin: < 40% 0.70 · 40–60% 0.85 · 60–75% 1.0 · > 75% 1.05 (skip when the base multiple is
     already sector-specific for low-margin sectors).
   Why these sizes: public software multiples by growth tier are 3.3× (< 15% NTM growth), 6.7× (15–22%) and 18.0×
   (> 22%) in Sep 2026 [S25], and private companies' growth rises from 15% to 50% as NRR goes from < 90% to > 130%
   [S10] — so growth and NRR are the right levers, but a private, often self-reported figure gets a much narrower
   band (0.5–2.0×) than the public spread. The base multiple itself is still re-pulled from sources on every
   valuation (search #6/#7), because the tiers moved from 9.7× to 18.0× within 2026 [S25].
   **Evidence shrink:** each factor moves toward 1.0 by the metric's verification level (same `LEVEL_SHRINK` as §4.2:
   L1 self-reported keeps 60% of the effect, L2 80%, L3 90%, L4 100%). Adjustment inputs + levels are stored in `method.inputs.adjust`.
   Use **ARR** (run-rate) instead of TTM revenue when revenue is recurring and ARR is at level ≥ L2; else TTM.
2. **Scorecard method** replaces "stage benchmark × SVI factor": `value = stage median pre-money × scorecard factor`,
   `factor = Σ_i w_i × (score_i / 50)` over the v5 dimensions (50 = the average company at that stage → 1.0×),
   clamped **0.4–2.0** (Payne's scorecard multiplies a regional median pre-money by a weighted "percent of average"
   factor [S26]). Low/high = stage P25/P75 × factor. For idea / pre-seed also compute a **Berkus** cross-check
   (5 elements × up to A$0.75M each — Berkus' US$0.5M caps at app FX [S27] — each element's share = the mapped
   dimension score / 100: idea→market, prototype→product, team→founder, relationships→moat, rollout→traction) and show
   it; it gets weight only when no other method exists. **Risk Factor Summation** [S28] is not a value method here;
   its 12 risk categories become the checklist the Narrative uses for "Key risks" (no numbers).
3. **Stage-aware method weights**: the stage method's weight alone stays 1.0; with other methods it is 0.1 at Series
   A+ (today) but **0.35 at idea/pre-seed and 0.2 at seed**, because at those stages revenue multiples are noisy.
   Outlier rule (> 5× away → 0) unchanged.

Confidence gets one more reason: "key traction/retention figures are self-reported" → cannot be `high` unless the
revenue used is at level ≥ L2.

**Link to share pricing.** Default issue price stays A$1.00/share (shares = approved valuation ÷ 1). Offerings
(`studio/offerings.py`) already default to the latest approved mark and flag > 20% above it; add: the offering pack
shows the valuation confidence and the evidence-level summary, and if the revenue used is L1 only, the pack warns
"price based on self-reported revenue". Revaluations (`/v1/admin/companies/{cid}/revalue`) gain an option to
**re-score from approved KPI updates** (§3.4) so the mark moves with disclosed, approved numbers using the same stage
profile.

---

## 2. Agents

All four analysts are new modules in `agents/src/blockid_agents/agents/`. They run as **one graph step
`analysts`** between `market` and `svi`, executed **in parallel** (ThreadPoolExecutor, like `cv_review.py`), each on
its own evidence window. Pattern for each: (a) plan ≤ 1 extra search, (b) build a compact keyword-windowed digest of
evidence **already stored** for this valuation (site pages, competitor pages, market pages, uploaded deck/CSV text),
(c) one `extract_json` call → typed claims with verbatim quotes, (d) code verifies quotes (reuse
`research.amount_in_quote`, `people.quote_in`), converts, computes metrics and the dimension score. No agent returns
a score.

| Agent (module) | Inputs | Extra searches (conditional) | Free non-LLM lookups | LLM calls (profile) | Output schema |
|---|---|---|---|---|---|
| **Traction Analyst** (`traction.py`) | site pages (customers, case studies, pricing, careers, press), company-financials pages, deck text, metrics CSV, typed metrics, KPI history | `traction`: `"<name>" customers OR "case study" OR partnership OR contract <year>` — only if the site shows < 3 named customers and no deck | Tranco rank of the domain (free daily list, cached), Wayback CDX snapshot count (site age, first seen), iTunes Search API (app rating count), careers page open roles (already crawled) | 1 × `TractionClaims` (`extract_json`) | `TractionAnalysis` |
| **Market Sizer** (`market_size.py`) | market-search pages (search #2), pricing page, deck market slide, typed target-customer count/price | `market_bottom_up`: `number of <target customer> <country> statistics` — only if the segment is not covered by the local ABS table and no count was found | **local ABS Counts of Australian Businesses table** (`agents/data/abs_business_counts_2025.csv`, ANZSIC division × employment/turnover size; 2.73M trading businesses, 994k employing [S29]) — the LLM only picks the ANZSIC division + size band with a quote describing the customer; code looks up the count, so AU B2B SMB sizing needs **no search** | 1 × `MarketSizeClaims` (`extract_json`) | `MarketSizing` (TAM/SAM/SOM computed) |
| **Moat & Competition Analyst** (`moat.py`) | site pages (technology, integrations, security, about), competitor list + funding + homepages, deck | `ip`: `"<name>" patent OR trademark site:ipaustralia.gov.au OR patents.google.com` — only if the site/deck mention patents or IP | integrations count from site; competitor funding totals (already verified); ABN Lookup web service (free GUID: entity status, registration date, business names [S30]) and ASIC company dataset (weekly, free [S31]) for AU entities — also feeds company age into §6 and `trust_verification` | 1 × `MoatClaims` (`extract_json`) | `MoatAnalysis` (level per power) |
| **Retention Analyst** (`retention.py`) | metrics CSV (cohorts / MRR movements), typed churn/NRR/GRR/NPS, deck, site testimonials ("customer since"), review pages | `reviews`: `"<name>" reviews G2 OR Capterra OR Trustpilot OR "App Store"` — only if the company has customers | iTunes Search API (rating, count), Google Play page fetch (rating, installs band) | 1 × `RetentionClaims` (`extract_json`) | `RetentionAnalysis` |

Plus one optional **Document Reader** step (in `analysts`, before the four) when a deck is uploaded: one
`long_context` or `extract_json` call → `DeckFacts` (claimed ARR, growth, customers, market size, round, use of funds,
each with the verbatim slide text). The four analysts read `DeckFacts`, not the raw deck, so the deck is paid once.

The existing `QualitativeScores` call shrinks to `product_strength`, `investment_readiness` and a fallback
`founder_quality` (when no team report) — `market_attractiveness` and `trust_verification` are no longer asked of the
LLM (net −2 dimensions in the one `reason_score` call, which the Narrative call then explains).

### 2.1 Search budget

`SEARCH_MAX_QUERIES` hard cap 8 → **12** (default 11). The four new kinds are appended to `tools/search.QUERY_PLAN`
**after** the valuation-critical ones, so a smaller budget drops analyst searches first:
`competitors, market, company, valuation, market_cap, comps, comps_named, traction, reviews, market_bottom_up, ip`.
Each is conditional (table above); typical run adds **2** searches, at most 4. Same 72 h search cache, same
`searches` log (report shows purpose "customers & contracts", "reviews", "number of target customers", "patents &
trade marks").

### 2.2 Model routing and cost per evaluation

Add to `ai_gateway.SCHEMA_PROFILES`: `TractionClaims`, `MarketSizeClaims`, `MoatClaims`, `RetentionClaims`,
`DeckFacts` → `extract_json` (deck > 30k tokens → `long_context` automatically). Production order for `extract_json`
stays free SambaNova first (DeepSeek-V3.1/V3.2, gpt-oss-120b), Claude bridge next, DeepInfra DeepSeek-V4-Flash last.
The 24 h result cache (`studio.ai_cache`) and the 72 h search cache apply unchanged.

Prompt budgets (enforced by a digest builder `tools/digest.py`, keyword windows like `research.fin_excerpts`):
≤ 14k chars in (~4.5k tokens) + ≤ 1.5k tokens out per analyst; deck ≤ 60k chars.

| Item | Calls | Free tier (SambaNova) | Worst case (DeepInfra V4-Flash US$0.09 / 0.18 per M tokens) |
|---|---|---|---|
| 4 analyst extractions | 4 | US$0 | 4 × (4.5k × 0.09 + 1.5k × 0.18)/1e6 ≈ **US$0.0027** |
| Deck reader (when uploaded) | 0–1 | US$0 | (19k × 0.09 + 2k × 0.18)/1e6 ≈ **US$0.0021** |
| Schema-repair retries (~10%) | 0.5 | US$0 | ≈ US$0.0003 |
| Extra searches | 2 (≤ 4) | Claude bridge `/search` (subscription, daily cap) or Brave free quota: US$0 | Brave paid ≈ US$0.005/query (assumed list price; confirm on the Brave plan before E2) → 2–4 × = **US$0.010–0.020** |
| Free lookups (Tranco, Wayback, iTunes, Play) | 3–4 HTTP | US$0 | US$0 |
| **Total extra** | ~5 LLM + 2 searches | **US$0** | **≈ US$0.015** typical, ≤ US$0.025 if all 4 searches + deck run on paid tiers |

To stay ≤ US$0.02 in the worst case: when the search provider that answers is paid, the planner caps analyst searches
at 2 (`ANALYST_PAID_SEARCH_MAX=2`), and IP / reviews lookups fall back to the free APIs. The ledger (`studio.ai_usage`)
records the analyst spend per valuation; `GET /v1/admin/ai/health` gains "cost per valuation (p50/p95)".

### 2.3 Caching and reuse

- **Evidence reuse first**: every analyst reads `deps.evidence.for_subject(...)` for the site, valuation and competitor
  subjects (same as `graph.site_evidence`) before searching; a search runs only if the digest lacks its keywords.
- **Cross-valuation reuse**: public lookups (Tranco, Wayback, iTunes/Play, IP Australia) are cached per domain /
  company for 7 days in a new `studio.lookup_cache(key, value jsonb, fetched_at)`.
- **Re-score without re-research**: adding numbers or documents after the report re-runs only the affected analyst's
  code path (and its extraction if a document was added) and the deterministic `svi` + triangulation — the same pattern
  as `valuation.apply_team_score` (no web, no narrative change). New function `valuation.rescore(result, patch)`.
- **Revaluation from KPI updates**: reuses the stored analysis and replaces only metrics that now have approved KPI
  history (level L3 "disclosed").

---

## 3. Data inputs

### 3.1 Founder form (all optional, grouped, stage-aware)

`schemas.SelfReportedMetrics` becomes **v2** (`extra="forbid"`, all `None` by default, same bounds style). v1 keys
stay valid (API backward compatible; `revenue_growth_yoy_pct` is kept but code prefers growth computed from two
revenue points). Each value may carry `as_of` (YYYY-MM) and `doc_ref` (an uploaded document id). Stored in
`studio.valuations.self_reported` as today.

| Group (wizard section) | Fields | Shown from stage |
|---|---|---|
| **Revenue & growth** | `revenue_ttm_aud`, `revenue_prev_ttm_aud`, `arr_aud`, `mrr_aud`, `mrr_6m_ago_aud`, `mrr_12m_ago_aud`, `revenue_model` (subscription / transactional / marketplace / services / hardware / other), `gmv_ttm_aud`, `take_rate_pct`, `gross_margin_pct` | seed+ (pre-seed: revenue only) |
| **Customers & pipeline** | `paying_customers`, `paying_customers_12m_ago`, `active_users_monthly`, `active_users_daily`, `waitlist`, `pilots_paid`, `lois`, `contracted_backlog_aud`, `qualified_pipeline_aud`, `top_customer_share_pct`, `public_logos[]` (names the company allows us to show) | all (pre-seed sees waitlist / pilots / LOIs first) |
| **Retention** | `logo_churn_monthly_pct`, `grr_pct`, `nrr_pct`, `m3_retention_pct`, `m12_retention_pct`, `nps` | seed+ |
| **Efficiency** | `cash_aud`, `burn_monthly_aud`, `net_new_arr_12m_aud`, `cac_aud`, `arpa_monthly_aud`, `raised_to_date_aud`, `runway_months` (computed if cash + burn given) | seed+ |
| **Market** | `target_customer` (text ≤ 120), `target_customer_count`, `target_count_source_url`, `annual_price_aud`, `geographies[]` | all |
| **Moat** | `patents[]` (number + office), `trademarks[]`, `licences[]` (type + number), `integrations_count`, `exclusive_contracts` (count), `moat_note` (≤ 500 chars, self-reported) | all |
| **Last round** | `last_round_type`, `last_round_date`, `last_round_post_money_aud`, `lead_investor` | all |

Derived by code only (never typed): growth %, CMGR, runway, burn multiple, CAC payback, LTV/CAC, NRR from CSV.

### 3.2 Documents (phase 2)

Same approach as the CV upload (`web/app/src/pages/hr/cvFile.ts`): the **browser** reads the file (pdf.js / CSV) and
sends text; the server stores text + SHA-256 of the original bytes, never the file (privacy, no malware surface).

| Kind | Accept | Limits | Used for | Level |
|---|---|---|---|---|
| Pitch deck | .pdf, .pptx (text), .md | ≤ 20 MB, ≤ 60k chars | `DeckFacts` → traction / market / moat claims with slide quotes | L2 when a typed number matches the deck (±5%), else the deck value is L1 "claimed in deck" |
| Metrics CSV | .csv (template `docs/templates/metrics-monthly.csv`: `month, revenue_aud, mrr_aud, new_mrr, expansion_mrr, contraction_mrr, churned_mrr, customers, new_customers, churned_customers, active_users, cash_aud, burn_aud`) + Stripe "MRR by month" / Baremetrics / ChartMogul exports mapped by header aliases | ≤ 2 MB, ≤ 120 rows | code computes growth, CMGR, NRR/GRR, logo churn, burn multiple, run consistency checks (§4.4) | L2 |
| Financial statements | .pdf (P&L, balance sheet, BAS summary) | ≤ 20 MB | revenue TTM, gross margin cross-check | L2 (L3 if accountant-signed and ABN matches) |

API: `POST /v1/studio/valuations/{id}/documents` `{kind, filename, sha256, text | rows}` (owner / admin, ≤ 5 per
valuation) → `{doc_id, parsed}`; `GET …/documents`; `DELETE …/documents/{doc_id}`. Table
`studio.valuation_documents(id, valuation_id, kind, filename, sha256, text, parsed jsonb, uploaded_by, created_at)`.

### 3.3 Connectors (phase 4, later)

Read-only, OAuth, the platform stores only computed monthly aggregates + a signed fetch receipt (hash of the provider
response, provider, account id, time): **Stripe** (restricted read key or Stripe Connect OAuth: subscriptions,
invoices → MRR movements), **Xero** / **MYOB** (P&L by month), **Google Analytics 4** (active users), **App Store
Connect / Google Play Console** (downloads, retention), **Basiq** (AU open banking: bank inflows as revenue
cross-check). Level **L4 "connected"**. Endpoints `GET /v1/connect/{provider}/start`, `GET /v1/connect/{provider}/callback`,
`POST /v1/connect/{provider}/refresh`, `DELETE /v1/connect/{provider}`.

### 3.4 Already-owned verified data

Approved, on-chain-disclosed KPI updates (`studio/updates.py`: revenue, gross/net profit, cash, customers, headcount)
become level **L3 "disclosed"** inputs for revaluations: code builds the monthly series from approved periods, so the
traction, efficiency and retention (customer count) sub-metrics of a listed business refresh without the founder
retyping anything.

---

## 4. Evidence and verification rules

### 4.1 Claim format (all analysts)

```python
class MetricClaim(BaseModel):          # LLM output (extract_json)
    metric: Literal[...]               # e.g. "arr", "paying_customers", "nrr", "tam", "cagr", "patent", ...
    value: float | None                # as stated, in `unit`
    unit: str = ""                     # "AUD" | "USD" | "%" | "count" | "months" | ...
    period: str = ""                   # as written ("FY24", "last 12 months", "June 2026")
    source_url: str = ""               # copied exactly from the evidence list, or "doc:<id>#p<page>"
    quote: str                         # verbatim ≤ 300 chars, must contain the number
    subject: Literal["company", "market", "competitor"] = "company"
```

Code keeps a claim only if: the source is stored evidence for this valuation (or an uploaded doc); the quote is in
the page/snippet/doc text (normalised whitespace, `people.quote_in`); the quote states the number
(`research.amount_in_quote`, ±1.5%); a company claim's page names the company; money converts with the dated FX
table; the period parses (`triangulate.parse_as_of`) and is ≤ 36 months old (older → shown, not scored). Dropped
claims go to `analysis.dropped[]` with the reason (as `VerifiedValuationEvidence.dropped`).

### 4.2 Verification levels (shown as badges everywhere)

| Level | Label (EN) | Meaning | Score effect (shrink toward 50) |
|---|---|---|---|
| L0 | Missing | no data | sub-metric dropped; coverage cap |
| L1 | Self-reported | typed by the founder, or only in the founder's deck, or a marketing claim on the company's own site | keeps 60% of the distance from 50 |
| L2 | Document-backed | typed value matches an uploaded document / CSV (±5%), or computed from the uploaded CSV that passed consistency checks | 80% |
| L3 | Publicly corroborated / disclosed | verbatim in an independent source (press, registry, app store, review site) or in an approved on-chain KPI update | 90% |
| L4 | Connected | computed from a connected system (Stripe, Xero, bank) with a fetch receipt | 100% |

`score_used = 50 + (score_raw − 50) × shrink(level)`. So self-reported great numbers help, but less than verified ones,
and self-reported bad numbers hurt less (conservative both ways). The dimension's level = weight-weighted mean of its
sub-metrics' levels; `trust_verification` = share of total scored weight at L2+ (0–100).

### 4.3 Confidence per dimension

`high` = coverage ≥ 0.7 and level ≥ L2 on the top-weighted sub-metric; `medium` = coverage ≥ 0.4; `low` otherwise.
Shown next to every dimension score and fed to the triangulation confidence reasons.

### 4.4 Anti-gaming checks (code, `tools/consistency.py`)

- **Cross-source**: typed vs deck vs site vs cited vs CSV; a > 20% gap flags "figures do not match" (both shown; the
  lower one is used unless the higher one is L3+).
- **Internal arithmetic**: ARR ≈ 12 × MRR (±10%); customers × ARPA ≈ revenue (±30%); growth from two points vs typed
  growth %; runway ≈ cash ÷ burn; NRR ≥ GRR; GRR ≤ 100%; churn and retention consistent.
- **Plausibility bounds by stage**: e.g. YoY growth > 1,000% at Series A+, NRR > 200%, gross margin > 95% for
  non-software → flag + the value is capped at the stage top-decile for scoring until an admin confirms.
- **CSV forensics**: duplicated rows, perfectly smooth series (coefficient of variation of MoM growth ≈ 0), round-number
  share, first-digit (Benford) test only when ≥ 50 values (flag, never an automatic penalty), negative values in
  non-negative columns, future months.
- **Public contradiction**: web traffic rank (Tranco) or app rating count wildly inconsistent with claimed consumer
  users (e.g. 1M MAU with no Tranco rank and < 50 ratings) → flag.
- **Concentration**: top-customer share > 20% flagged; a single customer > 50% caps T3 at 50 (high severity).
- **ARR hygiene**: ARR claims whose quote says "run rate", or where CSV shows services / one-off lines, are reclassified
  as revenue run-rate (not ARR) and not used for the ARR multiple.
- **Gameable public signals**: GitHub stars are discounted (fake-star campaigns are documented) — use contributors and
  releases instead; Similarweb-type estimates are not used (large error on small sites); Tranco only as a flag.
- **Stability**: a re-score that raises the index > 15 points from typed numbers alone requires admin review.
- Every flag lands in `svi.needs_human_review` and the report's Notes; the admin sees a "consistency" panel at the gate.

---

## 5. UI

### 5.1 Wizard (`web/app/src/pages/NewWizard.tsx`, `web/app/src/lib/selfReported.ts`)

- Step 1 stays one field (website) + the Founding team panel. The collapsed "Your numbers" box becomes **"Add your
  numbers (optional)"** with 4 small tabs: *Revenue & growth* · *Customers* · *Retention* · *Market & moat*, plus a
  **"Upload a pitch deck or metrics CSV"** drop zone (browser-parsed, like the CV). A stage chip ("Looks like: Seed —
  change") pre-selects which fields show; the founder can switch.
- Each field shows its unit, an example, and a "How we check this" tooltip (L1 → L2 by upload → L4 by connecting).
- `SR_FIELDS` grows to a grouped config `SR_GROUPS` (`key, kind, group, minStage, help`); the draft in localStorage
  keeps working (new keys are optional).
- CSV template download link; parse errors inline ("row 7: revenue is not a number").

### 5.2 Report (`web/app/src/pages/Valuation.tsx`)

Split the long `Report` into **tabs** (URL hash `#traction` etc., so they can be linked and pass `/verify` untouched):

| Tab | Content |
|---|---|
| Overview | grade, value, range, confidence, radar (9 dims), contribution bars, stage chip with reasons, "Top 3 things that would raise this score" |
| Team | existing `TeamCard` + link to hr.blockid.au |
| Traction | score + level badge; sub-metric table (value · stage median · top quartile · where it sits · source badge); growth chart when a series exists (CSV / KPI history); logos found (verified quotes) |
| Market | TAM / SAM / SOM bars (bottom-up vs top-down), inputs with quotes, CAGR, source-quality tiers |
| Moat & competition | 7-Powers grid (level 0–3, evidence quote per power), existing competitor funding bars and list, competitive intensity |
| Retention | NRR / GRR / churn gauges vs stage bands, cohort curve (CSV), reviews (rating, count, source), concentration |
| Valuation | existing `ValuationMethods` + the new multiple adjustment breakdown (base × growth × retention × margin, each with its level) + scorecard factor table |
| Evidence & notes | existing evidence list + dropped claims + consistency flags + search log |

Components: `DimensionTab`, `MetricTable`, `LevelBadge`, `BenchmarkBar` (value on a P25–P50–P75–P90 bar), `PowersGrid`,
`TamSamSom`, `CohortChart` (use the existing chart primitives; follow the dataviz rules already used by `HBars`).
Admin gate (`AdminReview`): overridable dims unchanged in shape (the new code-computed dims are not overridable — the
admin fixes the *input* instead: "mark this metric as verified (L3) with note" → `POST /v1/studio/valuations/{id}/metrics/verify`).
EN + VI strings in `web/app/src/dict*.ts`; public copy avoids "AI / SVI" per FACTS.md (tabs say "Business score").

---

## 6. Stage sync

### 6.1 How the stage is decided (`tools/stage.py`, deterministic)

Inputs, in priority order, each with its evidence:
1. **Listed** (verified listing from `market_evidence.detect_listing`) → `growth`.
2. **Latest verified round** (anchor kind `priced_round` or `CompanyFinancials`/typed `last_round_type`, ≤ 30 months
   old): pre-seed/angel → `pre-seed`; seed → `seed`; Series A → `series-a`; Series B or later → `growth`.
3. **Revenue / ARR band** (best level available): < A$0 revenue and no product live → `idea`; < A$150k →
   `pre-seed`; A$150k–1.5M → `seed`; A$1.5M–15M → `series-a`; ≥ A$15M → `growth`.
4. **Raised to date** band as a tie-breaker: < A$1M pre-seed, < A$5M seed, < A$30M series-a, else growth.
5. The LLM's `StartupProfile.stage` is only a last-resort hint.

Rule: stage = the round-based stage if one exists, otherwise the revenue band; if round-based and revenue-based
differ by ≥ 2 steps, take the **lower** and add a note ("raised a Series A but revenue looks like seed"). The report
shows `stage`, `stage_basis` (listing / round / revenue / raised / hint) and the reasons. Admin can override at the gate
(`overrides.stage`), recorded as `stage_basis = "human"`.

### 6.2 Everything keys off the stage — one table

`tools/stage.py`:

```python
STAGES = ("idea", "pre-seed", "seed", "series-a", "growth")      # unchanged keys (growth = Series B+)
@dataclass(frozen=True)
class StageProfile:
    weights: dict[str, float]            # §1.1 column
    bench: dict[str, tuple[float, float, float, float]]  # metric -> (P25, P50, P75, P90), §1.3
    pre_money_aud: tuple[float, float, float]            # P25, P50, P75 for the scorecard method
    stage_method_weight_with_others: float               # 0.35 / 0.35 / 0.2 / 0.1 / 0.1
    som_share: tuple[float, float]                       # achievable share of SAM in 5 years
    plausibility: dict[str, float]                       # upper bounds for anti-gaming caps
STAGE_PROFILES: dict[str, StageProfile] = {...}
STAGE_TABLE_VERSION = "2026-09"                         # stored in the report; /verify reads the stored copy
SECTOR_ADJ = {"saas": ..., "marketplace": ..., "fintech": ..., "consumer": ..., "hardware": ..., "services": ...}
```

`svi.STAGE_REVENUE_BENCHMARK` and `svi.STAGE_PRE_REVENUE_RANGE` become thin views of this table for v4 and are frozen
for `/verify` of old reports. **The report stores the exact stage profile values it used** (`svi.analysis.stage_profile`)
so `/verify` recomputes from stored inputs even after the table is recalibrated.

Stage re-evaluation happens on every re-score / revaluation; a stage change is an explicit event ("moved from seed to
Series A: weights and benchmarks changed") in the company activity feed and in the revaluation note.

---

## 7. Phased tasks, acceptance criteria and tests

Each phase: tests → deploy → update docs/FACTS.md, docs/LLM-ROUTING.md, README → commit + push (owner's rule).

### Phase E1 — model, stage and deterministic scoring (no new agents yet) — ~2 days

Files: new `tools/stage.py`, `tools/metrics_calc.py` (growth, CMGR, NRR/GRR, burn multiple, payback, LTV/CAC),
`tools/consistency.py`; `tools/svi.py` (v5 dims, `WEIGHT_SETS["v5"]` per stage, `score_v5`, keep v4 path);
`tools/triangulate.py` (v4: adjusted multiple, scorecard factor, stage-aware stage weight; `recompute` by version);
`schemas.py` (`SelfReportedMetricsV2`, `MetricValue{value, unit, as_of, level, source, quote}`, `DimensionDetail`,
`Analysis`, `SVIResult.analysis: Analysis | None` excluded from `report_hash` when `None`,
`SVIResult.weights_profile`); `config.py` (`MULTIPLE_ADJ`, `MARKET_SOURCE_TIERS`, `LEVEL_SHRINK`);
`agents/valuation.py` (use v5 when `FORMULA_VERSION=v5`; `rescore`); `studio/verify.py` (formula text v5).
Acceptance:
- Same inputs → same index/value (golden JSON fixtures); v1–v4 reports in the DB still verify (run
  `test_verify.py` on a snapshot of the 14 live companies: 14/14 match).
- A company with only a website gets a v5 report whose traction/retention show "Not enough data" (score 40, coverage 0)
  and whose value is within ±10% of v4 for the 8 backtest companies with anchors (anchors dominate).
- Stage rules: table-driven tests for 15 cases (listed, each round type, revenue bands, conflicts, hint only).
Tests: `tests/test_stage.py`, `tests/test_svi_v5.py`, `tests/test_metrics_calc.py`, `tests/test_consistency.py`,
extend `tests/test_valuation_v3.py` → v4 recompute, `scripts/valuation-backtest.py --formula v5`.

### Phase E2 — the four analysts + search plan — ~3 days

Files: `agents/traction.py`, `agents/market_size.py`, `agents/moat.py`, `agents/retention.py`, `tools/digest.py`,
`tools/lookups.py` (Tranco, Wayback CDX, iTunes Search, Play page, ABN Lookup; 7-day `studio.lookup_cache`),
`agents/data/abs_business_counts_2025.csv` (ABS counts by ANZSIC division × size, with source URL and date),
`tools/search.py` (4 new kinds + purposes, cap 12), `graph.py` (`analysts` node between `market` and `svi`, progress
detail "traction 62 · market 55 · moat 48 · retention n/a"), `ai_gateway.SCHEMA_PROFILES`, `config.py`
(`SEARCH_MAX_QUERIES` default 11 cap 12, `ANALYST_PAID_SEARCH_MAX`), `studio/schema.sql` (lookup cache).
Acceptance:
- Every stored claim has a verbatim quote found in stored text; a fixture with an invented quote/URL is dropped (per
  analyst).
- Budget: ≤ 12 searches total, typical +2; recorded in `searches` with purpose. Ledger shows ≤ US$0.02 extra on the
  paid path (run with `LLM_PROVIDER_ORDER=deepinfra` + Brave on 5 companies).
- Latency: `analysts` step p50 ≤ 25 s (parallel) on SambaNova.
- Live check on 5 companies (Canva, Airtasker, SafetyCulture, Employment Hero, one pre-seed AU startup): traction,
  market, moat, retention sections populated with ≥ 1 verified claim each where public data exists; zero invented URLs.
Tests: one test file per analyst with recorded evidence fixtures (`tests/fixtures/analysts/*.json`, same style as
`scripts/fixtures/valuation-backtest.json`), `tests/test_research_budget.py` extended for the new plan order.

### Phase E3 — founder inputs, uploads, re-score — ~2 days

Files: `schemas.SelfReportedMetricsV2`, `studio/routes.py` (`ValuationBody.metrics` accepts v2;
`PUT /v1/studio/valuations/{id}/metrics`; `POST/GET/DELETE /v1/studio/valuations/{id}/documents`;
`POST /v1/studio/valuations/{id}/rescore`; `POST /v1/studio/valuations/{id}/metrics/verify` admin), `studio/db.py`,
`studio/schema.sql` (`valuation_documents`), new `agents/deck_reader.py` (`DeckFacts`), `tools/csv_metrics.py`
(header aliases for Stripe / Baremetrics / ChartMogul / template), web `lib/selfReported.ts` (`SR_GROUPS`),
`NewWizard.tsx`, new `lib/docFile.ts` (reuse `cvFile.ts` pdf.js loader), `docs/templates/metrics-monthly.csv`.
Acceptance:
- Adding numbers after the report re-scores in < 3 s with no web calls (audit shows no `search_served`) and is refused
  once a company was created from the valuation (hash may be anchored) — same rule as `apply_to_valuation`.
- Uploading the template CSV of a fixture company yields growth, NRR, GRR, burn multiple equal to hand-computed values;
  the forensics fixture (smooth series, duplicate rows) raises flags.
- Typed ARR matching the deck within 5% shows L2; a 30% mismatch shows the flag and uses the lower value.
Tests: `tests/test_csv_metrics.py`, `tests/test_self_reported_v2.py`, `tests/test_rescore.py`, `tests/test_documents_api.py`
(auth: owner/admin only, size limits, ≤ 5 docs), vitest for `SR_GROUPS` parsing.

### Phase E4 — report UI — ~2 days

Files: `Valuation.tsx` (tabs), new `components/eval/*` (`DimensionTab`, `MetricTable`, `LevelBadge`, `BenchmarkBar`,
`PowersGrid`, `TamSamSom`, `CohortChart`), dictionaries EN/VI, `Verify.tsx` (v5 formula text; per-dimension recompute
table), sample report `/v/sample/report` refreshed.
Acceptance: every tab renders for (a) a website-only pre-seed, (b) a CSV-backed seed, (c) a listed growth company;
mobile 360 px without horizontal scroll; no "AI/SVI" wording on public tabs; `/verify` shows v5 recompute = stored.
Tests: vitest snapshot per tab with the three fixtures; Playwright smoke on `/v/sample/report#traction`.

### Phase E5 — stage-synced revaluation and pricing — ~1 day

Files: `studio/routes.py` `revalue` (option `from_kpis=true` → deterministic re-score from approved KPI updates, stage
re-evaluated), `studio/offerings.py` (pack shows confidence + evidence levels; warning when revenue is L1),
`studio/updates.py` (on publish: enqueue a suggested revaluation for admin, not automatic).
Acceptance: an approved quarterly KPI update with +40% revenue produces a suggested mark with the same stage profile
(or a stage-change note), requiring admin approval; offering pack warning appears for L1-only revenue.
Tests: `tests/test_revalue_from_kpis.py`, extend `tests/test_offerings.py`.

### Phase E6 — connectors (later) — ~4 days

Stripe first (restricted key or Connect OAuth → MRR movements → L4), then Xero, GA4, app-store consoles, Basiq.
Acceptance: fetch receipt hash stored; tokens encrypted at rest; revoking removes tokens and keeps only aggregates.

### Calibration task (runs alongside E1–E2)

Refresh `STAGE_PROFILES` from the sources in §9 and the SVI dissertation dataset; backtest v5 on the 8 reference
companies + 10 AU seed/Series A companies with known rounds (median |error| target ≤ 30%, same as v3); record in
`docs/valuation-reference.md`.

---

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Founders inflate typed numbers to raise the price of their tokenised shares | level shrink (L1 keeps 60%), consistency checks, plausibility caps, admin gate "consistency" panel, offering-pack warning for L1 revenue, re-score jump > 15 points needs review |
| Hash / verify breakage | new data only inside `svi.analysis` (excluded when `None`), versioned formulas (`v5`, triangulation `v4`), stored stage profile, snapshot test on 14 live companies |
| Search quota (bridge `/search` 150/day, Brave quota 0) | analyst searches last in `QUERY_PLAN`, conditional, 72 h cache, free APIs first; at 11 searches/valuation ≈ 13 valuations/day on the bridge — raise `BRIDGE_MAX_PER_DAY` or fund Brave if volume grows |
| Free-model extraction quality (namesakes, wrong company metrics) | verbatim-quote + page-names-company check, subject field, benchmark the 5 new schemas in `scripts/ai-benchmark.py` before switching `AI_ROUTING=dynamic` |
| Benchmarks are US-centric / dated | cite each row, `STAGE_TABLE_VERSION`, AU adjustment factor (smaller rounds), yearly refresh task |
| Stage misclassification swings weights and value | evidence-based rules with reasons, conflict → lower stage + note, admin override, stage method weight bounded |
| Too many dimensions confuse investors | Overview shows the grade + 5 priority dims first; others under "More" |
| Privacy of uploaded decks / CSVs | text only, browser-parsed, contacts redacted, owner/admin visibility only, delete endpoint, never sent to search providers (only to LLM providers already listed in SECURITY.md) |
| Web-traffic proxies are weak (Tranco top-1M only; no Similarweb without paid API) | used only as a contradiction flag, never as a positive score input |
| Latency grows (4 more calls) | parallel analysts, compact digests, hedging already in the gateway; target +25 s p50 |
| Cost overruns on paid fallback | `ANALYST_PAID_SEARCH_MAX`, per-valuation spend in the ledger, `DEEPINFRA_DAILY_BUDGET_USD` unchanged |

---

## 9. Research notes and sources

Web research done on 27 Sep 2026 (about 30 searches). Carta pages returned 403, so Carta figures are taken from
sites that cite Carta; items marked *secondary* should be re-checked during calibration before they become weights.

### 9.1 What the frameworks say (and what this plan takes from each)

- **Traction.** YC treats growth rate as the key signal: 5–7% per week is good, 10% exceptional, 1% a sign the team has
  not found it yet; revenue is the preferred metric [S9]. Battery's T2D3 path (from ~US$1–2M ARR: ×3, ×3, ×2, ×2, ×2)
  [S7]; fewer than 10% of companies hit it in 2024 (*secondary*) [S8]. Bessemer: US$1–10M ARR companies averaged ~200%
  growth (middle 50%: 100–230%), 65–70% gross margin target [S3]; good/better/best for Series B/C: growth 75/100/125%,
  NRR 100/110/120%, logo retention 85/90/95%, CAC payback 12–18 / 6–12 / 0–6 months, runway 12/18/24 months [S2].
  High Alpha 2025 median growth by ARR band: < US$1M 75%, 1–5M 40%, 5–20M 30%, 50M+ 15% [S4]; SaaS Capital median 22%
  (2025) for private B2B [S32]. a16z separates bookings, revenue, ARR, TCV, ACV — run-rate presented as ARR is a red
  flag [S33]. → Taken: T1/T2 definitions, ARR hygiene, stage growth bands, MoM at early stage.
- **Efficiency.** Burn multiple (Sacks): < 1× amazing, 1–1.5× great, 1.5–2× good, 2–3× suspect, > 3× bad [S15]; Series A
  expected near 1.0× (CRV, citing Carta) [S6]. Rule of 40: only 27.9% of 1,377 private companies cleared it, 89% of them
  via growth, and only 37% stayed there a year later [S34] → used only at growth stage. LTV/CAC 3:1 comes from mature
  SaaS (*secondary*) [S35]. KeyBanc/Sapphire 2024 median CAC payback ~20 months [S16].
- **Stage thresholds.** Series A median ARR ~US$2.5M in 2025 (competitive US$2–5M), median pre-money US$48M (Q1 2025),
  616 days seed→A, 17.9% dilution (CRV citing Carta) [S6]; seed bar ~US$300–500K ARR (*secondary*) [S5]; seed 10–20%+
  MoM for several months (*secondary*) [S1]; pre-seed judged on team, market, narrative (*secondary*) [S36]; median seed
  post-money ~US$24M (Carta via *secondary*) [S18]. AI rounds price very differently (Carta Q1 2026) [S6].
- **Market sizing.** a16z prefers bottom-up (customers × ACV + a credible go-to-market) and warns about "1.36B people ×
  $1 × 40%" top-down maths [S33]. Sequoia's plan format: why now, market size (TAM/SAM/SOM), competition [S37]. Credible
  AU base: ABS Counts of Australian Businesses (2,729,648 trading, 994,178 employing, by ANZSIC × size) [S29]; ASIC
  dataset [S31]. → Taken: bottom-up SAM first, top-down as cross-check, source tiers, red flags (top-down only, no
  source, no customers × ACV, SOM unrelated to channel, no why-now).
- **Moats.** Helmer's 7 Powers — scale economies, network economies, counter-positioning, switching costs, branding,
  cornered resource, process power; each needs a benefit **and** a barrier [S38]. NFX: network effects ≈ 70% of tech
  value since 1994, 16 types in 5 families [S39]. a16z marketplace defensibility: multi-tenanting, switching /
  multi-homing costs, concentration [S20]. Multi-year contracts show 103% NRR / 94% GRR vs 100% / 89% month-to-month
  [S10] → switching-cost evidence. → Taken: the 7-Powers grid with benefit + barrier evidence and level caps.
- **Retention.** SaaS Capital 2025 (ARR ≥ US$1M): median NRR 101%, GRR 91% (95% above US$250K ACV); NRR by ACV
  98–106%; growth 15% at NRR < 90% vs 50% at > 130%; "GRR must be at least 90%" [S10]. High Alpha: median NRR 106%, SMB
  ~97%, enterprise target 118%+ [S11]. Public SaaS median NRR 110% (Sep 2026) [S12]. Lenny: 6-month retention good/great
  by category (SMB SaaS 60/80%, consumer subscription 40/70%, social 25/45%) [S14]; monthly churn good/great (B2B SMB
  2.5–5% / < 1.5%) [S13]. a16z social: DAU/MAU 40/50%+, D30 25/30% [S23]; consumer subscription M12 30–40% was best in
  class [S24]; marketplace supply GMV retention best ≥ 100% at M12, average 45–50% [S21]. → Taken: R1–R5, ACV bands.
- **Valuation methods.** Scorecard (Payne): team 30 / opportunity 25 / product 15 / competition 10 / sales & partners 10
  / more funding 5 / other 5, multiplier on a regional median [S26]. Berkus: up to US$0.5M each for 5 elements, ~US$2.5M
  cap, inflation-adjust [S27]. Risk Factor Summation: 12 risks scored −2..+2 [S28]. VC method: exit ÷ target multiple
  [S40]. Public multiples by growth tier (Sep 2026): median EV/NTM revenue 4.2×; > 22% growth 18.0×, 15–22% 6.7×,
  < 15% 3.3× (Feb 2026: 9.7× for high growth) [S25].
- **Public signals.** Tranco: free, manipulation-resistant top-sites list, mostly the top 1M [S41]. Similarweb
  over-reported sessions by ~94% across 1,787 e-commerce sites, weakest under ~5K visits/month [S42]. 4.5M suspected fake
  GitHub stars; ~16% of repos with 50+ stars linked to fake-star campaigns in July 2024 [S43]. Job postings as a leading
  indicator (*secondary, weak*) [S44]. ABN Lookup free web services [S30]. → Taken: flags only, never positive score
  inputs, except registry facts (ABN/ASIC/IP Australia) which are L3.
- **Verification.** TrustMRR (read-only Stripe/LemonSqueezy/Polar keys, hourly) [S45] and Baremetrics Open Startups
  (live MRR/churn from Stripe/Braintree/Recurly) [S46] show connected revenue is practical → L4. Concentration > 20% =
  warning, > 50% = high (*secondary*) [S47]; request cohorts, retention, pipeline, unit economics from seed (Hustle
  Fund) [S48]; Benford's law only on transaction-level data with ≥ ~50 values, never on summary KPIs [S49].

### 9.2 Source list

| Key | Source |
|---|---|
| S1 | https://www.startups.com/lexicon/seed-round (*secondary*) |
| S2 | https://www.bvp.com/atlas/state-of-the-cloud-2023 |
| S3 | https://www.bvp.com/atlas/scaling-to-100-million |
| S4 | https://www.growthunhinged.com/p/2025-saas-benchmarks-report · https://www.highalpha.com/saas-benchmarks |
| S5 | https://www.pitchwise.se/blog/median-seed-round-size-by-industry-in-2026-data (*secondary*) |
| S6 | https://www.crv.com/content/series-a-metrics-vcs-expect · https://carta.com/data/state-of-private-markets-q1-2026/ |
| S7 | https://www.battery.com/blog/helping-entrepreneurs-triple-triple-double-double-double-to-a-billion-dollar-company/ |
| S8 | https://saascalchub.com/guides/2026-saas-industry-benchmarks (*secondary*) |
| S9 | https://www.ycombinator.com/library/8s-startup-growth |
| S10 | https://www.saas-capital.com/wp-content/uploads/2025/09/RB32WS1-2025-B2B-SaaS-Retention-Benchmarks.pdf |
| S11 | https://www.highalpha.com/blog/net-revenue-retention-2025-why-its-crucial-for-saas-growth |
| S12 | https://cloudedjudgement.substack.com/p/clouded-judgement-92526-own-the-interaction |
| S13 | https://www.lennysnewsletter.com/p/monthly-churn-benchmarks |
| S14 | https://www.lennysnewsletter.com/p/what-is-good-retention-issue-29 · https://x.com/lennysan/status/1277620704146423809 |
| S15 | https://sacks.substack.com/p/the-burn-multiple-51a7e43cb200 |
| S16 | https://www.saasletter.com/p/2024-keybanc-sapphire-saas-benchmarks |
| S17 | https://verycreatives.com/saas-metrics/fintech (*secondary*) |
| S18 | https://www.flowjam.com/blog/seed-round-valuation-2025-complete-founders-guide (*secondary*, citing Carta) |
| S19 | https://a16z.com/the-marketplace-glossary/ · https://www.tidemarkcap.com/vskp-chapter/marketplace-take-rates |
| S20 | https://a16z.com/13-metrics-for-marketplace-companies/ |
| S21 | https://a16z.com/gmv-retention-the-marketplace-metric-most-ignore/ |
| S22 | https://www.feinternational.com/blog/how-to-value-a-fintech-business (*secondary*) |
| S23 | https://a16z.com/do-you-have-lightning-in-a-bottle-how-to-benchmark-your-social-app/ |
| S24 | https://a16z.com/the-great-expansion-a-new-era-of-consumer-software/ · https://a16z.com/ai-retention-benchmarks/ |
| S25 | https://cloudedjudgement.substack.com/p/clouded-judgement-92526-own-the-interaction · https://cloudedjudgement.substack.com/p/clouded-judgement-2626-software-is |
| S26 | https://www.equidam.com/scorecard-valuation-method/ |
| S27 | https://www.venionaire.com/early-stage-startup-valuation-part-2-the-berkus-method/ |
| S28 | https://waveup.com/blog/startup-valuation-methods/ |
| S29 | https://www.abs.gov.au/statistics/economy/business-indicators/counts-australian-businesses-including-entries-and-exits/jul2021-jun2025 |
| S30 | https://abr.business.gov.au/Documentation/WebServiceMethods |
| S31 | https://data.gov.au/data/dataset/asic-companies |
| S32 | https://www.saas-capital.com/research/private-saas-company-growth-rate-benchmarks/ |
| S33 | https://a16z.com/16-more-startup-metrics/ |
| S34 | https://thefundcfo.substack.com/p/357-rule-of-40-revisited-standard |
| S35 | https://foundrycro.com/blog/ltv-cac-ratio-benchmarks-2026/ (*secondary*) |
| S36 | https://www.stackmatix.com/blog/traction-benchmarks-by-funding-stage (*secondary*) |
| S37 | https://sequoiacap.com/article/writing-a-business-plan |
| S38 | https://7powers.com/ · https://www.acquired.fm/episodes/7-powers-with-hamilton-helmer |
| S39 | https://www.nfx.com/post/network-effects-manual |
| S40 | https://www.equidam.com/vc-method-startup-valuation/ |
| S41 | https://tranco-list.eu/ · https://arxiv.org/abs/1806.01156 |
| S42 | https://www.omniconvert.com/blog/we-analyzed-1787-ecommerce-websites-similarweb-google-analytics-thats-we-learned/ |
| S43 | https://arxiv.org/html/2412.13459v1 |
| S44 | https://paperswithbacktest.com/datasets/job-postings-hiring-data-trading (*secondary, weak*) |
| S45 | https://trustmrr.com/faq |
| S46 | https://baremetrics.com/open-startups |
| S47 | https://ddr.bio/blog/due-diligence-checklist (*secondary*) |
| S48 | https://www.hustlefund.vc/post/angel-squad-angel-investing-due-diligence-checklist-step-by-step |
| S49 | https://www.journalofaccountancy.com/issues/2022/sep/using-benfords-law-reveal-journal-entry-irregularities/ |

### 9.3 Open decisions for the owner

1. Approve the stage weight columns in §1.1 (team fixed at 0.30; pre-seed product 0.10 above retention 0.07).
2. `AU_ROUND_ADJ` = 0.5 × US medians for the scorecard pre-money until AU round data is calibrated — or supply AU figures.
3. Level shrink factors (L1 60% / L2 80% / L3 90% / L4 100%) — how hard to discount self-reported numbers.
4. Raise `SEARCH_MAX_QUERIES` cap 8 → 12, and the bridge `/search` daily cap to match expected volume (or fund Brave).
5. Connector order for E6 (Stripe → Xero → GA4 → app stores → Basiq).
