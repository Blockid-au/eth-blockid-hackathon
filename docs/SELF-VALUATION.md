# BlockID values itself — the first real case

Status: **prepared, not run.** Runs after the owner supplies the inputs marked _owner_ below. The result is published
as computed (no hand edits) and shown in the demo as "the first company on BlockID is BlockID".

## Why
- Proves the product on a real company with a real team and real shares (BlockID Pty Ltd: Long 80 %, Tuấn 20 %).
- Shows judges and investors the full flow: check → team report → valuation → finalise → share register → anchors.
- Honest: pre-revenue, pre-seed; the report says so.

## Subject
- Company: **BlockID Pty Ltd** (to be registered; until then "BlockID — to be incorporated as BlockID Pty Ltd,
  operated by Auschain Pty Ltd under licence"). Website https://eth.blockid.au.
- `origin = self` on the valuation and the company (badge "Real — self-assessment"); the 14 seeded listings are
  `origin = sample` (`scripts/mark-sample-listings.py`).

## Inputs (evidence level in brackets — `EVALUATION-V5-API.md`)
| Field | Value | Source |
|---|---|---|
| revenue_ttm_aud | 0 | L1 (true: no customers yet) |
| stage | pre-seed (product live on testnet) | derived |
| raised_to_date_aud | _owner_ (0 if bootstrapped by founders/Auschain) | L1 |
| cash_aud, burn_monthly_aud | _owner_ | L1 (L2 if a bank statement / budget file is uploaded) |
| target_customer | AU startups & SMEs raising or managing shareholders; recruiters; angel groups | L1 |
| target_customer_count | ~5,150 AU startups (StartupBlink 2026) + SMEs; 8,518 recruitment businesses (IBISWorld) | L3 (cited) |
| annual_price_aud | 588 (Founder A$49/mo) … 1,788 (Growth) | price book v1 |
| waitlist / lois / pilots_paid | _owner_ — honest counts only (0 is fine) | L1/L2 |
| integrations_count | chains: BlockID EVM, Ethereum Hoodi, HashKey testnet; Google sign-in; Stripe (after build) | L3 (explorers) |
| documents (L2) | 3-min deck PDF; projections CSV from `PLAN-GTM.md` §5 (marked **unaudited**); test report | upload |
| team | Do Van Long (co-founder & CEO, 80 %), Truong Quoc Tuan (co-founder, 20 %) with public URLs — `TEAM.md` | L3 where pages verify |

Expected (not a target): pre-seed; Scorecard / Berkus / risk-factor methods around the AU pre-seed median base
(A$3.0M, `tools/stage.py`); confidence **low → medium** because there is no revenue and no priced round. If
confidence is low, finalising needs an admin override with a written reason — record it.

## Governance (conflict of interest)
- Requester: Auschain / BlockID admin. **Approver must be independent** — not Long, not Tuấn. Use an external
  advisor's admin wallet (added to `ADMIN_WALLETS` temporarily) and remove it after.
- The report shows "Self-assessment by the BlockID team; approved by an independent reviewer" and the audit log
  entries (four-eyes).
- Billing: the valuation id goes in `BILLING_FREE_ALLOWLIST` (always free to view).

## Steps
1. Owner fills the _owner_ fields and confirms `TEAM.md`.
2. Enable `VALUATION_V5=1` (after the v5 code is deployed — commit fef89c4 ships it switched off).
3. `/start` with the website, self-reported figures, team (with headline + CV fields), documents.
4. Review; independent admin approves; finalise (share price default A$0.10 at pre-seed unless evidence supports another).
5. `PUT /v1/admin/origin` → `self`; set the Home "We valued ourselves first" link to `/v/<id>`.
6. After BlockID Pty Ltd is registered: create company **BLKID**, holders Long 800,000 / Tuấn 200,000 (or the
   registered numbers), issue on BlockID EVM, anchor on Hoodi + HashKey. This records existing holdings — it is not
   an offer. The page says the register is on test networks until the mainnet move (`PLAN-REVENUE-MODEL.md` §5).
7. Add the case to the deck and the demo script.
