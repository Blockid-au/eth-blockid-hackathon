# BlockID Business Passport — business readiness, usage tracking and pricing plan (2026-09-27)

Status: **PLAN ONLY — nothing here is built yet.** Owner summary in Vietnamese: `docs/PLAN-BUSINESS.vi.md`.
Testnet demo. Not an offer of securities or financial advice. All prices below are **hypotheses to test**, not
published prices. The 14 listed companies are sample listings built from public information; there are no real
users yet (`docs/FACTS.md`). Every metric this plan creates must keep sample, demo, internal and real users apart.

Goal: move from hackathon demo to a business that (1) knows exactly who uses it and what they do, (2) measures
what each customer would pay before charging, (3) can switch on subscriptions + per-transaction fees + white
label through one payment integration, and (4) moves between stages only when a written, scored gate is passed.

---

## 1. Review — where the project stands (2026-09-27)

### 1.1 Product (what can be sold)

| Module | Buyer | Natural billable unit | State |
|---|---|---|---|
| Business check + valuation (`/start`, `/v/:id/report`) | Founder / SME, investor checking a business | one report run; one finalised valuation | live (testnet), v5 partly built |
| HR people / team / CV reports (hr.blockid.au) | Recruiter, founder, investor checking a team | one person report, one CV analysis, one team report | live |
| Company workspace: cap table, mint, activity, team | Founder / company admin | company per month; holders on register | live (testnet) |
| Investor updates (AI-drafted, anchored) | Company → investors | company per month; published update | live (testnet) |
| Transfers + KYC requests | Holder, company | per transfer; per KYC check | live, KYC = hash + manual approval |
| Dividends (Merkle, `claimFor`) | Company → holders | % of distribution | live with test mAUD only |
| Offerings / reservations | Founder, investor | % of amount raised | simulated, no escrow |
| Investor portal `/i` | Investor | free (network builder); later premium | live |
| Admin console, ops, AI health | Operator / white-label partner | platform fee | live |
| Equity structure (classes, vesting, buyback) | Founder, employees | per company / per grant | planned (`EQUITY-STRUCTURE-PLAN.md`) |

Revenue lines already named in FACTS.md (issuance fee, cap-table SaaS, transfer-agent fee, 0.5–1% of dividend
rounds, custody via partner) have **no prices, no plans, no billing tables and no payment provider** anywhere.

### 1.2 Users, tracking and reporting (what exists)

Exists:
- Sign-in: SIWE wallet, guest browser key ("Try it now"), Google + device key, shared demo wallet, admin password.
  `studio.sessions` (kept 45 days after expiry), `studio.accounts` + `account_wallets` for Google users only.
- `studio.audit` records admin / Google / password sign-ins and most admin and company actions.
- Ops (`ops/`): nginx traffic per day (`ops_traffic_daily`, hashed visitors), `ops/stats.py` (accounts, active
  1/7/30 d, sign-ins by method, valuations, HR, companies, offerings, dividends, AI spend), weekly report,
  `/admin/ops` Traffic and Overview tabs.
- `studio.ai_usage`: one row per model / search call with `user_id`, tokens, `cost_usd`.
- Quotas: valuations 3/wallet/day, 60/day global; HR 5 runs/wallet/day; in-memory limits for HR suggest, URL check,
  login.

Gaps (the tracking feature fixes these):
1. **No single user identity.** Wallet, guest, demo and password users have no user row; one person can appear as
   several wallets; one Google account can link several.
2. **Non-admin wallet, guest and demo sign-ins are not audited**, only kept as session rows (deleted after 45 d).
3. **No "online now", no per-user activity, no product events, no funnel, no retention.** Access logs with a
   hashed user go only to Docker stdout.
4. **No real / demo / internal / sample flag** — reports cannot answer "how many real users?" honestly.
5. **AI cost is only summed globally**, never per user, company or customer — no unit economics.
6. In-memory limits reset on restart; guest wallets are free to create, so per-wallet caps are Sybil-able.
7. No cookie notice, privacy policy or terms page.
8. No tenant / organisation concept — white label impossible today.

### 1.3 Production readiness (blocks charging money)

Ranked by risk (from the ops/security review):
1. Public `admin / admin` login grants full platform admin (can approve issuance) — `ADMIN_PASSWORD_LOCKED=1`.
2. Hot issuer key on the same host as its password files; no multisig / KMS.
3. **No database backups**, no off-site copy, no restore test; Postgres, chain state, evidence and keys on one disk.
4. Single VM; Terraform describes an older design; site served from a home directory; no staging.
5. HR CVs / names sent to offshore model providers; no retention purge, no DPA, self-attested consent (APP 8).
6. Legal: tokenised Pty shares are securities; no AFSL / CSF partner; no contract audit; DAF Act from 9 Apr 2027.
7. Claude subscription bridge in the production path (terms + single point of failure) → metered API needed.
8. Monitor runs inside the API it watches; alert email waits on SMTP; no external uptime check.
9. Sybil-able free limits; open issuance (`OPEN_ISSUE=1`); no edge rate limits.
10. CI: no web tests / typecheck, Postgres tests skipped, no dependency / image / secret scans, `:latest` images.

Strengths to keep: issuer-only key holder with admin approval, four-eyes approvals, SIWE + `__Host-` cookie +
CSRF allowlist + CSP, JSON logs with request ids, 18 ops checks with runbooks, ~295 Python + 37 Foundry tests,
AI gateway with cost ledger.

---

## 2. Stages and gates

The business moves through five stages. A stage ends only when its gate is **scored and recorded** in
`docs/GATES.md` (new file: date, scores, evidence links, decision, who signed off). No gate is skipped.

| Stage | What it is | Money | Ends at gate |
|---|---|---|---|
| **S0 Hackathon** (now) | Public demo for judging, sample data, judging-mode caps | none | **G0 — Judging closed** |
| **S1 Foundation** (~4 weeks) | Tracking, identity, hardening, legal pages, split demo from production | none | **G1 — Ready for real users** |
| **S2 Free pilot** (8–12 weeks) | Invited real founders, recruiters, investors; shadow pricing; interviews | none charged; shadow invoices | **G2 — Ready to charge** |
| **S3 Paid beta** (~3 months) | Stripe live for non-regulated products; first white-label partner LOI | subscriptions + usage | **G3 — Ready to scale** |
| **S4 Scale / white label** | Tenants, partner billing, regulated fees only with licensed partner | full model | quarterly review |

### G0 — Judging closed (move S0 → S1)
Checklist (all required):
- Judging finished; result and judge feedback recorded in `docs/GATES.md` and `docs/FACTS.md` (placement, prize,
  feedback quotes). Devfolio entry frozen.
- Judging-mode caps restored from `/opt/blockid/app.env.bak-judging`; `agents-api` restarted; checked.
- Decision recorded: which demo stays public (sample report, guest try-it) and on which host.
- Hackathon-period traffic snapshot exported from `/admin/ops` (baseline "before real users").

### G1 — Ready for real users (S1 → S2), scored 0–2 per line, pass = all "must" lines at 2
| # | Criterion | Must |
|---|---|---|
| 1 | `admin/admin` removed from production; admin = SIWE admin wallets (+ password with TOTP if kept) | ✔ |
| 2 | Nightly encrypted `pg_dump` off-site + restore rehearsed once | ✔ |
| 3 | Tracking live: users, identities, auth events, events, presence, `/admin/analytics` (§3) | ✔ |
| 4 | Every account flagged real / demo / internal / test; sample companies flagged `is_sample` | ✔ |
| 5 | Terms, Privacy Policy, cookie notice, HR consent text reviewed by a lawyer | ✔ |
| 6 | Production separated from demo (demo host or `is_demo` workspace; demo writes never count as real) | ✔ |
| 7 | External uptime check + SMTP alerts working | ✔ |
| 8 | Metered AI API replaces the subscription bridge in production paths | ✔ |
| 9 | HR CV retention purge (e.g. 90 days) + delete-my-data endpoint | ✔ |
| 10 | Usage ledger + shadow pricing recording (§4) | ✔ |
| 11 | Legal memo on what may be charged before an AFSL partner (§5.4) | — |
| 12 | Company legal line in footer + legal pages (`COMPANY.md` §4); BlockID trade mark application filed (™ until registered, never ®); items marked G1 in `COMPANY.md` §6 done | ✔ |

### G2 — Ready to charge (S2 → S3), scored against pilot data
| Metric (real users only) | Target to pass |
|---|---|
| Real pilot companies onboarded | ≥ 10 (≥ 5 via one accelerator / partner) |
| Real monthly active users (MAU) | ≥ 50 |
| Activation: sign-in → first completed report within 7 days | ≥ 40 % |
| Week-4 retention of founders | ≥ 25 % |
| Willingness to pay: pilot users saying "would pay at price X" in interview | ≥ 5, at ≥ 2 price points tested |
| Shadow MRR (what pilots would have paid under the proposed price book) | ≥ A$1,500 |
| AI + infra cost per active company / month (from ledger) | known, < 20 % of proposed price |
| G1 items still green; no Sev-1 incident open | yes |
| Stripe account (Auschain Pty Ltd), GST registration, invoice template ready | yes |

Score each line 0 (miss) / 1 (near) / 2 (met); pass = total ≥ 80 % and the last two lines at 2.

### G3 — Ready to scale (S3 → S4)
Real MRR ≥ A$5,000; logo churn < 5 %/month; ≥ 1 signed white-label / partner contract; payback of acquisition
cost < 6 months; AFSL / CSF partner signed **before** any fee on transfers, offerings or dividends; contract audit
done before any mainnet issuance; SOC-style controls list (access review, backups, incident log) in place.

---

## 3. Feature: user tracking, online presence and admin reporting (build in S1)

Principles: first-party only (data stays in our Postgres, no third-party trackers → simpler privacy and no cookie
banner for analytics beyond a notice); every row carries `user_id` or `anon_id`, `host`, and a **segment flag**;
server-side events are the source of truth for anything billable; the browser only adds page / UI events.

### 3.1 Data model (new tables in `studio` schema)

```sql
-- One person, many ways to sign in
users(id uuid pk, created_at, first_seen_at, last_seen_at, display_name, email null, country null,
      segment text check (segment in ('real','internal','demo','test','judge')) default 'real',
      persona text null,              -- founder | investor | recruiter | partner | unknown (self-declared at onboarding)
      org_id uuid null,               -- white label / team (S4); null until tenants exist
      tenant_id uuid null,
      marketing_opt_in bool default false, deleted_at null)
user_identities(id, user_id fk, kind text,            -- wallet | guest | google | password | demo
                subject text,                          -- lowercase address / google sub / username
                created_at, last_used_at, unique(kind, subject))
auth_events(id bigserial, at, user_id null, identity_kind, subject_hash, event text,   -- login_ok | login_fail | logout | session_expired | link_identity
            host, ip_hash, ua_family, country, session_id_hash)
sessions  -- existing; add user_id, last_seen_at, host
events(id bigserial, at, user_id null, anon_id null, session_id_hash null, host, segment,
       name text,                      -- e.g. page_view, start_submitted, report_viewed, issuance_requested
       company_id null, props jsonb, source text check (source in ('server','web')))
usage_ledger(id bigserial, at, user_id, company_id null, tenant_id null, unit text,  -- see §4.2
             quantity numeric, ref_type, ref_id, ai_cost_usd numeric default 0,
             shadow_price_aud numeric null, billed bool default false, invoice_id null)
daily_metrics(day, host, segment, metric text, value numeric, primary key(day, host, segment, metric))  -- rollups kept forever
```

Migration: backfill `users` + `user_identities` from `accounts`, `account_wallets`, distinct `requested_by` /
`created_by` / `actor` values, `admin_users`, `company_admins`; mark the demo wallet, seeded holders, admin wallets
and team wallets as `demo` / `internal`; mark the 14 sample companies `is_sample=true` (new column on companies).

### 3.2 Capture points

Server (authoritative, in `studio/routes.py`, `accounts.py`, `hr.py`, `runner.py`, `offerings.py` …):
- `resolve_user(session)` on every authenticated request → creates user + identity on first sight; updates
  `last_seen_at` (throttled to once per minute per session).
- `auth_event()` on **every** sign-in method (fixes gap 2), failed logins, logout, identity linking.
- `track(name, …)` on product actions: start_submitted, valuation_completed / failed, report_shared, hr_report_*,
  cv_analysis_completed, company_created, issuance_requested / approved, mint, transfer, kyc_requested, dividend_*,
  offering_*, update_published, investor_invited.
- `meter(unit, qty, ref)` writes `usage_ledger` for billable units and pulls `ai_cost_usd` from `ai_usage` by job.

Browser (`web/app/src/lib/track.ts`, batched `POST /v1/t`, `sendBeacon` on unload):
- `page_view` on route change (route template, not raw URL with ids), `anon_id` in localStorage (per host).
- Heartbeat every 60 s while the tab is visible → presence.
- Key UI events: cta_clicked (landing), try_it_started, signup_started / completed, onboarding_persona, share_opened,
  deck_viewed, pricing_viewed (S2), upgrade_clicked (S3).
- Honour Do-Not-Track and an in-app "limit tracking" switch; no text inputs, CV content or wallet balances in props.
- Rate-limited endpoint, max 50 events/batch, props size cap 2 KB, bot user agents dropped.

### 3.3 Online now

`presence` = distinct users / anon_ids with a heartbeat in the last 5 minutes (from `sessions.last_seen_at` +
an in-memory counter flushed every minute). Shown live in admin with split by host (eth / hr), segment and
signed-in vs anonymous; peak concurrent per day saved to `daily_metrics`.

### 3.4 Admin: new `/admin/analytics` section (next to `/admin/ops`)

| Tab | Content |
|---|---|
| Overview | Online now; DAU / WAU / MAU; new users; sign-ins by method; real vs demo vs internal toggle (default **real only**); week-over-week |
| Users | Searchable list: user, segment, persona, identities, first / last seen, sessions, reports, companies, AI cost, shadow revenue. Admin can change segment / persona |
| User detail | Timeline of auth events + product events + usage; linked wallets; companies; export; delete (privacy) |
| Funnels | Visit → try-it → sign-in → first report → company created → issuance; HR: visit → sign-in → first report → second report |
| Retention | Weekly cohort table by first-seen week and persona |
| Features | Usage per module, per host; top pages; drop-off steps |
| Companies | Per company: admins, holders, actions, usage units, AI cost, shadow price, plan (S3) |
| Revenue (S2 shadow → S3 real) | Shadow MRR by plan, usage revenue, cost per unit, gross margin, top customers |
| Export | CSV per table and a monthly "real users report" PDF / markdown for investors (numbers from `segment='real'` only) |

Monthly report (extends `ops/report.py`): real users, MAU, activation, retention, usage, cost, shadow / real MRR,
compared with last month — emailed to admin@blockid.au and stored in `ops_reports`.

### 3.5 Privacy and retention

- Raw `events` kept 13 months, `auth_events` 24 months, `usage_ledger` 7 years (tax records), rollups forever.
- IPs never stored raw (daily-salted hash, as `ops_traffic_daily` does now); country from Cloudflare header.
- Privacy Policy lists the first-party analytics, the model providers (offshore, APP 8), retention and deletion.
- Delete-my-data: anonymise `users` row, drop identities, keep ledger rows with `user_id` replaced (legal basis).

### 3.6 Work breakdown (S1, ~2 weeks for one engineer + Claude)

1. Schema + migration + backfill script with dry-run report (counts per segment) — 2 d
2. `resolve_user`, `auth_event` on all sign-in paths, session `last_seen_at` — 1.5 d
3. Server `track()` / `meter()` helpers + calls in all modules — 2 d
4. `/v1/t` endpoint + `track.ts` + heartbeat + DNT / limit switch — 1.5 d
5. Rollup job (hourly into `daily_metrics`) + retention purge job — 1 d
6. `/admin/analytics` UI (7 tabs) with real-only default + CSV export — 3 d
7. Monthly report + tests (pytest for resolve / meter / rollups; smoke test for the admin page) — 1.5 d
Acceptance: a new guest who then signs in with Google shows as **one** user with two identities; demo account
activity never appears under "real"; online-now matches a manual two-browser test; ledger totals equal
`ai_usage` totals for the same jobs.

---

## 4. Pricing research and billing design

### 4.1 Approach: measure → shadow price → charge

1. S1 builds the ledger; every billable action is metered from day one of the pilot.
2. S2 applies a **price book** (versioned JSON in the DB) to the ledger to compute **shadow invoices** per user /
   company — nobody is charged. Pilot users see "This would cost A$X on the Growth plan" in their account page
   (test price anchoring) and are interviewed (Van Westendorp: too cheap / cheap / expensive / too expensive).
3. S3 switches the same price book on in Stripe. Price changes = new price-book version, grandfathered customers.

### 4.2 Billable units (ledger `unit` values)

`valuation_report`, `valuation_finalised`, `hr_person_report`, `hr_cv_analysis`, `hr_team_report`,
`company_month` (active company workspace), `holder_on_register`, `investor_update_published`, `kyc_check`
(pass-through + margin), `share_issuance`, `transfer_processed`, `dividend_round` (amount), `offering_settled`
(amount), `white_label_tenant_month`, `api_call` (partner API, S4).

### 4.3 Hybrid model (hypotheses, AUD, ex GST)

> **Superseded 2026-09-28 by price book v1 in [PLAN-GTM.md](PLAN-GTM.md) §4** (market-researched: people report A$49,
> passport check A$59, valuation A$299 / A$890, Founder A$49/mo, Growth A$149/mo, group / recruiter plans, white label).
> PLAN-GTM §6 also moves one-off paid reports into S2 ("paid pilot", from early Nov 2026). The table below is kept for history.

**Investors: free.** They are the network that makes companies want the passport. Later "Investor Pro" (alerts,
portfolio export, deeper reports) ~A$15/month — test only after G2.

**Founders / companies — subscription + usage:**

| Plan | Price / month (annual −20 %) | Includes | Over the limit |
|---|---|---|---|
| Free | A$0 | 1 business report / month, public passport, cap table ≤ 10 holders, test-network only | upgrade prompt |
| Starter | A$49 | 3 reports / month, cap table ≤ 50 holders, investor updates, 1 admin | A$19 / extra report |
| Growth | A$199 | unlimited reports, finalised valuation 1 / quarter, 3 admins, investor portal branding, equity plan (when built) | A$99 / extra finalised valuation |
| Scale | A$499 | multiple companies / funds, API, priority support | custom |

**HR / recruiters (fastest non-regulated revenue):** pay-as-you-go A$19 / person report, A$9 / CV analysis;
packs 20 reports A$299; Team plan A$149 / month (15 reports). Credits never expire within 12 months.

**Transaction fees (only after an AFSL / CSF partner and legal sign-off, S4):** share issuance A$490 one-off
per round; transfer A$15–25 each (transfer-agent style); dividend round 0.5–1 % capped at A$2,000; offering
success fee 1–3 % shared with the licensed intermediary; KYC at provider cost + 30 %.

**White label (S4) for accelerators, CSF platforms, accounting / law firms, VN securities firms:**
setup A$5k–15k; platform A$1,500–5,000 / month (brand, own host, own admins, N companies included);
usage per company above the included count; optional revenue share 20–30 % of transaction fees on their tenant.

Unit economics to verify from the ledger: AI cost per valuation ≈ US$0–0.025 today on free tiers and will rise
on a metered API — the ledger must show real cost per unit before G2. Target gross margin ≥ 75 %.

### 4.4 Entitlements (replace env caps)

`plans(id, code, version, limits jsonb, features jsonb, price_ids jsonb)`, `subscriptions(id, owner_type user|company|tenant,
owner_id, plan_id, status, period_start/end, stripe_customer_id, stripe_subscription_id)`, `entitlement_check(user,
unit)` used by `create_valuation_limited`, `hr_store.queue_run`, etc. Env caps become the Free plan's limits;
admin can grant credits / trials. Persist all limits in Postgres (fixes in-memory resets). Guest wallets keep a
small anonymous allowance per IP-hash per day (fixes Sybil).

### 4.5 Payment integration design (build in S2, switch on at G2)

- **Provider: Stripe (Auschain Pty Ltd, AUD)** — Billing for subscriptions, Meters for usage (report units from
  `usage_ledger` hourly with idempotency key = ledger id), Checkout for sign-up, Customer Portal for card / plan /
  invoices, Stripe Tax for 10 % GST, invoices for white-label partners (bank transfer / BECS).
- Abstraction `billing/provider.py` (`create_customer`, `start_checkout`, `report_usage`, `handle_webhook`) so
  Vietnam can add **PayOS / VNPay / MoMo** (VND) later, and stablecoin payment (USDC / AUDD) can be added without
  touching product code.
- Tables: `billing_customers`, `subscriptions`, `invoices` (mirror of Stripe), `payment_events` (raw webhook log,
  signature-verified, idempotent), `credits`.
- Webhooks: `checkout.session.completed`, `customer.subscription.*`, `invoice.paid` / `payment_failed` → update
  entitlements; failed payment → 7-day grace → downgrade to Free (data kept, read-only).
- UI: `/pricing` page (S2 shows plans with "pilot — free for now"), account → Plan & billing, admin → Revenue.
- We never hold client money for investments: offering / dividend funds stay with the licensed partner / escrow
  contract; our fees are invoiced separately.
- Tests: Stripe test mode + CLI webhook replay in CI; reconciliation job ledger vs Stripe usage daily.

---

## 5. Business plan

### 5.1 Target customers, in order

1. **Recruiters and founders hiring (HR reports)** — no securities law issue, clear per-report value, quickest
   first revenue. Channel: LinkedIn, recruiter communities, founder networks.
2. **Early-stage AU founders / SMEs (pre-seed → Series A)** via **accelerators and angel groups** (Sydney / Melbourne
   programs, university incubators): business report + passport + cap table + investor updates. Accelerator gets a
   cohort deal (free pilot → Growth at a cohort discount).
3. **Investors (angels, syndicates)** — free, invited by their companies; they create pull for the passport.
4. **White-label partners**: licensed CSF intermediaries (e.g. Birchal-type), accounting / law firms serving SMEs,
   Vietnamese securities / advisory firms — the post-raise layer under their brand.
5. **Regulated transaction flows** (issuance, transfers, dividends, offerings) — only with the AFSL / CSF partner.

### 5.2 Revenue ramp (targets, to be replaced by pilot data at G2)

| Month after G2 | Paying founders | HR buyers | White label | Target MRR (A$) |
|---|---|---|---|---|
| 3 | 15 | 20 | 0 | ~3,500 |
| 6 | 40 | 50 | 1 | ~11,000 |
| 12 | 120 | 120 | 3 | ~35,000 |

### 5.3 Costs to plan for (monthly, rough)
VM + backups + storage A$150–400; metered LLM API (from ledger, target < 10 % of revenue); KYC provider per
check; Stripe ~1.7 % + A$0.30 (domestic cards); email provider; legal (one-off memo A$5–15k, terms / privacy
A$2–5k); contract audit before mainnet US$15–60k; insurance (PI / cyber).

### 5.4 Legal line (must be confirmed by a lawyer before S3)
Sell now (S3): software subscriptions, reports, HR checks, investor-update tooling, cap-table **records**.
Wait for a licensed partner (S4): anything that arranges, issues, transfers or pays out securities or handles
investor money, or that could read as personal financial advice (valuation wording, RG 255). Vietnam:
securities-backed tokens are excluded under Resolution 05/2025 — sell software / HR only there.

---

### 5.5 Operating entity
All selling is done by **Auschain Pty Ltd** (ABN 79 659 615 111, ACN 659 615 111, GST from 26 Mar 2025, NSW), the
user of the unregistered BlockID™ mark (application to be filed; name clash with 1Kosmos "BlockID" to be cleared), trading as BlockID. Facts, footer text, invoice rules and the list of missing
company information (TM number, ASIC extract, business name, bank, insurance, lawyer, IP agreement with Vietnam
Blockchain Corporation, R&D Tax Incentive by 30 Apr 2027) are in [COMPANY.md](COMPANY.md).

## 6. Roadmap (added to `docs/ROADMAP-RESEARCH.md`)

| When | Stage | Deliverables |
|---|---|---|
| Now → judging result | S0 | keep demo stable; record result; this plan approved |
| G0 + 0–2 weeks | S1-a | tracking + identity + admin analytics (§3); remove admin/admin; backups |
| G0 + 2–4 weeks | S1-b | legal pages, demo / production split, metered AI API, uptime + SMTP, CV retention, usage ledger, price book v0; **score G1** |
| G1 + 0–12 weeks | S2 | invite 10–20 pilot companies (1 accelerator) + recruiters; shadow invoices; WTP interviews; `/pricing` page; Stripe integration built in test mode; legal memo; KYC provider chosen; **score G2** |
| G2 + 0–3 months | S3 | Stripe live for HR + founder plans; monthly real-user report; tenant model designed; first white-label LOI; AFSL / CSF partner talks; contract audit quote; **score G3** |
| G3 onwards | S4 | tenants + white-label theming by host; partner billing; regulated fees through licensed partner; mainnet path (Safe multisig, validators, ERC-3643, audit) before 9 Apr 2027 DAF Act date |

## 7. Decisions needed from the owner
1. First-party analytics in our Postgres (recommended) vs a hosted tool (PostHog / Plausible).
2. First paid product: HR reports + founder plans (recommended) vs waiting for transaction fees.
3. Price hypotheses in §4.3 as the S2 test book — accept or change.
4. ~~GST status~~ answered: Auschain Pty Ltd (ABN 79 659 615 111) is GST-registered from 26 Mar 2025 (`COMPANY.md`).
   Still open: Stripe account under Auschain, business name BLOCKID, and the missing items in `COMPANY.md` §6.
5. Demo stays on eth.blockid.au as a clearly marked demo workspace, or moves to demo.blockid.au (recommended).
6. Who scores the gates (owner alone, or owner + an advisor) and where results are published.
