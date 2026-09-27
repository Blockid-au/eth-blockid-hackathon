# BlockID billing — implementation plan (Stripe, 7-day trials, investor-led invites)

Status: **approved 28 Sep 2026, in implementation** (behind `BILLING_ENABLED=0`). Owner setup: `STRIPE-SETUP.md`.
Revenue model: `PLAN-REVENUE-MODEL.md`. Self-valuation case: `SELF-VALUATION.md`. Gates: `GATES.md`.

Owner decisions: BlockID Pty Ltd to be registered (Long 80 % / Tuấn 20 %, Auschain licenses BlockID™ + IP);
charging starts only after the hackathon results (G0) + 7 days; 7-day trial with card on every plan + 1 free report
during the trial; one-off reports paid upfront; cancel in one click (portal or in-app).

## Workstream A — Launch gating (keep the competition safe)
- Flags: `BILLING_ENABLED=0` (default) and `BILLING_MODE=test|live`.
  - While the flag is off, the app behaves exactly as today.
  - Stripe test mode runs from week 1.
  - Live mode switches on at **G0 + 7 days**: results announced + recorded in `docs/GATES.md`, judging caps restored from `/opt/blockid/app.env.bak-judging`.
  - Target date **01 Nov 2026** if results are out by 25 Oct; otherwise the date moves.
- Paths that are never paywalled:
  - guest "Try it now"
  - `/v/sample/report`
  - demo account
  - the BlockID self-valuation case
  - `/verify`, `/hsk`, `/docs`, the deck
  - users with segment `judge`, exempt until 30 days after the results
- A public "Pricing starts on <date>" banner goes up 14 days before live (fair notice to trial users).

## Workstream C — Billing implementation (new package `agents/src/blockid_agents/billing/`)

`stripe` is not a dependency yet, so add `stripe>=10` + `pyyaml` to `agents/pyproject.toml`.
`ValuationRunner.run()` doesn't know the requester, so credit settlement is keyed on `ref_id` (the valuation id or HR team id).

1. **Config** (`config.py`, same `field(default_factory=…)` pattern as `:305`):
   - `BILLING_ENABLED`, `BILLING_START_AT`, `STRIPE_MODE`. Refuse to start if the key prefix does not match the mode.
   - `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PUBLISHABLE_KEY`.
   - `BILLING_JUDGE_EMAILS` / `_WALLETS`.
   - `BILLING_TRIAL_DAYS=7`, `BILLING_GRACE_DAYS=7`.
   - Helper `billing_live(now)`.
2. **Price book** `billing/pricebook/v1.yaml` is the source of truth. It holds:
   - products and prices, each keyed by `lookup_key`, e.g. `plan_founder_monthly_v1`
   - AUD cents
   - `tax_behavior`: inclusive for consumer one-offs, exclusive for B2B plans
   - plan entitlements: holders, valuations per year, checks per month, sponsored seats, `trial_credits: 1`
   - coupons `founding30` (forever, max 50) and `pulley6`

   `billing/pricebook.py` validates it: unique keys, and annual = 10× monthly.
3. **Schema** (append to `studio/schema.sql`, idempotent):
   - `billing_customers(account_id PK, stripe_customer_id, email, segment normal|judge|demo|staff, abn)`
   - `billing_subscriptions(stripe_subscription_id PK, account_id, plan_key, price_lookup_key, status, trial_end, current_period_end, cancel_at_period_end, grace_until, coupon, sponsor_account_id)`
   - `billing_trials(email_norm UNIQUE, card_fingerprint)` — one trial per person
   - `billing_credits` ledger:
     - `kind`
     - `delta`
     - `state granted|reserved|captured|released|expired`
     - `ref_type`, `ref_id`
     - `source plan|trial|purchase|admin|refund`
     - `expires_at`
     - unique on the reserved `(ref_type, ref_id, kind)`
   - `billing_orders`
   - `billing_events(stripe_event_id PK, payload, processed_at, error)` — for idempotency
   - `billing_invites`, `billing_referrals`, `billing_attributions`, `billing_payouts`
   - `email_otps`
   - `billing_catalog_cache`
4. **Store** `billing/store.py` (the `hr_store` pattern):
   - `balance`
   - `reserve` (runs under `pg_advisory_xact_lock(hashtext('billing:'||account_id))`)
   - `capture` / `release` (safe to call twice)
   - `grant`
   - `upsert_subscription`
5. **Stripe gateway** `billing/stripe_client.py`:
   - A protocol with create_customer, create_checkout, create_portal, cancel, list/create/update prices, and construct_event.
   - The real SDK sends an `idempotency_key` on every create; tests use `FakeStripe`.
   - It is injected via the studio ctx.
6. **Sync** `python -m blockid_agents.billing.sync --dry-run|--apply`, also available as an admin button:
   - Upsert each product by `metadata.pb_key`.
   - Look up each price by `lookup_key`. If it changed, create a new price with `transfer_lookup_key=true` and archive the old one.
   - Upsert coupons and promo codes.
   - Print a diff and cache the catalogue. `/pricing` never uses hard-coded prices.
7. **API** `billing/routes.py` → `build_billing_router(ctx)`, included in `api.py` after the HR router.
   - Public:
     - `GET /v1/billing/catalog`, returning live + start_at
     - `GET /v1/billing/invites/{token}`
   - Signed-in users (409 `email_required` if there is no email):
     - `GET /v1/billing/me`
     - `POST /v1/billing/checkout {lookup_key, promo?, invite_token?}`:
       - Subscription: `mode=subscription`, `subscription_data.trial_period_days=7` (only if eligible), `payment_method_collection='always'`, `trial_settings.end_behavior.missing_payment_method='cancel'`, `automatic_tax`, `tax_id_collection`, `allow_promotion_codes`, `client_reference_id=account_id`.
       - One-off: `mode=payment` + `invoice_creation`.
     - `POST /v1/billing/portal`
     - `POST /v1/billing/cancel`: immediate while trialing (no charge), otherwise at period end; 1 confirm, sends an email.
     - `POST /v1/billing/resume`
     - invites CRUD + accept
     - `GET /v1/billing/portfolio`
   - Admin:
     - sync, grant credits (audited), set segment
     - revenue, reconcile, referrals CRUD
   - **Webhook** `POST /v1/billing/webhook` (public URL `https://eth.blockid.au/api/v1/billing/webhook`; add to `CSRF_EXEMPT_PATHS`, `api.py:44`):
     - Read the raw body with `await request.body()` and verify with `construct_event` (tolerance 300 s). A bad signature returns 400.
     - Dedupe on the event id. Return 500 on error so Stripe retries.
8. **Email for wallet/guest users** (`studio/accounts.py`): `POST /v1/auth/email/otp|verify` creates or links an `accounts` row with provider `email`, linked to the wallet via `account_wallets`. Billing always attaches to the account, never the wallet.
9. **Webhook handlers** `billing/webhooks.py`. Each re-fetches the object and upserts from current state, so ordering does not matter.
   - `checkout.session.completed`: payment → order + credits (a pack of 10 → 10 credits); subscription → upsert, attribution, invite accept.
   - `customer.subscription.created/updated`:
     - On `trialing`: record the email and card fingerprint. If they were used before, cancel and email the user. Otherwise grant 1 trial credit.
     - On `active`: grant the plan credits for that period (idempotent per period start).
   - `customer.subscription.deleted`: expire plan credits and move to the free tier.
   - `customer.subscription.trial_will_end`: email "trial ending", sent 3 days before, with the charge date, price and a one-click cancel link.
   - `invoice.paid`: clear the grace period and refresh credits.
   - `invoice.payment_failed`: set `grace_until = now + 7 d` and email. A daily ops job downgrades accounts after grace.
   - `charge.refunded`: reverse unspent credits.
10. **Entitlement gate** `billing/entitlements.py` → `gate(ctx, sess, kind, ref_type, ref_id)` returns one of `free` / `credit` / 402 `PaymentRequired{checkout_hint}`. Exempt when:
    - billing is not live
    - the user is an admin
    - segment is judge or demo
    - it is an allowlisted demo/sample/self-valuation path

    Hook points:
    - `routes.py:489-521` before `create_valuation_limited`
    - `hr.py:478-484` around `queue_run`

    Capture points:
    - `runner.py:31-45`: capture on `waiting_approval`/`approved`, release on `failed`/`rejected`
    - `hr_store.finish` (`:613`), plus the failure and watchdog paths

    A sweeper releases stale reservations after 24 h. Paying users skip the env daily caps.
11. **Mailer** (`studio/mailer.py`, EN/VI like `welcome` at `:94`): `trial_started`, `trial_ending`, `payment_failed`, `cancel_confirmed`, `invite`.
12. **Web** (`web/app/src`):
    - `pages/Pricing.tsx` at `/pricing`: monthly/annual toggle, "incl. GST"/"+GST" labels, "7-day free trial · card required · cancel anytime", and a "Starts after launch" banner.
    - `pages/Billing.tsx` at `/account/billing` (linked from `Investor.tsx` `Account()` at `:203`): plan, trial end, credits, receipts, Manage (portal), and a **Cancel button on the same screen**.
    - `/invite/:token`, `/portfolio`, a global 402 modal, and the email OTP component.
    - `dict.billing.ts` EN/VI, merged in `dict.ts:1333`. Nav and footer links in `Layout.tsx`.
    - Admin **Revenue** section (`Admin.tsx:793` SECTIONS; new `pages/admin/Revenue.tsx` modelled on `OpsTab`):
      - MRR (trials excluded)
      - active trials
      - trial→paid conversion over 30 days
      - churn
      - one-off revenue
      - per-customer view
      - reconcile
      - grant credits
      - segments
      - referral payouts due

## Workstream D — B2B/B2C investor-led sales loop
The idea: an investor joins (B2C, or B2B as an angel group or fund) and invites portfolio startups. Each startup needs a
passport, valuation, share register and investor updates, and pays for them. The investor sees a portfolio dashboard.
- **Investor side**
  - The Investor portal `/i` is free.
  - Angel group plan A$199/mo includes **3 sponsored founder seats** (Founder plan paid by the group) and 10 checks a month.
  - Portfolio dashboard: invited startups, passport status, latest update, holding value.
- **Invite flow**
  - `POST /v1/invites {emails[], role:'founder'|'co-investor'}` creates a single-use token (HMAC-compared, like the HR share token), emails it (mailer), and records `invites(inviter_account, invitee_email, company_id?, status, sponsor_seat bool)`.
  - An invited founder lands on `/start?invite=` and gets a 14-day Founder trial (instead of 7) plus the investor's name.
  - Attribution is stored and reported in `/admin/analytics`.
- **Founder → investors**: founders invite their shareholders to the investor portal (free), which creates more investor accounts. This is the loop.
- **Partners**: referral codes for accountants and accelerators, with 20 % revenue share in year 1, tracked in `referrals` and paid manually each month.
- **Channels** (no VBC clients yet): communities, competitions, accelerators, events and networking. PLAN-GTM §7 gets updated:
  - AU: Startmate / Antler / Blackbird Giants perks, Sydney Angels, Scale Investors.
  - Meetups: Fintech Australia, Blockchain Australia, Sydney Ethereum and EthGlobal events, Stone & Chalk.
  - Pitch competitions.
  - Next hackathons: re-use the BlockID case.
  - Target: 4 events a month, 20 conversations per event.

## Verification
- `cd agents && python -m pytest -q` (new tests: price sync idempotency with a stubbed Stripe client, webhook signature + idempotency, trial → paid, trial cancel = no charge, payment_failed grace → downgrade, credit reserve / capture / release, flag-off = unchanged behaviour, judge / demo exempt).
- Stripe test mode e2e with `stripe listen` and test clocks (advance 7 days → invoice paid; cancel in the portal during trial → no invoice).
- Web: `scripts/screenshots/flow-smoke.mjs` plus new pricing and billing screenshots; typecheck / build via `scripts/build-web.sh` from a clean worktree.
- Self-valuation: the report is reachable at `/v/<id>`, the badge says "Real — self-assessment", the audit log shows an independent approver, and `/verify/BLKID` resolves after issuance.
