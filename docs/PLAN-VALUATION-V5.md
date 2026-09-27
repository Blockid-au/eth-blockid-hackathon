# BlockID — Business Valuation Agent (valuation v5) — implementation plan

Status: PLAN ONLY (no repo changes). Researched 27 Sep 2026 against `/home/dovanlong/blockid-eth-platform` (live
https://eth.blockid.au). Paths below are relative to `agents/src/blockid_agents/` unless they start with `web/`,
`docs/`, `scripts/` or `agents/tests/`.

Owner request (paraphrased): a separate valuation agent built on the most widely used valuation methods, OR on the
business's own uploaded financial projections, OR on Claude's valuation library / standard methods (reuse a ready-made
library if one exists); values must follow the startup stage and be **finalised before** tokenised shares are
proposed (price per share, number of shares).

---

## 0. TL;DR

1. **There is no importable "Claude valuation library".** Anthropic's `anthropics/financial-services` repo
   (Apache-2.0) ships Claude *skills* (`dcf-model`, `comps-analysis`, `3-statement-model`, `lbo-model`) — prompt
   instructions that make Claude author Excel models, plus one `validate_dcf.py` checker. They assume paid data
   connectors (S&P Kensho / FactSet / Daloopa) and SEC filings. We **reuse their methodology and checks** (terminal
   growth < WACC, WACC sanity 5–20 %, terminal value share of EV, mid-year convention, base-centred sensitivity grid,
   quartile statistics for comps, three-tier isolation of untrusted uploaded packages) with attribution, and **write
   the maths ourselves** as a small deterministic Python module, because BlockID's rule is "the LLM never produces a
   number" and `/verify` must recompute every value from stored inputs.
2. **New deterministic engine** `tools/valuation_methods.py` (pure functions: `dcf`, `trading_comps`,
   `precedents`, `vc_method`, `scorecard`, `berkus`, `rfs`, `first_chicago`) + `tools/valuation_params.py`
   (frozen, versioned parameters and dated market data) + `blend_v5` in `tools/triangulate.py`. Valuation formula
   **v5** = v3 methods (market anchor, revenue multiple, stage benchmark) + the new methods, selected and weighted by
   a **stage × data-availability matrix** and an **evidence-quality factor**. `studio/verify.py` gets a `v5`
   candidate; v1–v4 reports keep verifying unchanged.
3. **Projection upload**: XLSX/CSV template (3–5 years + up to 3 actual years), parsed without any LLM, validated with
   sector/stage sanity caps, stored with its SHA-256, and always labelled "Based on management projections
   (unaudited, not verified by BlockID)". Projections unlock DCF, VC method and First Chicago; bad projections lose
   weight instead of silently moving the value.
4. **Valuation Agent** (`agents/valuation_agent.py`, new graph step after `valuation`): the LLM only (a) maps the
   business to a fixed industry list, (b) suggests Berkus / Risk-Factor ratings with cited evidence (ai_suggested,
   confirmed at the admin gate), (c) extracts precedent-transaction claims that code then quote-verifies. ≤ 3 LLM
   calls, ≤ 1 extra search (inside the existing hard cap of 8), US$0 on the free tier, worst case < US$0.01.
5. **Tokenisation hand-off**: after admin approval the owner **finalises** the valuation → a frozen
   `ValuationFinal` (pre-money, recommended price per share, share count, offer price range, stage, hash). Company
   creation (`POST /v1/studio/companies`) and offerings (`studio/offerings.py`) read their defaults from it and refuse
   a stale or stage-mismatched one.
6. **UI**: "How we reached this value" football-field chart (inline SVG), method tabs, DCF sensitivity grid,
   admin-editable assumptions with reason + audit + new version.
7. **Acceptance**: live median |error| stays ≤ 25 % on the 8 reference companies (today 25.8 %), fundamentals-only
   ablation improves from 60.6 % to ≤ 45 %, new profitable-SME set ≤ 30 % from fundamentals alone; 100 % of stored
   v5 reports recompute exactly.

Effort: ~18–22 dev-days in 7 phases behind `VALUATION_V5=0` (§10).

---

## 1. What exists today (read before designing)

| Piece | File | What it does | What v5 must keep |
|---|---|---|---|
| v3 triangulation | `tools/triangulate.py` (360 lines) | 3 methods: `market_anchor` (newest verified own price; kind × recency weight), `revenue_multiple` (revenue × comps > sector > market analysis > default; −25 % private discount on listed multiples), `stage_scorecard` (SVI stage benchmark × SVI factor; weight 1 alone, 0.1 with others, 0 if > 5× away). Blend = weighted mean, range widened to ±10/20/35 % by confidence. `recompute(tri)` rebuilds from stored `inputs`. | Every method stores `inputs`; `recompute` is pure; confidence reasons in plain words. |
| SVI | `tools/svi.py` | 7 weighted dimensions (v4 weights, founder 0.30), index → factor `0.5 + index/100`; `STAGE_PRE_REVENUE_RANGE` placeholders (idea 0.25/0.75/1.5 M … growth 30/80/200 M AUD); formula versions v1, v1b, v2, v3, v4; `apply_triangulation` sets the headline range. | SVI stays the *quality* indicator; its dimension scores feed Scorecard deterministically (§2.5). |
| Evidence | `agents/market_evidence.py`, `agents/research.py` | One LLM call → `ValuationEvidence` claims; code keeps a claim only if the quote is verbatim on a stored page and states the number; fixed FX table. | Same verification for precedent transactions. |
| Agent | `agents/valuation.py` | LLM suggests 5 qualitative scores (ai_suggested); code computes the rest; `apply_overrides` at the human gate; `apply_team_score`. | Human gate is the only way an AI-suggested input becomes "human". |
| Config | `config.py` | `FX_TO_AUD` (as of 2026-09-26, USD 1.50), default multiples (2/3.5/6×, SaaS/fintech 3/6/10×), anchor weights, `PRIVATE_COMPANY_DISCOUNT 0.25`, `RANGE_MIN_HALF_WIDTH`, search cap 8 × 3 pages. | Fixed, dated parameters so values reproduce. |
| Verify | `studio/verify.py` | `recompute(report)` tries v3 → v2 → v1b → v1 and reports which version reproduces the stored numbers; hash = keccak of `{url, profile, competitors, market, svi, self_reported}` (`studio/report_hash.py`). | Do **not** change `REPORT_KEYS`; put all v5 data inside `svi.triangulation` so it is hashed and anchored on-chain. |
| Company creation | `studio/routes.py:612` | `total_shares = round(valuation_mid / share_price_aud)`, `share_price_aud` default **A$1**; valuation must be `approved`. | Keep A$1 as fallback; default now comes from `ValuationFinal`. |
| Offerings | `studio/offerings.py` | Offer price default = latest mark (`studio.marks`, else `share_price_aud`); pack shows low/mid/high + confidence; `PRICE_WARN` 1.2 × mark. | Add range check against the finalised range and a staleness check. |
| Backtest | `docs/valuation-reference.md`, `scripts/valuation-backtest.py` | 8 AU companies; offline median \|error\| 6.2 %, **live 25.8 %** (4/7 in range); without own price 60.6 %. | Same script, extended set, ablations. |
| LLM routing | `docs/LLM-ROUTING.md`, `ai_gateway.py` | Profiles `extract_json` / `reason_score`; SambaNova free → Claude bridge (300/day) → DeepInfra (US$3/day cap). | New calls use `extract_json`; no new provider. |
| Four-eyes | `studio/company_admins.py` (`CompanyAuthz`) | Company-level approvals need a second person; demo account never approves. | Reuse for admin assumption edits on a finalised valuation. |

Gaps v5 fills: no DCF, no EBITDA/earnings multiples, no precedent transactions, no startup-specific methods beyond a
placeholder stage table, no way for the business to upload forecasts, no explicit stage → method logic, no frozen
"final" value/price/share count linking valuation → company → offering, no football-field view.

---

## 2. Research findings (with sources)

### 2.1 Methods practitioners actually use

**Established businesses — the "three pillars".** DCF, trading comparables and precedent transactions are the three
standard methods in investment banking, equity research, PE and M&A; comps is the most used (data readily
available), EV/EBITDA the most common metric, and DCF is rarely used alone — it is triangulated with the other two
into a range ([CFI — valuation methods](https://corporatefinanceinstitute.com/resources/valuation/valuation-methods/),
[Ryan O'Connell CFA — DCF & multiples](https://ryanoconnellfinance.com/dcf-valuation-multiples/),
[Street of Walls](https://www.streetofwalls.com/finance-training-courses/investment-banking-technical-training/valuation-techniques-overview/)).

- **DCF (FCFF → EV, discounted at WACC)**: FCFF = EBIT × (1 − t) + D&A − capex − ΔNWC. Cost of equity by CAPM
  (rf + β × ERP); WACC = weighted Ke / after-tax Kd; no debt → WACC = Ke. Mid-year convention. Terminal value:
  **Gordon growth** (preferred; g ≤ long-run GDP / rf, g < WACC) or **exit multiple** (final-year EBITDA × comps or
  precedent multiple). TV should be ~50–70 % of EV; > 75 % means the model leans on the terminal assumption.
  Sensitivity grid centred on the base case (Anthropic `dcf-model` skill, see §2.2). FCFE (equity cash flows at Ke)
  only for banks / lenders — out of scope for v5.
- **Trading comps**: EV/Revenue, EV/EBITDA, P/E of listed peers; use quartiles (25th / median / 75th), not the mean
  (Anthropic `comps-analysis` skill). Listed → private: discount for lack of marketability **20–35 %** from
  restricted-stock studies, 40–60 % from pre-IPO studies; smaller / less profitable firms get larger discounts
  ([Acquiry — DLOM research](https://www.acquiry.com/sector-multiples/dlom-research/),
  [Grant Thornton UK](https://www.grantthornton.co.uk/insights/when-to-apply-a-discount-for-lack-of-marketability/)).
  Our existing 25 % private-company discount sits inside that band.
- **Precedent transactions**: EV / revenue or EV / EBITDA paid in acquisitions (include a control premium, no
  DLOM when the targets were private). Australian private businesses with < A$5 M EBITDA typically change hands at
  **~2–6× normalised EBITDA**; mid-market (A$1–5 M EBITDA) 3.5–6×; size is the strongest driver
  ([Lyndon Advisory 2026](https://lyndonadvisory.com/blog/ebitda-multiples-australia-2026),
  [Oliver Group 2026](https://olivergroup.com.au/insights/ebitda-multiples-by-industry-australia/),
  [Quinn M&A 2026](https://www.quinnma.com.au/blog/valuations/what-is-my-business-worth-2026/)). These are broker /
  adviser composites — usable as a *cited sector range*, never as verified comps.

**Reconciling methods.** IVS 105: where several methods are used, the conclusion must be reasoned and described
"without averaging"; *weight* is the reliance placed on each indication; widely divergent indications must be
investigated rather than weighted blindly ([IVS 105](https://www.ivsc.org/wp-content/uploads/2021/10/IVS105ValuationApproaches.pdf)).
→ v5 keeps a weighted blend **but** (a) weights come from evidence quality, (b) an outlier > 3× from the median of the
other methods gets weight 0 and a note, (c) every weight has a written reason. The football field (bars per method +
blended value) is how the reconciliation is shown.

**Private-capital practice.** IPEV Guidelines (Dec 2022, and the **Dec 2025 edition**): the price of a recent
investment is a **calibration point, not a default fair value**; for pre-revenue companies look at milestones, cash
burn, market acceptance and the timing of the next round
([IPEV 2022](https://www.privateequityvaluation.com/Portals/0/Documents/Guidelines/IPEV%20Valuation%20Guidelines%20-%20December%202022.pdf),
[IPEV 2025](https://www.privateequityvaluation.com/Portals/0/Documents/Guidelines/2025%20IPEV%20Valuation%20Guidelines.pdf),
[PwC summary](https://www.pwc.com/jg/en/events/document/ipev-2022-update-summary-26-january-2023.pdf)).
→ v5 keeps the v3 market anchor as the dominant method when fresh, but it now *calibrates* the fundamentals (implied
multiple / implied discount rate shown) instead of standing alone.

**Startups.** The five methods most cited for early-stage companies are Berkus, Scorecard (Payne), Risk Factor
Summation, the VC method and comparables; practitioners run Berkus + Scorecard side by side and add RFS when risk is
lopsided ([Waveup 2026](https://waveup.com/blog/startup-valuation-methods/),
[Virtue CPAs](https://virtuecpas.com/pre-revenue-startup-valuation-methods-explained/),
[Republic Europe](https://europe.republic.com/academy/4-valuation-methods-used-by-vcs-and-angels)).

- **Scorecard (Bill Payne, 2001)**: start from the median pre-money of recently funded peers in the region/stage,
  multiply by Σ weight × comparison factor; weights team 30 %, opportunity size 25 %, product/technology 15 %,
  competition 10 %, marketing/sales/partnerships 10 %, need for additional investment 5 %, other 5 %
  ([Equidam](https://www.equidam.com/scorecard-valuation-method/),
  [Venionaire](https://www.venionaire.com/startup-valuation-payne-scorecard-method/)).
- **Berkus**: up to US$500k for each of 5 risk reducers (sound idea, prototype, quality team, strategic
  relationships, product rollout / sales) → up to US$2 M pre-revenue (US$2.5 M incl. rollout); the amounts are
  "arbitrary" and should be adjusted for geography and sector
  ([Angel Capital Association — Berkus, "After 20 years"](https://angelcapitalassociation.org/blog/after-20-years-updating-the-berkus-method-of-valuation/),
  [berkus.com](https://berkus.com/the-berkus-method-valuing-an-early-stage-investment-2/)).
- **Risk Factor Summation (Ohio TechAngels)**: base pre-money (regional median) ± US$250k per step on 12 risks rated
  −2…+2 (management, stage, legislation/political, manufacturing, sales & marketing, funding, competition,
  technology, litigation, international, reputation, lucrative exit)
  ([Gust](https://gust.com/blog/valuations-101-the-risk-factor-summation-method/),
  [Springer chapter](https://link.springer.com/chapter/10.1007/978-3-031-35291-1_11)).
- **VC method**: post-money today = exit value / target multiple (or / (1 + r)^t); pre = post − investment. Targets:
  seed 20–30× (some say more), Series A 10–15×, growth 3–5×; early-stage discount rates 40–60 %
  ([Kruze](https://kruzeconsulting.com/blog/what-vcs-return-expectations/),
  [Industry Ventures risk/return matrix](https://www.industryventures.com/insight/the-venture-capital-risk-and-return-matrix/),
  [Ryan O'Connell — VC method](https://ryanoconnellfinance.com/venture-capital-valuation-method/)).
- **First Chicago**: probability-weighted worst / base / best scenarios (often 25 / 50 / 25 %), each a DCF or exit
  value ([Wall Street Prep](https://www.wallstreetprep.com/knowledge/first-chicago-method/)).
- **Cost to duplicate**: a floor (what it costs to rebuild product/IP); ignores the market and the team — shown as
  information only, never weighted (not in the owner's "most used" set).

**Market reference points for the stage bases.** Carta US medians: seed pre-money US$16 M (Q3 2025), seed post
US$24 M and Series A post US$78.7 M (Q4 2025) ([Carta Q1 2026](https://carta.com/data/state-of-private-markets-q1-2026/),
[Carta pre-seed Q2 2026](https://carta.com/data/state-of-pre-seed-q2-2026/)). Australia 2025 median **deal sizes**:
A$1.0 M angel/pre-seed, A$2.5 M seed, A$11 M Series A, A$30 M Series B+ (390 deals)
([Cut Through Venture 2025](https://www.cutthrough.com/insights/state-of-australian-startup-funding-2025)).
AU pre-money medians are not published in the free summary → derive with a typical 15–25 % dilution per round
(seed A$2.5 M / 20 % ⇒ ~A$10 M pre) and **calibrate in Phase 0**; until then keep the existing placeholder table and
label it.

### 2.2 Libraries and tools — reuse vs write

| Candidate | Licence | What it gives | Decision |
|---|---|---|---|
| **anthropics/financial-services** (commit `574ed36`, 21 Sep 2026) — `plugins/vertical-plugins/financial-analysis/skills/{dcf-model,comps-analysis,3-statement-model,lbo-model}`, agent plugin `valuation-reviewer`, `dcf-model/scripts/validate_dcf.py` ([repo](https://github.com/anthropics/financial-services), [Financial Analysis plugin](https://claude.com/plugins/financial-analysis), [install guide](https://support.claude.com/en/articles/13851150-install-financial-services-plugins)) | Apache-2.0 | Methodology written for Claude to build live-formula Excel models; data from paid MCPs / SEC; checks: g < WACC (critical), WACC outside 5–20 % (warn), TV > 80 % of EV (warn); sensitivity centre = base; comps stats Max/75th/Median/25th/Min; "valuation-reviewer" = 3-tier isolation (reader with no tools touches untrusted docs → schema-validated JSON → runner → publisher). | **Reuse the rules, not the code path.** Port the checks into `valuation_methods.dcf_checks()` (cite skill + commit in a comment; Apache-2.0 attribution in `NOTICE` if any text/code is copied verbatim). Mirror the 3-tier isolation for uploaded projections (parser never shares a context with tools). Optional Phase 7: offer an admin-only "Download model (.xlsx)" built by our own openpyxl writer that follows the skill's conventions (inputs blue, formulas live, sensitivity grid). **Do not** run the skill at request time (needs Claude Code + paid connectors, not deterministic). |
| **numpy-financial** ([repo](https://github.com/numpy/numpy-financial)) | BSD-3 | `npv`, `irr`, `pmt` | **Not needed at runtime** (NPV is 5 lines; pulls numpy). Use as a *test oracle* in `dev` extras. |
| **pyxirr** ([repo](https://github.com/Anexen/pyxirr)) | Unlicense | Fast XIRR/XNPV (Rust) | Not needed (annual periods). |
| **QuantLib** | BSD-style | Curves, day counts, derivatives | Overkill. |
| **FinanceToolkit** ([repo](https://github.com/JerBouma/FinanceToolkit)) | MIT | Ratios/DCF for **listed** tickers via FMP API | No (needs paid API; our subjects are private). |
| **openpyxl** (MIT) | MIT | Read `.xlsx` (read_only, `data_only=True`) and write the template | **Add** as a dependency; with **defusedxml** (PSF) installed openpyxl guards against XML attacks. |
| pandas | BSD-3 | Tabular parsing | **No** — heavy; stdlib `csv` + openpyxl are enough. |
| Open-source DCF repos (e.g. `halessi/DCF`, 501★, *no licence*) | none / MIT toy repos | — | **Do not vendor** (no licence = all rights reserved; toy quality). |

Conclusion: write ~600 lines of pure Python (no numpy) — deterministic, auditable, byte-for-byte reproducible by
`/verify`, which no external library gives us for free.

### 2.3 Market data for discount rates and multiples (dated snapshot)

| Input | Value | Date | Source |
|---|---|---|---|
| AU risk-free (10-y CGS) | **5.385 %** (5.40 % on 25 Sep; near its highest since 2011) | 26 Sep 2026 | [Trading Economics](https://tradingeconomics.com/australia/government-bond-yield), [ABC 1 Sep 2026](https://www.abc.net.au/news/2026-09-01/australian-government-10-year-bond-hits-15-year-high/107103096) |
| VN 10-y government bond | 4.54 % (3.5-year high) | 3 Sep 2026 | [Trading Economics](https://tradingeconomics.com/vietnam/government-bond-yield/news/580736) |
| Mature-market ERP (Damodaran) — Australia (Aaa, CRP 0) | **4.23 %** | 5 Jan 2026 | [Damodaran ctryprem](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ctryprem.html) |
| Vietnam (Ba2): default spread / ERP / **CRP** | 2.56 % / 8.13 % / **3.90 %** | 5 Jan 2026 | same |
| AU practice MRP | **6.0 %** (independent expert reports: almost all use 6 %; regulators 6 %) | 2008–2026 | [CA ANZ — MRP Australian evidence](https://www.charteredaccountantsanz.com/tools-and-resources/client-service-essentials/business-valuation/market-risk-premium-australian-evidence) |
| Industry betas, WACC, EV/Sales, EV/EBITDA, PE, margins | `betaRest.xls`, `waccRest.xls`, `psRest.xls`, `vebitdaRest.xls`, `marginRest.xls` (Aus/NZ/Canada), `*emerg.xls` (emerging, for VN), `*Global.xls` | 9 Jan 2026 | [Damodaran current data](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datacurrent.html) |
| Country risk methodology | Damodaran 2026 edition | 2026 | [Country risk 2026](https://aswathdamodaran.substack.com/p/country-risk-determinants-measures), [ERP 2026 (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6361419) |
| AU private SME EBITDA multiples | 2–6× (< A$5 M EBITDA); by sector (tech 6–14×, healthcare 6–12×, prof. services 5–9×, manufacturing 4–7× for mid-market) | 2026 | Lyndon / Oliver Group / Quinn (above) |
| DLOM | 20–35 % (restricted stock), 40–60 % (pre-IPO) | — | Acquiry (above) |

Decisions (owner can change in §12):

- **ERP**: use AU practice **6.0 %** as base; show Damodaran 4.23 % as the low end of the sensitivity grid.
  (With rf at 5.4 %, 6 % gives Ke ≈ 11.4 % at β = 1 — in line with AU independent-expert practice.)
- **Vietnam**: value in AUD; Ke = rf_AU + β × ERP + **CRP_VN 3.90 %** (Damodaran λ = 1 for a domestic-revenue
  business); VN CIT 20 %, AU company tax 25 % (base-rate entity) / 30 %.
- **Private-company premium** in DCF: `size_specific_premium` 3 % (A$ > 20 M EV), 4 % (5–20 M), 6 % (< 5 M) —
  judgement parameter, labelled, editable by admin. **Never** add a DLOM on top of a DCF that already carries this
  premium (double counting); DLOM applies only to listed-peer multiples (existing 25 %).
- **Startup DCF / VC discount rates** replace CAPM when the business is pre-profit: idea/pre-seed 60 %, seed 50 %,
  Series A 40 %, Series B+ 30 %, profitable SME → CAPM WACC (sources above: 40–60 % early stage; 20–35 % VC IRR
  targets overall).
- Snapshot these numbers as a **dated dataset** `agents/data/market/2026-09-26.json` (value, unit, as_of, source URL,
  sha256 of the downloaded Damodaran file). Refresh: Damodaran each January, rf monthly (manual PR, never live
  scraping at valuation time — reproducibility). Damodaran's data is freely published for use; cite it on the page.

### 2.4 Projection uploads — standards and regulatory labelling

- ASIC RG 170: prospective financial information needs **reasonable grounds**; ranges of forecasts are discouraged in
  disclosure documents; start-ups justify shorter horizons
  ([RG 170](https://www.asic.gov.au/regulatory-resources/find-a-document/regulatory-guides/rg-170-prospective-financial-information/),
  [PDF](https://download.asic.gov.au/media/1240943/rg170-010411.pdf)). → BlockID never *presents* the business's
  forecasts as its own; it states whose they are, that they are unaudited, and shows what the value is without them.
- Template fields follow a standard 3-statement / FCFF build (Anthropic `3-statement-model` and `dcf-model` skills):
  revenue, COGS, opex, EBITDA, D&A, EBIT, tax, capex, working capital, headcount, cash, debt.

### 2.5 How the current SVI maps onto the startup methods (no new LLM scoring needed for Scorecard)

| Payne factor (weight) | Source in BlockID (already human-confirmed at the gate) |
|---|---|
| Team 30 % | `founder_quality` (team report when linked) |
| Size of opportunity 25 % | `market_attractiveness` |
| Product / technology 15 % | `product_strength` |
| Competitive environment 10 % | RFS "competition" rating (agent, ai_suggested) → 50 + 25 × rating |
| Marketing / sales / partnerships 10 % | `revenue_performance` (0 revenue → Berkus "strategic relationships") |
| Need for additional investment 5 % | runway: `min(runway_months/24,1) × 100` |
| Other 5 % | mean(`investment_readiness`, `trust_verification`) |

Comparison factor per line = `0.5 + score/100` (score 50 = peer median = 1.0×), same convention as the SVI factor.

---

## 3. Method selection matrix (stage × data availability)

### 3.1 Stage classification (deterministic, stored with reasons)

`classify_stage(profile, metrics, evidence, projections) -> StageClass` in `tools/valuation_methods.py`:

| Class | Rule (first match) | Maps to `profile.stage` |
|---|---|---|
| `listed` | verified `Listing` + fresh market cap | any |
| `profitable_sme` | revenue > 0, EBITDA > 0 in last actual year (upload or self-reported `ebitda_margin_pct` > 0), YoY growth < 30 %, not VC-funded or funding < 1× revenue | new value `established` |
| `growth` (Series B+) | revenue ≥ A$10 M or priced round ≥ Series B | `growth` |
| `series_a` | revenue A$1–10 M or Series A anchor | `series-a` |
| `seed` | revenue > 0 and < A$1 M, or seed round | `seed` |
| `pre_seed` | no revenue, product live / prototype | `pre-seed` |
| `idea` | no revenue, no product | `idea` |

If the LLM-extracted `profile.stage` disagrees with the class by more than one step, add a review item ("stage looks
like Series A from revenue A$3.2 M; the website says seed") — the **admin sets the final stage** at the gate (audit
`valuation_stage_set`). The stage is part of the hashed inputs, so a stage change = a new valuation version.

Schema change: `StartupProfile.stage` Literal gains `"established"`; `svi.STAGE_PRE_REVENUE_RANGE` and
`STAGE_REVENUE_BENCHMARK` get an `established` row (benchmark only used when nothing else applies).

### 3.2 Base weights (raw weight before the evidence factor; 0 = not run)

| Method \ class | idea | pre-seed | seed | series_a | growth | profitable_sme | listed |
|---|---|---|---|---|---|---|---|
| `market_anchor` (own price, v3 rule) | kind × recency (v3) | same | same | same | same | same | market cap 3.0 |
| `scorecard` (Payne) | 1.0 | 1.0 | 0.6 | 0.2 | – | – | – |
| `berkus` | 0.8 | 0.8 | 0.3 (only if revenue < A$250k) | – | – | – | – |
| `rfs` | 0.8 | 0.8 | 0.5 | 0.2 | – | – | – |
| `vc_method` (needs projections or stage exit table) | – | 0.4 | 0.8 | 0.8 | 0.4 | – | – |
| `revenue_multiple` (trading comps, v3 rule) | – | – | 0.4 | 0.8 | 1.0 | 0.4 | 0.3 |
| `ebitda_multiple` (trading comps on EBITDA) | – | – | – | – | 0.3 (if EBITDA > 0) | **1.0** | 0.3 |
| `precedents` (transaction multiples) | – | – | – | 0.3 | 0.6 | **0.8** | – |
| `dcf` (FCFF; Gordon or exit TV) | – | – | 0.2 (First Chicago) | 0.4 (First Chicago) | 0.6 | **1.0** | 0.3 |
| `stage_scorecard` (v3 placeholder) | only when no scorecard inputs | 0.1 fallback | 0.1 | 0.1 | 0.1 | – | – |

"The three methods" the owner asked for, per stage:

- **Idea / pre-seed**: Scorecard + Berkus + RFS (+ own price if a round/SAFE cap is verified — dominant when fresh).
- **Seed**: Scorecard + VC method + revenue multiple (+ RFS as risk check).
- **Series A**: VC method + revenue comps + DCF (First Chicago scenarios).
- **Series B+ / growth**: revenue comps + precedents + DCF.
- **Profitable SME**: DCF + EBITDA comps + precedent transactions (the classic three pillars).
- **Listed**: market cap (≥ 90 % weight) with comps/DCF as a frame.

### 3.3 Evidence-quality factor (multiplies the base weight)

| Input basis | Factor |
|---|---|
| audited / filed accounts (upload flagged `audited` + document) | 1.0 |
| management accounts, actual years (upload) / verified cited revenue | 0.9 |
| founder self-reported figure | 0.8 |
| management projections, all sanity checks pass | 0.7 |
| management projections with warnings (capped values used) | 0.4 |
| multiple from ≥ 3 verified comps / precedents | 1.0; 1–2: 0.8; cited sector range: 0.7; Damodaran industry table: 0.6; default table: 0.25 |
| AI-suggested factor ratings not yet confirmed | 0.5 (becomes 1.0 after the gate) |

Method raw weight = base × Π(factors of its inputs). Then: (1) outlier rule — a method > 3× from the weighted median
of the others gets weight 0 and a note (IVS 105 "investigate, don't average"); v3's 5× stage rule stays for
`stage_scorecard`; (2) normalise; (3) anchor calibration — when a fresh (≤ 12 m) priced round exists, show for each
fundamental method the implied multiple / discount rate that would reproduce the anchor (information, not weight).

---

## 4. Engine design (deterministic)

### 4.1 Files

| File | New / changed | Content |
|---|---|---|
| `tools/valuation_methods.py` | **new** (~600 lines) | Pure functions, floats, no I/O, no LLM. Each returns `ValuationMethod(method, label, value_aud, low_aud, high_aud, raw_weight, inputs, sources, notes)` with `inputs` sufficient to rebuild it. |
| `tools/valuation_params.py` | **new** | `PARAMS = {"v5": MappingProxyType({...})}` — base weight matrix, evidence factors, Berkus caps, RFS step, scorecard bases, stage discount rates, VC target multiples, growth / margin caps, terminal-g cap, TV share warning, outlier ratio, range half-widths. Frozen; changing anything = new key `v5.1`; every report stores `params_version`. |
| `agents/data/market/2026-09-26.json` | **new** | Dated market dataset (§2.3) + Damodaran industry rows (beta_unlevered, EV/Sales, EV/EBITDA, operating margin — Aus/NZ + emerging + global) for ~94 industries; source URLs + sha256 of the source files. Loader `tools/market_data.py` returns an immutable snapshot and its id. |
| `tools/triangulate.py` | changed | `VERSION = "v5"` for new reports; `blend_v5(methods, stage_class, params)`; `triangulate_v5(...)`; `recompute()` dispatches on `tri["version"]` (v3 path untouched) and on `method` via `METHOD_REGISTRY` (`name -> rebuild(inputs, params) -> ValuationMethod`). |
| `tools/svi.py` | changed | `FORMULA_VERSION = "v5"`, `TRIANGULATION_VERSION = "v5"`; `apply_triangulation` unchanged in shape. |
| `studio/verify.py` | changed | Candidate `("v5", _range_v5(tri))` when `tri.version == "v5"`; `formula()` adds `params_by_version` and the dataset id; `VALUATION_METHOD` text gains a v5 paragraph. |
| `schemas.py` | changed | see §4.4. |
| `config.py` | changed | `VALUATION_V5` flag, `VALUATION_PARAMS_VERSION="v5"`, `MARKET_DATASET="2026-09-26"`, projection limits. |

### 4.2 Function signatures (all pure)

```python
# tools/valuation_methods.py
def wacc(rf, beta_u, erp, crp, size_premium, tax_rate, debt_to_equity=0.0, kd_pre_tax=None) -> dict
def fcff_series(years: list[ProjectionYear], tax_rate) -> list[dict]        # EBIT(1-t)+D&A-capex-ΔNWC per year
def dcf(fcff: list[float], rate: float, *, terminal: Literal["gordon","exit"], g: float | None,
        exit_multiple: float | None, final_ebitda: float | None, mid_year=True,
        net_debt_aud=0.0) -> ValuationMethod              # EV and equity value; low/high from the sensitivity grid
def dcf_checks(rate, g, tv_share, fcff) -> list[Check]   # ported from Anthropic dcf-model skill + ours
def sensitivity(fcff, rate, g, *, d_rate=0.02, d_g=0.01) -> list[list[float]]  # 5x5, centre = base
def first_chicago(scenarios: list[tuple[str, float, float]]) -> ValuationMethod  # (name, probability, value)
def trading_comps(metric_value_aud, multiples: list[float], basis: Literal["revenue","ebitda"],
                  dlom: float, sources) -> ValuationMethod    # 25th/median/75th -> low/mid/high
def precedents(metric_value_aud, deals: list[DealMultiple], basis) -> ValuationMethod  # no DLOM, recency-weighted median
def vc_method(exit_metric_aud, exit_multiple, years_to_exit, target_multiple | target_irr,
              retention=1.0, investment_aud=0.0) -> ValuationMethod   # pre-money; low/high from target band
def scorecard(base_pre_money_aud, factors: dict[str, float], weights) -> ValuationMethod
def berkus(scores: dict[str, float], cap_per_factor_aud) -> ValuationMethod   # 5 × (score/100 × cap)
def rfs(base_pre_money_aud, ratings: dict[str, int], step_aud) -> ValuationMethod  # 12 × rating × step, floor 0.2×base
def classify_stage(...) -> StageClass
def select_methods(stage_class, available: set[str], params) -> dict[str, float]  # base weights
```

Rules worth fixing now:

- **Units**: AUD, whole-currency floats; round only at the end (`round(x, -3)` like v3). FX via `config.FX_TO_AUD`
  (projection currency must be in the table; rate + `FX_TO_AUD_AS_OF` recorded).
- **DCF guards** (from the Anthropic `dcf-model` skill, Apache-2.0): `g >= rate` → method not run (error note);
  `rate` outside 5–20 % for CAPM-WACC → warning (VC-style rates are allowed up to 70 %, labelled);
  TV share > 75 % → warning and evidence factor × 0.8; negative terminal FCFF → Gordon not run (exit multiple only).
  Terminal g ≤ min(3 %, rf) (AU nominal long-run); mid-year convention (TV discounted at N − 0.5 for Gordon,
  N for exit multiple).
- **Range per method**: DCF low/high = the grid cells at (rate + 2 pp, g − 1 pp) and (rate − 2 pp, g + 1 pp);
  comps/precedents = 25th/75th percentile (min 2 points; one point → ×0.7/×1.4 like v3); startup methods = ±25 %
  (Scorecard/RFS) or the factor band; VC = target multiple band (e.g. seed 20×–30×).
- **Equity bridge**: equity = EV − net debt (from upload; 0 with a note when unknown). Pre-money = equity value
  before the new raise; post-money = pre + raise (shown in §7).
- **Blend** = Σ wᵢ × valueᵢ; range = Σ wᵢ × lowᵢ / highᵢ widened to `RANGE_MIN_HALF_WIDTH[confidence]`
  (unchanged v3 behaviour). Confidence v5: high = fresh anchor carrying ≥ 50 % and methods within 2×, or ≥ 2
  fundamental methods on actual (non-projected) data within 1.5× with ≥ 3 verified comps/deals; medium = any
  anchor, or one fundamental method on verified data; low otherwise. Reasons in plain words (existing style).

Worked example (profitable SME, for tests; A$ M): revenue 5.0 → 15 % growth for 5 years (5.75 … 10.06), EBITDA
margin 20 %, D&A 3 %, capex 3.5 %, NWC 10 % of Δrevenue, tax 25 %; Ke = 5.39 % + 0.9 × 6 % + 4 % = **14.79 %**
(no debt). FCFF 0.63 / 0.72 / 0.83 / 0.96 / 1.10. PV(FCFF, mid-year) 2.95; Gordon TV (g 2.5 %) 9.18 → PV 4.94;
**EV 7.88** (TV 63 % ✓). Exit-multiple TV at 5× EBITDA 2.01 → 10.06 → PV 5.05; EV 7.99. EBITDA comps: LTM EBITDA
1.0 × 5.0× × (1 − 25 %) = 3.75; precedents (AU SME 4.5×, no DLOM) = 4.5. → The football field shows DCF well above
the multiples because it prices in 15 % growth — exactly the divergence the reviewer must see (DCF weight falls if the
growth is a projection with warnings).

### 4.3 Formula versioning and `/verify`

- `svi.triangulation.version = "v5"`, `params_version = "v5"`, `market_dataset = "2026-09-26"`.
- Each method's `inputs` contains **the numbers used** (rf, β, ERP, CRP, premium, tax, FCFF list, g, exit multiple,
  multiples list, factor scores, base pre-money …), not references — so `/verify` recomputes without the dataset
  file; `params` only supplies rules (caps, weights) and is public in `formula()["params_by_version"]`.
- `recompute(tri)`: rebuild each method via `METHOD_REGISTRY`, re-blend with `PARAMS[tri.params_version]`, compare
  low/mid/high at A$1,000 (as today). Old v3 reports: untouched v3 path; version detection order in verify becomes
  v5 → v3 → v2 → v1b → v1. Reported formula version = `v5` (valuation rules) + `weights_version` v4 (dimension weights).
- Report hash unchanged in construction (`REPORT_KEYS`); projections used are copied into `dcf.inputs` (the rows, not
  the file) and the file's sha256 is in `inputs.projection_sha256`, so the on-chain hash commits to them.
- `POST /v1/verify/hash` works for v5 reports with no change.

### 4.4 Schemas (`schemas.py`)

```python
MethodName = Literal["market_anchor","revenue_multiple","stage_scorecard",           # v3
                     "ebitda_multiple","precedents","dcf","vc_method","scorecard","berkus","rfs","first_chicago"]
class ValuationMethod(BaseModel):  # method: MethodName (extended Literal); + checks: list[Check] = []
class Check(BaseModel): code: str; severity: Literal["error","warning","info"]; message: str
class StageClass(BaseModel): cls: Literal["idea","pre_seed","seed","series_a","growth","profitable_sme","listed"];
                             reasons: list[str]; set_by: Literal["code","admin"] = "code"
class Triangulation(BaseModel):  # + params_version: str = ""; market_dataset: str = ""; stage: StageClass | None
                                 # + football_field: list[FieldBar] = []; tokenisation: TokenisationProposal | None
class FieldBar(BaseModel): method: str; label: str; low_aud: float; mid_aud: float; high_aud: float; weight: float
# projections
class ProjectionYear(BaseModel): year: int; actual: bool; revenue: float; cogs: float; opex: float; d_and_a: float;
    capex: float; nwc: float | None; change_nwc: float | None; tax: float | None; headcount: int | None; ...
class ProjectionSet(BaseModel): currency: str; fiscal_year_end: str; basis: Literal["management_projection"];
    years: list[ProjectionYear]; net_debt: float = 0; cash: float = 0; shares_fd: int | None; planned_raise: float = 0;
    source_sha256: str; uploaded_by: str; uploaded_at: str; checks: list[Check]; attested: bool = False
# agent LLM outputs (ai_suggested, verified by code)
class IndustryPick(BaseModel): industry: Literal[<Damodaran industry names>]; rationale: str
class StartupFactors(BaseModel): berkus: dict[BerkusKey, FactorScore]; rfs: dict[RfsKey, RfsRating]; competition: RfsRating
class DealClaim(BaseModel): target: str; acquirer: str; ev: float | None; revenue: float | None; ebitda: float | None;
    multiple: float | None; basis: Literal["revenue","ebitda"]; currency: str; date_text: str; source_url: str; quote: str
class TokenisationProposal / ValuationFinal  -> §7
```

`web/app/src/components/ValuationMethods.tsx` mirrors the TS types (extend the `method` union).

---

## 5. The Valuation Agent

### 5.1 Where it runs

New graph node `valuation_methods` in `graph.py` between `valuation` (SVI + v3 triangulation) and `gate_valuation`,
in both `build_onboarding` and `build_site_valuation`; a stored valuation can also be re-run deterministically
(no LLM, no web) when projections or admin assumptions change (`rerun_methods(vid)` → like `apply_team_score`).
Behind `VALUATION_V5` (0 = today's behaviour exactly).

### 5.2 Inputs

Profile + metrics (+ `metrics_sources`), SVI dimension scores, `valuation_evidence` (anchors, comps, sector
multiples, listing), `market` (incl. `company_financials`), confirmed projections (`ProjectionSet`), KPI history
(`studio.kpi_values`, for companies that already exist — revenue actuals override projections for past periods),
team report score, the dated market dataset.

### 5.3 What the LLM does (and never does)

| Call | Profile | Output | Verified / confirmed by |
|---|---|---|---|
| 1. Industry mapping | `extract_json` | `IndustryPick` (enum of Damodaran industries) + rationale | Code picks β / multiples / margin band from the dataset; admin can change at the gate. Fallback: keyword map (existing `SAAS_FINTECH_TERMS` style). |
| 2. Startup factors (only idea → series_a) | `extract_json` | Berkus 5 scores 0–100, RFS 12 ratings −2…+2, competition rating — each with evidence URLs from stored evidence | ai_suggested → weight factor 0.5 until the admin confirms/overrides at the gate (same flow as `QualitativeScores`). URLs not in stored evidence are dropped (existing rule). |
| 3. Precedent deals (only series_a+ with revenue/EBITDA) | `extract_json` | `DealClaim[]` from stored pages | Code keeps a deal only if the quote is verbatim on the page, states the number, has a date on the page, currency in the FX table, multiple within `MULTIPLE_BOUNDS` (EBITDA: 1–40×). Same helpers as `market_evidence.py` (`amount_in_quote`, `parse_as_of`). |

Never: produce a value, weight, discount rate, multiple it did not quote, or edit projections. No personal names
are sent (existing `redact`).

### 5.4 Search budget

No new cap. Add purpose `precedents` to `tools/search.py` `QUERY_PLAN` **inside the existing hard cap of 8**:
`"<sector> acquisition EV/EBITDA multiple <country> <year>"` (EBITDA > 0) or `"<sector> acquired revenue multiple
<year>"` (revenue only), run only for series_a / growth / profitable_sme and only when a slot remains
(`comps_named` is dropped for profitable SMEs to free it). ≤ 3 pages, 72 h cache, logged in `searches`.

### 5.5 Model profile and cost

- `extract_json` on the existing valuation chain (SambaNova DeepSeek-V3.1 / gpt-oss-120b free → Claude bridge →
  DeepInfra V4-Flash). Industry mapping may pin `claude-bridge` first via `AI_PROFILE_EXTRACT_JSON` only if the
  benchmark shows free models mis-map (> 20 % disagreement on the golden set).
- Budget per valuation: ≤ 3 calls, ≤ ~12k input tokens each. Cost: **US$0** on SambaNova; worst case DeepInfra
  V4-Flash ≈ 3 × (12k × 0.09 + 1.5k × 0.18)/1e6 ≈ **US$0.004**. Adds ~15–30 s.
- Add the three schemas to `scripts/ai-benchmark.py` golden set (8 backtest companies + 5 SMEs).

### 5.6 Admin gate changes

`POST /v1/studio/valuations/{vid}/decision` body gains optional `stage`, `industry`, `startup_factors`
(overrides), `assumptions` (see §8.3). Approval recomputes v5 with basis "human" for everything confirmed.

---

## 6. Projection upload flow

### 6.1 Template (download)

`GET /v1/studio/projection-template?format=xlsx|csv&lang=en|vi` — generated by openpyxl at build time and
served statically (`web/app/public/templates/blockid-projections-v1.xlsx` + `.csv`), versioned `template_version: 1`.

Sheet `Projections` — one column per fiscal year (up to 3 actual + 5 projected), rows:

| Row key | Label | Required | Notes |
|---|---|---|---|
| `year` | Fiscal year ending (YYYY) | ✓ | consecutive |
| `actual` | Actual (A) / Projection (P) | ✓ | ≥ 3 P years; A recommended |
| `revenue` | Revenue | ✓ | ≥ 0 |
| `cogs` | Cost of sales | ✓ | ≥ 0 |
| `opex` | Operating expenses (excl. D&A) | ✓ | ≥ 0 |
| `ebitda` | EBITDA | computed | if given, must equal revenue − cogs − opex ± 1 % |
| `d_and_a` | Depreciation & amortisation | ✓ | ≥ 0 |
| `tax` | Income tax paid | optional | default = max(EBIT, 0) × country rate |
| `capex` | Capital expenditure | ✓ | ≥ 0 |
| `nwc` | Net working capital (balance) or `change_nwc` | one of | default 10 % of Δrevenue, flagged |
| `headcount` | Employees (FTE) | optional | revenue/FTE check |
| `customers` | Paying customers | optional | |

Sheet `Company`: currency (AUD/USD/VND/…), fiscal year end, cash, debt, shares on issue (fully diluted), planned
raise, audited (Y/N), prepared by, basis notes (free text, never parsed as numbers). Sheet `Guide`: plain-words help
EN/VI.

### 6.2 API

| Method | Path | Who | Behaviour |
|---|---|---|---|
| GET | `/v1/studio/projection-template` | anyone signed in | xlsx/csv |
| POST | `/v1/studio/valuations/{vid}/projections` | owner / admin | `multipart/form-data` (`file`), ≤ 512 KB, `.xlsx` or `.csv` only (`.xlsm`/`.xls` rejected), sniff magic bytes; parse → `ProjectionSet` + `checks`; stores **draft**; returns checks. Rate-limit 10/day/valuation. |
| GET | `/v1/studio/valuations/{vid}/projections` | owner / admin / viewers of a listed company (summary only) | latest + history |
| POST | `/v1/studio/valuations/{vid}/projections/{pid}/confirm` | owner | `{attest: true}` — "These are our management's projections, prepared with reasonable care. I understand BlockID does not verify them." → `confirmed`; triggers deterministic `rerun_methods` (status back to `waiting_approval` if it was approved and the value moves > 5 %) |
| DELETE | `/v1/studio/valuations/{vid}/projections/{pid}` | owner (draft only) | |

Alternative for mobile / no spreadsheet: a small in-page grid (same fields, 3–5 columns) posting JSON to the same
endpoint (`application/json`), same validation.

### 6.3 Storage

```sql
CREATE TABLE IF NOT EXISTS studio.valuation_projections (
  id serial PRIMARY KEY, valuation_id text NOT NULL REFERENCES studio.valuations(id) ON DELETE CASCADE,
  company_id int REFERENCES studio.companies(id), status text NOT NULL,          -- draft | confirmed | superseded
  filename text, content_type text, size_bytes int, sha256 text NOT NULL, file bytea,   -- original kept for audit
  parsed jsonb NOT NULL, checks jsonb NOT NULL DEFAULT '[]', template_version int,
  uploaded_by text NOT NULL, attested_by text, attested_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS valuation_projections_vid ON studio.valuation_projections (valuation_id, created_at DESC);
```

Parsed rows are also copied into `result.svi.triangulation.methods[dcf|vc_method|first_chicago].inputs` so the report
hash covers them. Audit events: `projection_uploaded`, `projection_confirmed`, `projection_rejected`.

### 6.4 Parsing and validation (no LLM — the "package-reader" tier)

`tools/projections.py`: `parse_xlsx(bytes)` (openpyxl `read_only=True, data_only=True`, first 3 sheets, max 200
rows × 20 cols; formulas read as cached values — if a formula cell has no cached value → error "save the file in
Excel before uploading"); `parse_csv(bytes)`; `validate(ps, stage_class, industry) -> list[Check]`.

| Check | Severity | Rule (params v5) | Message (EN, plain words) |
|---|---|---|---|
| structure | error | ≥ 3 projected years, consecutive, required rows present, numbers finite | "Row 'capex' is missing for 2028." |
| identity | error | EBITDA (if given) = revenue − COGS − opex ± 1 % | "EBITDA 2027 doesn't add up: 1.2 M given, 1.05 M from the rows above." |
| currency | error | in `FX_TO_AUD` | "Currency XYZ isn't supported." |
| growth cap | warning → capped | Y1 growth over last actual: idea/pre-seed ≤ 300 %, seed ≤ 200 %, Series A ≤ 150 %, growth ≤ 80 %, SME ≤ 25 %; each later year ≤ previous year's cap × 0.8 | "Revenue grows 400 % in 2027; we used 200 % (seed limit)." |
| jump from actual | warning | Y1 revenue > 3× last actual (or > 1.5× for SME) | |
| gross margin | warning | outside sector band (SaaS 55–90 %, marketplace 10–80 %, services 20–60 %, hardware 15–55 %, retail 15–50 %, other Damodaran margin p10–p90) | |
| terminal EBITDA margin | warning → capped | ≤ Damodaran industry operating margin p90 + 10 pp | "EBITDA margin 65 % in 2030 is above what listed peers reach (35 %); we used 45 %." |
| revenue / FTE | info/warning | > 3× industry norm | |
| capex vs D&A | warning | long-run capex < 50 % of D&A | |
| tax | info | defaulted | |
| actuals mismatch | warning | last actual revenue differs > 20 % from self-reported / KPI / cited revenue | "Your 2026 actual revenue (2.0 M) differs from the revenue on your valuation (1.2 M)." |
| hockey stick | warning | ≥ 80 % of cumulative 5-year FCFF in the last year, or TV share > 75 % | |

Effect: errors block confirmation; warnings apply the cap and set the evidence factor 0.4 (instead of 0.7); the
result card shows the uncapped DCF as a grey tick ("your forecast as uploaded") next to the used value.

Security: size cap before parsing; zip-bomb guard (reject if uncompressed > 20 MB — check `zipfile` infolist
before openpyxl); `defusedxml` installed; never evaluate formulas; strip control chars; free-text fields
length-capped and never sent to an LLM with tools; CSV export of projections escapes leading `= + - @`
(formula injection).

### 6.5 Label

Everywhere a value uses projections: **"Based on management projections (unaudited, not verified by BlockID)."**
The football field also shows the value **without** projection-based methods, so an investor sees what the forecast
adds. Pack (`offerings.py` `information pack`) includes the projection sha256, who attested and when.

---

## 7. Outputs for tokenisation

### 7.1 `TokenisationProposal` (computed, inside `svi.triangulation.tokenisation`, hashed)

```
pre_money_aud          = blended equity value (mid) — for a listed company: market cap
range_aud              = [low, high] of the blend
fd_shares_existing     = company.total_shares (+ granted-not-issued + pools when EQUITY-STRUCTURE exists) or
                         ProjectionSet.shares_fd, else None (new company)
price_per_share_aud    = pre_money / fd_shares_existing, 4 dp        (existing company)
                       = stage default price (below) and share count = round(pre_money / price)   (new company)
offer_price_range_aud  = [low / fd, mid / fd]  — recommended offer price = mid / fd; price above high / fd is BLOCKED,
                         above mid × 1.2 flagged (existing PRICE_WARN)
raise_aud (optional)   = ProjectionSet.planned_raise → new_shares = raise / price; post_money = pre + raise;
                         dilution = new / (fd + new)
```

Default price per share for a **new** company (so share counts look like real cap tables and stay integers with
enough granularity for small investors): idea / pre-seed **A$0.10**, seed **A$0.25**, Series A **A$1.00**, growth
**A$1.00**, profitable SME **A$1.00** (current behaviour), listed → market price. Rounded share count to a "clean"
number (e.g. 3 significant figures) with the price re-derived to 4 dp. Bounds: 10,000 ≤ shares ≤ 10¹⁵ (existing).
Owner decision #1 (§12).

### 7.2 Finalise → `ValuationFinal`

`POST /v1/studio/valuations/{vid}/finalise` (owner or platform admin; valuation `approved`; confidence ≠ `low` unless
admin ticks "allow low confidence" with a reason): freezes `{pre_money_aud, low_aud, high_aud, price_per_share_aud,
total_shares, offer_price_low/high, stage, params_version, report_hash, finalised_by, finalised_at, valid_until =
+12 months (or +6 months for idea/pre-seed)}` into `studio.valuations.final` (new jsonb column) + audit
`valuation_finalised`. Re-finalising requires a new approval.

Sync rules:

- `POST /v1/studio/companies`: if `valuation.final` exists, default `share_price_aud` and `total_shares` come from it
  and `valuation_aud = final.pre_money_aud` (today: `valuation_mid` / A$1). A caller-supplied different price is
  allowed only within the offer price range (422 otherwise). No `final` → today's behaviour + a warning in the UI
  ("finalise the valuation first") while `VALUATION_V5_REQUIRE_FINAL=0`; set to 1 after rollout.
- `offerings.py`: defaults `price_aud = final.price_per_share_aud` when newer than the latest mark; **submit blocked**
  (409 with plain reason) when `final` is expired, the stage class changed since, a newer approved valuation exists,
  or the latest KPI revenue deviates > 25 % from the revenue used (then "revaluation needed"). Pack gains
  `valuation.final` + football-field bars + "based on management projections" flag.
- Admin `revalue` (`/v1/admin/companies/{cid}/revalue`): unchanged manual path, but the UI proposes the v5 value and
  records `source='valuation_v5'` in `studio.marks` when accepted.
- Equity structure plan (`docs/EQUITY-STRUCTURE-PLAN.md` §6, priced round "price per share default = latest approved
  fair value per share") uses `final.price_per_share_aud`.

---

## 8. UI

### 8.1 "How we reached this value" (Valuation page, Company page, offering pack, /verify)

- **Football field** (`web/app/src/components/FootballField.tsx`, inline SVG, no chart library — the app has none):
  one horizontal bar per method (low → high, tick at mid, label "DCF · 32 %"), methods with weight 0 greyed with the
  reason on hover/tap; vertical line = blended value; shaded band = final range; diamond = offer price; optional grey
  tick for "your forecast as uploaded". Log scale when max/min > 20. Accessible table fallback below the chart; works
  at 360 px width (bars stack, labels above).
- **Method tabs**: Overview · Own price · Revenue multiple · EBITDA multiple · Deals · DCF · Startup methods
  (Scorecard / Berkus / Risk factors) · VC method. Each tab: inputs table (value, source link or "self-reported" /
  "management projection" / "BlockID parameter v5"), checks (errors/warnings in plain words), notes.
- **DCF tab**: FCFF table by year (A/P columns), discount rate build-up (rf, β, ERP, country, size premium),
  terminal method, TV share gauge, **5 × 5 sensitivity grid** (rate × g) with centre = base (skill convention).
- Public copy: plain words, no "AI" (owner rule); "indicative value, not a formal valuation or financial advice";
  EN/VI strings in `web/app/src/dict.valuation.ts`.

### 8.2 Projection upload

Valuation page card "Add your forecast (optional)" (also a step in `NewWizard.tsx`): Download template (xlsx / csv)
→ drop file → checks list with row/year pointers (errors red, warnings amber with "we used X") → attestation checkbox
→ Confirm → value re-computes; the football field animates old → new.

### 8.3 Admin-editable assumptions with audit

`PATCH /v1/admin/valuations/{vid}/assumptions` (platform admin; `{changes: {path: value}, reason (≥ 10 chars)}`),
whitelisted paths: `stage`, `industry`, `dcf.rf|beta_u|erp|crp|size_premium|tax_rate|g|terminal|exit_multiple`,
`vc.target_multiple|years_to_exit|exit_multiple`, `scorecard.base_pre_money`, `berkus.*`, `rfs.*`,
`weights.<method>` (override, ≤ 2× the rule weight, reason required), `dlom`. Each change: bounds-checked (same
`Check` rules), stored in `studio.valuation_assumption_changes (id, valuation_id, path, old, new, reason, actor, at,
version)`, audit `valuation_assumption_changed`, recompute → new result version (old kept in `result.history[]`),
status back to `waiting_approval`; if the valuation is already **finalised**, a second admin must approve (reuse
`CompanyAuthz` four-eyes pattern). The method card shows "Adjusted by admin: g 2.5 % → 2.0 % — reason …".

---

## 9. Backtest plan and acceptance criteria

### 9.1 Sets

1. **Existing 8** (`docs/valuation-reference.md`): Canva, Airwallex, SafetyCulture, Go1, Airtasker, Employment Hero,
   Culture Amp, Linktree — offline fixtures + live run.
2. **Profitable AU SMEs (new, 5–8 cases)** chosen in Phase 0 by a rule, not by hand-picking outcomes:
   (a) private Australian businesses acquired by ASX-listed acquirers where the announcement discloses the price
   **and** revenue/EBITDA (ASX announcements are primary sources); (b) 3 profitable ASX micro-caps (market cap
   < A$150 M, positive EBITDA 2 years) valued *as if private* (market cap is the reference; the engine gets no
   listing). Record page, date and figures in `docs/valuation-reference.md` with the same table layout.
3. **Startup cases (3)**: AU seed / Series A rounds with a disclosed post-money (Startup Daily / SmartCompany), valued
   with the round hidden (ablation) to test Scorecard/VC calibration.
4. **Projection fixtures**: synthetic good / hockey-stick / broken files for each stage.

### 9.2 Runs

`scripts/valuation-backtest.py --v5 [--ablation] [--live]`: columns per method (value, weight), blended error,
in-range, confidence; ablations: without own price, without projections, v3 vs v5.

### 9.3 Acceptance criteria

| # | Criterion | Target |
|---|---|---|
| A1 | Live median \|error\|, 8 reference companies | ≤ 25 % (v3 today 25.8 %) — no regression; in range ≥ 5/8 |
| A2 | Offline "without own price" median \|error\| | ≤ 45 % (v3 today 60.6 %) |
| A3 | Profitable SMEs, fundamentals only (DCF + EBITDA comps + deals) | median \|error\| ≤ 30 %, reference inside range ≥ 60 % |
| A4 | Startup cases, round hidden | median \|error\| ≤ 50 % (honest target for Scorecard/VC; shown as low/medium confidence) |
| A5 | Determinism | `/verify` recompute == stored for 100 % of v5 fixtures; v1–v4 fixtures still match (existing `test_verify.py`) |
| A6 | Projection sanity | every hockey-stick fixture triggers ≥ 1 warning and its DCF weight ≤ 0.4 × base |
| A7 | Cost / latency | ≤ 3 extra LLM calls, ≤ 8 searches total, ≤ +30 s p50; US$0 on free tier |
| A8 | Tokenisation | company creation / offering defaults equal `ValuationFinal`; stale or stage-changed final blocks offering submit |
| A9 | UI | football field renders at 360 px and in dark mode; EN/VI complete; no "AI" in public copy |

---

## 10. Phased tasks (files, endpoints, schemas, tests)

All behind `VALUATION_V5=0` until Phase 6.

**Phase 0 — decisions + data (1.5 d)**
- Owner decisions §12. Build `agents/data/market/2026-09-26.json` (rf AU/VN, ERP, CRP, Damodaran Jan-2026 industry
  rows from `betaRest/psRest/vebitdaRest/marginRest/*emerg`), `tools/market_data.py` loader + sha256.
- Select SME + startup backtest cases (§9.1), record in `docs/valuation-reference.md`; fixtures in
  `scripts/fixtures/valuation-backtest.json`.
- Calibrate scorecard base pre-money per stage (AU): from Cut Through median round sizes / dilution; keep
  `STAGE_PRE_REVENUE_RANGE` for v3.

**Phase 1 — engine (4 d)**
- `tools/valuation_methods.py`, `tools/valuation_params.py`, `blend_v5` / `triangulate_v5` / `recompute` dispatch in
  `tools/triangulate.py`; `schemas.py` (§4.4); `svi.FORMULA_VERSION="v5"` guarded by flag.
- `studio/verify.py` v5 candidate + `formula()`; `web/app/src/pages/Verify.tsx` shows v5 methods.
- Tests `agents/tests/test_valuation_methods.py`: DCF known answers (worked example §4.2 to A$1k; numpy-financial
  `npv` as oracle in dev extras), Gordon vs exit, mid-year, g ≥ rate refusal, TV-share warning, sensitivity centre
  == base, comps quartiles, DLOM only on listed multiples, precedents recency, VC method (multiple and IRR forms,
  retention), Scorecard mapping from SVI dims, Berkus cap, RFS floor, First Chicago probabilities sum to 1,
  stage classifier table-driven, selection matrix, evidence factors, outlier exclusion, confidence reasons;
  `test_verify.py`: v5 round-trip + all old versions unchanged; property test: `recompute(tri) == tri` for random
  valid inputs (hypothesis optional).

**Phase 2 — projections (3 d)**
- `tools/projections.py` (parse + validate), template generator `scripts/make-projection-template.py` →
  `web/app/public/templates/`, `studio/projections.py` router (endpoints §6.2), `schema.sql` table §6.3, `config`
  limits, `pyproject.toml` + `openpyxl`, `defusedxml`.
- Tests `test_projections.py`: good xlsx/csv, each check, caps applied, `.xlsm` rejected, zip bomb, formula without
  cached value, 513 KB rejected, currency, attestation required, permission (not owner → 403), rerun on confirm,
  CSV formula-injection escaping.

**Phase 3 — agent (3 d)**
- `agents/valuation_agent.py` (industry pick, startup factors, deal claims + verification reusing
  `market_evidence` helpers), `tools/search.py` purpose `precedents`, `graph.py` node `valuation_methods` (both
  graphs, progress step "Checking value with standard methods"), `agents/valuation.py` gate overrides extended,
  `rerun_methods(vid)` for deterministic reruns, `fakes.py` fixtures, `scripts/ai-benchmark.py` golden cases.
- Tests `test_valuation_agent.py`: LLM never sets numbers (fake returns a value → ignored), unknown URLs dropped,
  deal quote verification, budget ≤ 8 searches incl. `precedents`, flag off → identical v3 output (hash equality).

**Phase 4 — tokenisation (2.5 d)**
- `TokenisationProposal` computation; `POST /v1/studio/valuations/{vid}/finalise`; `studio.valuations.final` column;
  `routes.create_company` defaults + range check; `offerings.py` defaults, staleness / stage / KPI-deviation blocks,
  pack fields; `NewWizard.tsx` share step shows proposal.
- Tests: `test_studio.py` (create company from final; price outside range 422), `test_offerings.py` (default price,
  expired final 409, stage change 409, KPI deviation 409, pack contains final + projections flag).

**Phase 5 — UI (3.5 d)**
- `components/FootballField.tsx`, method tabs + DCF sensitivity in `ValuationMethods.tsx`, projection card
  (Valuation page + wizard), admin assumptions editor (`Admin.tsx` valuation review) with reason + diff + history,
  `PATCH /v1/admin/valuations/{vid}/assumptions` + table `studio.valuation_assumption_changes`, `dict.valuation.ts`
  EN/VI, `mock.ts` data for the demo mode.
- Tests: API tests for assumption edits (bounds, reason, four-eyes when finalised, audit row); `npm run typecheck`;
  screenshots at 360 / 1280 px light + dark (`scripts/screenshots`).

**Phase 6 — backtest, docs, rollout (2 d)**
- Offline + live backtest (§9), update `docs/valuation-reference.md`, `docs/LLM-ROUTING.md` (new calls, budget),
  `docs/FEATURES.md`, `docs/USER-GUIDE.md`; enable `VALUATION_V5=1` on the worker; existing companies keep their
  v3/v4 reports (no silent revaluation) — the admin can re-run to v5 per company.

**Phase 7 (optional) — Excel model export (1.5 d)**
- Admin/owner "Download model (.xlsx)" with live formulas following the Anthropic `dcf-model` / `comps-analysis`
  conventions (openpyxl writer, blue inputs, sensitivity grid), Apache-2.0 attribution; test that Excel-free
  recalculation (openpyxl can't compute) is validated by comparing a LibreOffice headless recalculation in CI.

Total ≈ 18–22 dev-days.

---

## 11. Risks and mitigations

| Risk | Mitigation |
|---|---|
| **Regulatory — "valuation" read as advice or an expert report** (AU: financial product advice / general advice; ASIC RG 170 reasonable grounds for forecasts; not an independent expert report; VN Securities Law 2019 for public offers) | Label every value "indicative, not a formal valuation or financial advice"; say whose projections they are and that BlockID does not verify them; never "recommend" investing — "suggested price per share for your offering" addressed to the issuer; offerings stay simulated on testnet (existing); legal review before any real-money offering. Owner decision on wording (FACTS.md word rule). |
| **Garbage / hockey-stick projections** | Deterministic checks and caps (§6.4), weight 0.4 on warnings, value-without-projections shown alongside, actuals-vs-KPI mismatch check, attestation with audit, KPI updates trigger "revaluation needed". |
| **Double counting discounts** (DLOM + size premium + stage rate) | One place per method (DLOM only on listed multiples; size premium only in CAPM DCF; VC rates already include illiquidity); unit tests assert it. |
| **Stale market parameters** (AU 10-y at 5.4 % is a 15-year high; Damodaran is January data) | Dated dataset, `market_dataset` id on each report, monthly rf refresh PR, sensitivity grid shows ±2 pp; ops check warns when the dataset is > 45 days old. |
| **Placeholder startup bases** (Scorecard / RFS base pre-money not calibrated for AU) | Phase 0 calibration; labelled "BlockID parameter v5 (calibrating)"; confidence capped at medium when a startup method carries > 50 % weight. |
| **LLM mis-mapping industry / inventing deals or factor ratings** | Enum industry list, quote verification for deals, ai_suggested factor weight 0.5 until human confirmation, dropped-claim list shown to admin. |
| **Verify / hash compatibility** | `REPORT_KEYS` unchanged; v5 data inside `svi.triangulation`; version detection order; old fixtures in CI. |
| **Gaming by the founder** (upload → value jumps → finalise → offer) | Any projection change after approval sends the valuation back to `waiting_approval`; finalise needs an approved valuation; price above the range is blocked. |
| **Spreadsheet attacks** (XXE, zip bomb, macros, formula injection) | §6.4 security list; no LLM with tools ever reads the file (package-reader isolation idea from Anthropic `valuation-reviewer`). |
| **Complexity for small businesses** | Upload is optional; wizard defaults; football field + one sentence per method; everything technical in tabs. |
| **Divergent methods confuse investors** | IVS-style rule: outliers excluded with a written reason; confidence and reasons shown; range, not a point, in public copy. |
| **Vietnam specifics** (VND cash flows, CRP, 20 % CIT, private JSC placement rules) | Country parameter set; VND through the fixed FX table; CRP 3.90 % dated; flagged "country risk added". |

---

## 12. Open decisions for the owner

1. Default price per share for new companies by stage (proposal: A$0.10 / 0.25 / 1.00 / 1.00 / 1.00), or keep A$1 for all.
2. ERP: AU practice 6.0 % (proposal) vs Damodaran 4.23 %.
3. Minimum confidence to finalise (proposal: medium; low only with admin reason).
4. Validity of a final value (proposal: 12 months; 6 months for idea/pre-seed).
5. Whether founders may edit assumptions themselves (proposal: no — they upload projections; only admins edit
   assumptions, with audit).
6. Whether to build the optional Excel export (Phase 7).
7. Growth caps by stage (§6.4) — conservative defaults proposed.

---

## Sources

- Anthropic financial services: https://github.com/anthropics/financial-services (Apache-2.0, commit 574ed36) ·
  https://claude.com/plugins/financial-analysis · https://support.claude.com/en/articles/13851150-install-financial-services-plugins
- Methods: https://corporatefinanceinstitute.com/resources/valuation/valuation-methods/ ·
  https://ryanoconnellfinance.com/dcf-valuation-multiples/ ·
  https://www.streetofwalls.com/finance-training-courses/investment-banking-technical-training/valuation-techniques-overview/ ·
  https://www.ivsc.org/wp-content/uploads/2021/10/IVS105ValuationApproaches.pdf
- Private capital: https://www.privateequityvaluation.com/Portals/0/Documents/Guidelines/IPEV%20Valuation%20Guidelines%20-%20December%202022.pdf ·
  https://www.privateequityvaluation.com/Portals/0/Documents/Guidelines/2025%20IPEV%20Valuation%20Guidelines.pdf ·
  https://www.pwc.com/jg/en/events/document/ipev-2022-update-summary-26-january-2023.pdf
- Startup methods: https://waveup.com/blog/startup-valuation-methods/ ·
  https://virtuecpas.com/pre-revenue-startup-valuation-methods-explained/ ·
  https://europe.republic.com/academy/4-valuation-methods-used-by-vcs-and-angels ·
  https://www.equidam.com/scorecard-valuation-method/ · https://www.venionaire.com/startup-valuation-payne-scorecard-method/ ·
  https://angelcapitalassociation.org/blog/after-20-years-updating-the-berkus-method-of-valuation/ ·
  https://berkus.com/the-berkus-method-valuing-an-early-stage-investment-2/ ·
  https://gust.com/blog/valuations-101-the-risk-factor-summation-method/ ·
  https://link.springer.com/chapter/10.1007/978-3-031-35291-1_11 ·
  https://kruzeconsulting.com/blog/what-vcs-return-expectations/ ·
  https://www.industryventures.com/insight/the-venture-capital-risk-and-return-matrix/ ·
  https://ryanoconnellfinance.com/venture-capital-valuation-method/ ·
  https://www.wallstreetprep.com/knowledge/first-chicago-method/
- Market data: https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ctryprem.html ·
  https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datacurrent.html ·
  https://aswathdamodaran.substack.com/p/country-risk-determinants-measures ·
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6361419 ·
  https://tradingeconomics.com/australia/government-bond-yield ·
  https://www.abc.net.au/news/2026-09-01/australian-government-10-year-bond-hits-15-year-high/107103096 ·
  https://tradingeconomics.com/vietnam/government-bond-yield/news/580736 ·
  https://www.charteredaccountantsanz.com/tools-and-resources/client-service-essentials/business-valuation/market-risk-premium-australian-evidence
- Multiples / DLOM: https://lyndonadvisory.com/blog/ebitda-multiples-australia-2026 ·
  https://olivergroup.com.au/insights/ebitda-multiples-by-industry-australia/ ·
  https://www.quinnma.com.au/blog/valuations/what-is-my-business-worth-2026/ ·
  https://www.acquiry.com/sector-multiples/dlom-research/ ·
  https://www.grantthornton.co.uk/insights/when-to-apply-a-discount-for-lack-of-marketability/
- Round data: https://carta.com/data/state-of-private-markets-q1-2026/ · https://carta.com/data/state-of-pre-seed-q2-2026/ ·
  https://www.cutthrough.com/insights/state-of-australian-startup-funding-2025
- Regulation: https://www.asic.gov.au/regulatory-resources/find-a-document/regulatory-guides/rg-170-prospective-financial-information/ ·
  https://download.asic.gov.au/media/1240943/rg170-010411.pdf
- Libraries: https://github.com/numpy/numpy-financial (BSD-3) · https://github.com/Anexen/pyxirr (Unlicense) ·
  https://github.com/JerBouma/FinanceToolkit (MIT) · openpyxl (MIT)
