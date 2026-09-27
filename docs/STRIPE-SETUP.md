# Stripe setup — BlockID billing (owner runbook)

Status: guide for the billing feature built behind `BILLING_ENABLED` (plan: `PLAN-BILLING.md`). Vietnamese
checklist: `STRIPE-SETUP.vi.md`. Prices come from the repo price book
`agents/src/blockid_agents/billing/pricebook/v1.yaml` (= price book v1 in `PLAN-GTM.md` §4); never type prices into
the Stripe Dashboard by hand — the sync script owns them.

**When money starts:** only after the EAG Global Buildathon results are announced and recorded (gate G0 in
`GATES.md`) + 7 days. Until then use **test mode** only. Judge / demo / sample / self-valuation paths are never charged.

---

## 1. Account (one-time, ~30 min)

1. Sign up at https://dashboard.stripe.com/register with admin@blockid.au.
2. **Activate payments** → Business type **Company** → legal entity:
   - now: **AUSCHAIN PTY LTD**, ABN 79 659 615 111, ACN 659 615 111 (see `COMPANY.md`);
   - later: **BlockID Pty Ltd** once registered (new ABN, GST, bank account). Create a *second* Stripe account for
     it and move customers at renewal — do not change the legal entity of a live account.
3. Directors / owners (Stripe KYC): Do Van Long, Truong Quoc Tuan as applicable; ID documents.
4. Bank account: AUD business account in the company name (payouts).
5. Public details: statement descriptor **`BLOCKID.AU`** (short: `BLOCKID`), support email info@blockid.au,
   website https://eth.blockid.au, support phone. Branding: BlockID™ logo, brand colour.

## 2. Tax (Stripe Tax)

1. Settings → Tax → **Enable Stripe Tax**; head office = Australia (NSW).
2. Registrations → add **Australia GST** (Auschain registered from 26 Mar 2025).
3. Default product tax code: **`txcd_10000000`** (electronically supplied services) — the sync sets it per product.
4. Tax behaviour per price comes from the price book: one-off reports **inclusive** (consumer price shows the total),
   plans **exclusive** ("+GST"). Checkout collects the address and ABN (`tax_id_collection`), so Australian businesses
   get a valid tax invoice and overseas customers are zero-rated where the law allows (confirm with the accountant).

## 3. Billing settings

- Settings → Billing → **Subscriptions and emails**:
  - Customer emails: successful payments, refunds, **"Send a reminder email before a free trial ends"** (card-network
    rule for free trials), upcoming renewals (annual plans), expiring cards, failed payments.
  - **Smart Retries** on; after all retries fail → **cancel the subscription** (our app also gives a 7-day grace).
- Settings → Billing → **Customer portal** (this is the "unsubscribe" place, in addition to the in-app Cancel button):
  - Allow: update payment method, view invoice history, **cancel subscriptions** (mode: *at end of billing period*;
    during a trial the app cancels immediately so the card is never charged), switch plans between Founder/Growth
    and monthly/yearly, cancellation reason (optional, must not block cancelling).
  - Business info: Terms and Privacy links (`/terms`, `/privacy` once published).
- Settings → Radar: default rules on; block if CVC fails.
- Australian law: from **1 Jul 2027** hard-to-cancel subscriptions are banned (Unfair Trading Practices Act 2026).
  We comply now: cancelling is one click in the app or the portal, same as sign-up.

## 4. API keys and webhook

1. Developers → API keys → **Create restricted key** "blockid-app" with:
   Write: Products, Prices, Coupons, Promotion codes, Customers, Checkout Sessions, Subscriptions,
   Customer portal, Invoices (read is enough), Refunds (read). Read: Events, Balance transactions.
   Make one in **test mode** first (`rk_test_…`), later the same in live (`rk_live_…`).
2. Developers → Webhooks → **Add endpoint** `https://eth.blockid.au/api/v1/billing/webhook`, API version = account
   default, events:
   `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`,
   `customer.subscription.deleted`, `customer.subscription.trial_will_end`, `invoice.paid`,
   `invoice.payment_failed`, `charge.refunded`. Copy the signing secret `whsec_…`.
3. Put them on the server (never in git, never in chat):
   ```bash
   sudo nano /opt/blockid/app.env
   # --- billing ---
   BILLING_ENABLED=1            # 0 = feature off, app behaves as before
   STRIPE_MODE=test             # test | live (the app refuses to start if the key prefix does not match)
   STRIPE_SECRET_KEY=rk_test_...
   STRIPE_WEBHOOK_SECRET=whsec_...
   STRIPE_PUBLISHABLE_KEY=pk_test_...
   BILLING_START_AT=            # empty = nothing is charged (pricing page shows "starts after launch")
   BILLING_TRIAL_DAYS=7
   BILLING_GRACE_DAYS=7
   BILLING_JUDGE_EMAILS=        # comma list, exempt until 30 days after results
   BILLING_JUDGE_WALLETS=
   BILLING_FREE_ALLOWLIST=      # e.g. the BlockID self-valuation id
   cd ~/blockid-eth-platform/deploy/vm-app
   sudo docker compose --env-file /opt/blockid/app.env -p blockid-app up -d --no-build --force-recreate agents-api agents-worker
   ```

## 5. Create the catalogue (products, prices, coupons)

```bash
# inside the agents-api container (reads STRIPE_* from the env file)
sudo docker compose --env-file /opt/blockid/app.env -p blockid-app exec agents-api \
  python -m blockid_agents.billing.sync            # dry run: prints what would change
sudo docker compose --env-file /opt/blockid/app.env -p blockid-app exec agents-api \
  python -m blockid_agents.billing.sync --apply    # creates/updates in Stripe
```
Or Admin → **Revenue → Sync prices** (dry run, then Apply). What it does:
- Products have fixed ids `bid_*`; prices are found by **lookup_key** (`founder_monthly`, `people_report`, …).
- A changed amount/interval/tax creates a **new price** with `transfer_lookup_key=true` and archives the old one
  (Stripe prices are immutable). Existing subscribers stay on their old price until you migrate them.
- Coupons `founding30` (30 % forever, first 50) and `pulley6` (6 months free) with promotion codes
  `FOUNDING30`, `PULLEY6`.
- The older helper `scripts/stripe/seed-prices.sh` uses the same lookup keys; prefer the Python sync (it also updates).

To change a price later: edit `pricebook/v1.yaml` (or add `v2.yaml`), commit, deploy, run sync. The `/pricing` page
reads `GET /v1/billing/catalog`, so no web deploy is needed for a price change.

## 6. Test mode end to end (before any real card)

```bash
# on a dev machine or the VM (Stripe CLI: https://docs.stripe.com/stripe-cli)
stripe login
stripe listen --forward-to localhost:8080/v1/billing/webhook   # prints a whsec_ for local testing
```
| Case | How | Expected |
|---|---|---|
| Buy one report | /pricing → People report → card `4242 4242 4242 4242` | order paid, 1 `people_report` credit, tax invoice email |
| Plan with 7-day trial | /pricing → Founder monthly → `4242…` | status *trialing*, 1 trial credit, "trial started" email |
| Trial reminder | `stripe trigger customer.subscription.trial_will_end` (or a test clock) | "trial ends in 3 days" email with one-click cancel |
| Auto charge after 7 days | Dashboard → Test clocks → advance 7 days | `invoice.paid`, status *active*, plan credits granted |
| Cancel during trial | /account/billing → Cancel | cancelled now, **no invoice** |
| Cancel after paying | Cancel | runs to period end, then free tier |
| Card fails | card `4000 0000 0000 0341`, advance clock | `invoice.payment_failed`, 7-day grace, then downgrade |
| Second trial abuse | same email or card again | trial refused, subscription cancelled, email explains |
| Judge account | account with segment `judge` runs a valuation | free, no 402 |
| Refund | Dashboard → refund | unspent credits reversed |

## 7. Go live (at G0 + 7 days)

1. Record the hackathon result in `docs/GATES.md` (G0) and restore normal caps from `/opt/blockid/app.env.bak-judging`.
2. 14 days before: set `BILLING_START_AT` in **test** mode so `/pricing` shows "Pricing starts on <date>".
3. Create the live restricted key + live webhook (same events), put `STRIPE_MODE=live`, live keys, run
   `billing.sync` (dry run → apply) against live.
4. Mark judge accounts (Admin → Revenue → Segments) and add the self-valuation id to `BILLING_FREE_ALLOWLIST`.
5. `BILLING_START_AT=<ISO date/time AEST>`; recreate `agents-api`/`agents-worker`.
6. Watch Admin → Revenue and `billing_events` errors for 72 h. **Rollback:** `BILLING_ENABLED=0` → app behaves
   as before; Stripe keeps collecting renewals, webhooks keep being recorded.

## 8. Money flow and accounting

- Payouts to the company bank account (default rolling 2–3 business days in AU).
- Fees: domestic cards ~1.7 % + A$0.30, international ~3.5 % + A$0.30 (check the current Stripe AU pricing page).
- Monthly: export Stripe payouts/invoices for BAS (GST collected), or connect Xero ↔ Stripe.
- Referral payouts (20 % year 1 to accountants/accelerators) are listed in Admin → Revenue and paid manually.
