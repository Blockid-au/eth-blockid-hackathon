# Valuation v5 — API contract (backend ↔ UI)

Status: implemented behind `VALUATION_V5` (default **off**). With the flag off every endpoint below answers
`404 {"detail": "valuation v5 is not enabled"}` and every existing endpoint behaves exactly as before.
Plan: [PLAN-VALUATION-V5.md](PLAN-VALUATION-V5.md) · owner decisions: [DECISIONS-V5.md](DECISIONS-V5.md).

All amounts are A$ (floats, whole dollars unless noted), prices per share have 4 decimals, dates are ISO-8601 UTC.
Errors: `{"detail": "<plain words>"}` with 401 (sign in), 403 (not yours / admin only), 404, 409 (state), 413, 415,
422 (validation), 429 (rate limit).

---

## 1. Where the v5 result lives

`GET /v1/studio/valuations/{vid}` (unchanged endpoint) → `svi.triangulation` with `version: "v5"`:

```jsonc
{
  "version": "v5", "params_version": "v5.1", "market_dataset": "2026-09-27",
  "value_aud": 4210000, "low_aud": 3100000, "high_aud": 5600000,
  "confidence": "medium", "confidence_reasons": ["..."],
  "valuation_class": "seed",            // idea|pre_seed|seed|series_a|growth|profitable_sme|listed
  "stage": {"stage": "seed", "basis": "revenue", "reasons": ["..."], ...},   // tools/stage StageDecision
  "methods": [ValuationMethod],         // every method run, weight 0 = not used (see notes)
  "football_field": [FieldBar],
  "without_projections": {"value_aud": 0, "low_aud": 0, "high_aud": 0} | null,
  "projections": {"sha256": "...", "attested_by": "0x..", "attested_at": "...", "label": "Based on management
                  projections (unaudited, not verified by BlockID)."} | null,
  "tokenisation": TokenisationProposal,
  "listed": false, "listing": "", "as_of": "2026-09-27", "fx_as_of": "2026-09-26"
}
```

`ValuationMethod`:
```jsonc
{"method": "market_anchor|revenue_multiple|stage_scorecard|ebitda_multiple|precedents|dcf|vc_method|scorecard|
            berkus|rfs|first_chicago",
 "label": "plain words", "value_aud": 0, "low_aud": 0, "high_aud": 0,
 "raw_weight": 0.56, "weight": 0.32,           // weight = share of the blend (0..1)
 "inputs": {...},                              // every number used (rebuilt by /verify)
 "sources": ["https://..."], "notes": ["not used: 3.4x away from the other methods"],
 "checks": [{"code": "tv_share", "severity": "warning", "message": "..."}]}
```
DCF `inputs` also carry `fcff` (per year), `rows` (projection years used), `rate_build` (rf, beta, erp, crp,
size_premium → rate), `terminal` (`gordon`|`exit`), `g`, `exit_multiple`, `tv_share`, `sensitivity` (5×5 grid:
`rates[5]`, `gs[5]` (or `exit_multiples[5]`), `values[5][5]`, centre = base) and `uncapped_value_aud` ("your forecast as
uploaded", grey tick) when caps were applied.

`FieldBar` (football field, one per method): `{"method", "label", "low_aud", "mid_aud", "high_aud", "weight",
"used": bool, "reason": "why weight is 0" | null, "projection_based": bool}`.

`TokenisationProposal` (recommended values; the founder may choose another price at finalise, see §3):
```jsonc
{"pre_money_aud": 4210000, "low_aud": 3100000, "high_aud": 5600000, "stage": "seed",
 "basis": "new_company" | "existing_shares",
 "fd_shares_existing": null | 12000000,
 "default_price_for_stage_aud": 0.25,
 "recommended_price_per_share_aud": 0.2501,   // re-derived from a clean (3 significant figures) share count
 "total_shares": 16800000,
 "offer_price_low_aud": 0.1845, "offer_price_high_aud": 0.2501,   // [low / shares, mid / shares]
 "raise_aud": 0 | 500000, "new_shares": 0 | 2000000, "post_money_aud": 0 | 4710000, "dilution_pct": 0 | 10.6}
```

## 2. Projections (optional forecast upload)

| Method | Path | Who | Result |
|---|---|---|---|
| GET | `/v1/studio/projection-template?format=xlsx\|csv&lang=en\|vi` | signed in | file download (`blockid-projections-v1.xlsx` / `.csv`) |
| POST | `/v1/studio/valuations/{vid}/projections` | owner / platform admin | `multipart/form-data` field `file` (`.xlsx` or `.csv`, ≤ 512 KB) **or** the raw file bytes (`Content-Type: text/csv` or the xlsx type, name in `?filename=`) **or** `application/json` ProjectionInput → `201 ProjectionView` (status `draft`). 413 too large, 415 macro / old Excel / wrong type, 422 unreadable, 429 limit |
| GET | `/v1/studio/valuations/{vid}/projections` | owner / admin | `{"latest": ProjectionView\|null, "history": [ProjectionView without parsed], "label": "..."}` |
| POST | `/v1/studio/valuations/{vid}/projections/{pid}/confirm` | owner / admin | body `{"attest": true}` → `{"projection": ProjectionView, "valuation_status", "value_before_aud", "value_after_aud", "moved_pct", "back_to_review": bool}` |
| DELETE | `/v1/studio/valuations/{vid}/projections/{pid}` | owner / admin (draft only) | `{"ok": true}` |
| GET | `/v1/studio/valuations/{vid}/projections/{pid}/export.csv` | owner / admin | CSV (cells starting `= + - @` are escaped) |

Rate limit: 10 uploads per valuation per day (429). Confirm is refused (409) once a company exists for the
valuation (its report hash may be anchored on chain). Confirming re-computes the value deterministically; if the
valuation was already approved and the value moves more than 5 %, it goes back to `waiting_approval`.

`ProjectionInput` (JSON alternative for the in-page grid):
```jsonc
{"currency": "AUD", "fiscal_year_end": "06-30", "audited": false, "prepared_by": "CFO", "basis_notes": "",
 "cash": 250000, "debt": 0, "shares_fd": 10000000 | null, "planned_raise": 500000,
 "years": [{"year": 2026, "actual": true, "revenue": 1200000, "cogs": 400000, "opex": 600000,
            "ebitda": null, "d_and_a": 20000, "tax": null, "capex": 30000, "nwc": null, "change_nwc": null,
            "headcount": 12, "customers": 80}, ...]}   // 1-3 actual + 3-5 projected consecutive years
```

`ProjectionView`:
```jsonc
{"id": 12, "valuation_id": "ab12..", "status": "draft|confirmed|superseded",
 "filename": "forecast.xlsx", "size_bytes": 10240, "sha256": "...", "template_version": 1,
 "uploaded_by": "0x..", "attested_by": null, "attested_at": null, "created_at": "...",
 "parsed": ProjectionSet, "checks": [Check], "can_confirm": true, "errors": 0, "warnings": 2}
```
`ProjectionSet` = ProjectionInput + `{"basis": "management_projection", "fx_rate_to_aud", "fx_as_of",
"net_debt", "years_used": [same rows after caps, AUD]}`.
`Check` = `{"code", "severity": "error|warning|info", "message", "year": 2028 | null, "row": "capex" | null,
"used_value": 1234 | null}` — codes: `structure, identity, currency, growth_cap, jump_from_actual, gross_margin,
margin_cap, revenue_per_fte, capex_vs_da, tax_default, nwc_default, actuals_mismatch, hockey_stick`.
Errors block confirm; warnings apply the cap shown in `used_value` and lower the forecast's weight (0.7 → 0.4).

## 3. Finalise the value (before shares are proposed)

| Method | Path | Who | Result |
|---|---|---|---|
| GET | `/v1/studio/valuations/{vid}/tokenisation` | owner / admin | TokenisationView |
| POST | `/v1/studio/valuations/{vid}/finalise` | owner / platform admin | FinaliseBody → `200 TokenisationView` (finalised) or `202 TokenisationView` (price change > 20 %: waiting for a platform admin) |
| POST | `/v1/studio/valuations/{vid}/price-requests/{rid}/cancel` | requester / admin | TokenisationView |
| GET | `/v1/admin/price-requests?status=pending` | platform admin | `[PriceRequest + {"url", "company_name"}]` |
| POST | `/v1/admin/price-requests/{rid}/approve` | platform admin (not the requester) | body `{"note"?}` → TokenisationView (finalised) |
| POST | `/v1/admin/price-requests/{rid}/reject` | platform admin | body `{"reason"}` (≥ 5 chars) → TokenisationView |

`FinaliseBody`: `{"price_per_share_aud"?: number, "note"?: string, "reason"?: string,
"allow_low_confidence"?: bool, "override_reason"?: string, "planned_raise_aud"?: number (>= 0)}`
- `planned_raise_aud` (optional): the raise the founder plans at the chosen price; stored in the final with the new
  shares, post-money and dilution (a price request keeps it until a second admin approves). Omitted → the planned
  raise of the confirmed projections (tokenisation proposal), else none.
- no price → the recommended price.
- price within ±20 % of the recommended price → finalised at once; a `note` (≥ 3 chars) is required when the price
  differs from the recommendation.
- price beyond ±20 % (hard limits 0.2×–5×) → needs `reason` (≥ 20 chars) and creates a PriceRequest (`202`);
  a **different** platform admin approves it (four-eyes; the requester can never approve their own request).
- confidence `low` → 409 unless a platform admin sends `allow_low_confidence: true` with `override_reason` (≥ 10).
- the valuation must be `approved`, v5, and not already finalised with a valid final (re-finalising needs a new
  approval, or the old final expired / the report changed).

`TokenisationView`:
```jsonc
{"valuation_id": "..", "valuation_status": "approved", "confidence": "medium",
 "proposal": TokenisationProposal | null,
 "final": ValuationFinal | null,
 "final_state": "none" | "valid" | "expired" | "stale",     // stale = report changed since finalising
 "pending_request": PriceRequest | null,
 "can_finalise": true, "blockers": ["plain words", ...],
 "rules": {"free_band_pct": 20, "hard_min_ratio": 0.2, "hard_max_ratio": 5, "validity_days": 90,
           "min_confidence": "medium", "default_price_by_stage": {"idea": 0.1, "pre-seed": 0.1, "seed": 0.25,
           "series-a": 1.0, "growth": 1.0}}}
```
`ValuationFinal` (stored in `studio.valuations.final`):
```jsonc
{"version": 1, "valuation_id": "..", "report_hash": "0x..", "formula_version": "v5", "params_version": "v5",
 "stage": "seed", "valuation_class": "seed", "confidence": "medium",
 "pre_money_aud": 4210000, "low_aud": 3100000, "high_aud": 5600000,
 "recommended_price_per_share_aud": 0.2501, "price_per_share_aud": 0.27,       // chosen (always both shown)
 "price_deviation_pct": 7.96, "price_note": "round number", "price_reason": null,
 "price_request_id": null | 7, "price_approved_by": null | "admin",
 "total_shares": 15592593, "fd_shares_existing": null,
 "implied_value_aud": 4210000,           // price x shares (existing shares: moves with the price)
 "offer_price_low_aud": 0.1988, "offer_price_high_aud": 0.27,
 "revenue_used_aud": 1200000, "based_on_projections": true, "projection_sha256": "..." | null,
 "finalised_by": "0x..", "finalised_at": "...", "valid_until": "... (+90 days)",
 "low_confidence_override": null | {"by": "admin", "reason": "..."},
 "planned_raise_aud": 0 | 500000, "planned_raise_source": null | "founder" | "projections",
 "new_shares": 0 | 1851851, "post_money_aud": 0 | 4710000, "dilution_pct": 0 | 10.62}
```
`PriceRequest`: `{"id", "valuation_id", "status": "pending|approved|rejected|cancelled", "recommended_price_aud",
"requested_price_aud", "deviation_pct", "reason", "note", "requested_by", "report_hash", "decided_by",
"decided_at", "decision_reason", "created_at"}`.

### Effects of a final value (only with `VALUATION_V5=1`)
- `POST /v1/studio/companies`: with a valid final, `share_price_aud` / `total_shares` default to the final values
  and `valuation_aud = final.pre_money_aud`; a different price or share count → 422 ("change it through finalise");
  an expired or stale final → 409. No final → unchanged behaviour, unless `VALUATION_V5_REQUIRE_FINAL=1` (409).
- `GET /v1/companies/{tk}/offering`: `defaults.price_aud` = the final price when it is newer than the latest mark;
  `defaults.final` = the final (or null).
- `POST /v1/companies/{tk}/offering/submit`: 409 with a plain reason when the final expired, the stage changed, a
  newer approved valuation of the same website exists (created after the finalised one), the latest KPI revenue differs > 25 % from the revenue used
  ("revaluation needed"), or the price is above `high_aud / total_shares`. The pack gains `valuation.final`,
  `valuation.football_field`, `valuation.based_on_projections` (+ projection sha256 / attested by / at).

## 4. Admin: confirm subjective inputs and assumptions (four-eyes after finalising)

| Method | Path | Who | Result |
|---|---|---|---|
| PATCH | `/v1/admin/valuations/{vid}/assumptions` | platform admin | `{"changes": {path: value}, "reason": "≥ 10 chars"}` → `{"applied": bool, "change_ids": [..], "pending": bool, "valuation": <triangulation>}` |
| GET | `/v1/admin/valuations/{vid}/assumptions` | platform admin | `{"current": {...}, "allowed": {path: [min, max] \| [choices]}, "changes": [AssumptionChange]}` |
| POST | `/v1/admin/assumption-changes/{id}/approve` | a second platform admin | applies a pending change |
| POST | `/v1/admin/assumption-changes/{id}/reject` | platform admin | `{"reason"}` |
| POST | `/v1/admin/valuations/{vid}/rerun-v5` | platform admin | `{"reason": "≥ 10 chars"}` → re-values a stored (v1–v4) report with the v5 methods, deterministic, back to `waiting_approval`; refused once a company exists |

Whitelisted paths: `stage` (idea…growth), `valuation_class` (idea…listed), `industry` (dataset key),
`confirm_startup_factors` (true: AI-suggested Berkus / risk ratings become confirmed), `berkus.<factor>` (0–100),
`rfs.<risk>` (−2…+2), `competition` (−2…+2), `dcf.rf|beta_u|erp|crp|size_premium|tax_rate|g` (bounded),
`dcf.terminal` (`gordon|exit`), `dcf.exit_multiple`, `vc.target_multiple|years_to_exit|exit_multiple`,
`dcf.rate` (venture discount rate, pre-profit stages), `ebitda.multiple`, `scorecard.base_pre_money`, `dlom`,
`weights.<method>` (≤ 2× the rule weight). Every change: audit
`valuation_assumption_changed`, a row in `studio.valuation_assumption_changes`, deterministic recompute, status back
to `waiting_approval` if it was approved. When the valuation is finalised the change is `pending` until a second
platform admin approves it; applying it clears the final (re-finalise needed). Refused (409) once a company exists.

## 5. Verify

`GET /v1/verify/{ticker}` / `POST /v1/verify/hash`: `recomputed.formula_version` is `v5` for v5 reports and
`recomputed.methods` lists `{method, value_aud, low_aud, high_aud, weight}` as rebuilt from the stored inputs;
`formula.params_by_version.v5` / `v5.1` publish the rules (weights matrix, evidence factors, caps, calibration). v5
reports also recompute the **index and band** from `svi.analysis` (every code-computed dimension rebuilt from its
sub-metrics, trust from the verification levels, weights checked against the published stage column):
`recomputed.weights_version` = `v5:<stage>`, `recomputed.dimension_matches` per dimension, and
`matches_report` gains `weights` and `dimensions`. v1–v4 reports verify exactly as before.

## 6. Parameters and market data (27 Sep 2026)

- `params_version` **v5.1** for new valuations (`v5` stays frozen; every report recomputes with its own version):
  VC method = Sahlman target return (the class's venture rate ± 10 pp) with retention to exit after later rounds
  (Carta 2025 dilution medians); venture-rate DCF / First Chicago end in an exit at listed peers' EV/EBITDA less the
  DLOM; stage benchmark = AU stage pre-money table, or funding raised × 3.5 / 4.5 / 6 when known; revenue and EBITDA
  listed-peer multiples blended with the private-market figure by company size (listed share 0 at ≤ A$10M revenue,
  50 % from A$1B). Details and sources: docs/V5-READINESS.md "Calibration".
- `market_dataset` **2026-09-27**: industry rows transcribed from Damodaran's January 2026 datasets (global rows used,
  Aus/NZ/Canada rows shown for reference; source URLs and sha256 in the file); `2026-09-26` (placeholder rows) is
  unchanged. With verified rows the EBITDA multiple carries the "industry table" evidence factor (0.6) instead of the
  placeholder 0.5.
- Search: the valuation agent may run one `precedents` query (Series A / growth) after the analysts' kinds, inside
  the production budget of 12 (7 + 4 + 1).
