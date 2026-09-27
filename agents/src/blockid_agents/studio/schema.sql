CREATE SCHEMA IF NOT EXISTS studio;
CREATE TABLE IF NOT EXISTS studio.admin_users (username text PRIMARY KEY, password_hash text NOT NULL, must_change boolean NOT NULL DEFAULT true);
CREATE TABLE IF NOT EXISTS studio.sessions (id text PRIMARY KEY, address text, username text, role text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL);
CREATE TABLE IF NOT EXISTS studio.nonces (nonce text PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS studio.valuations (id text PRIMARY KEY, url text NOT NULL, requested_by text, status text NOT NULL, steps jsonb NOT NULL DEFAULT '[]', result jsonb, error text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
ALTER TABLE studio.valuations ADD COLUMN IF NOT EXISTS self_reported jsonb;  -- founder-provided figures (optional)
CREATE TABLE IF NOT EXISTS studio.companies (
  id serial PRIMARY KEY, ticker text UNIQUE NOT NULL, name text NOT NULL, website text, valuation_id text REFERENCES studio.valuations(id),
  svi numeric, grade text, valuation_aud numeric NOT NULL, share_price_aud numeric NOT NULL DEFAULT 1, total_shares bigint NOT NULL,
  status text NOT NULL,          -- draft|pending_issue|issuing|issued|pending_anchor|anchoring|anchored|partially_anchored|rejected|failed
  created_by text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  local_registry text, local_token text, local_distributor text, local_block bigint,
  hoodi_registry text, hoodi_token text, hoodi_anchor_tx text, merkle_root text, anchored_block bigint, anchored_at timestamptz,
  error text);
-- multi-chain sync (BlockID Chain -> Ethereum Hoodi -> HashKey Chain testnet); see issuer/syncstate.py
ALTER TABLE studio.companies ADD COLUMN IF NOT EXISTS hsk_registry text;
ALTER TABLE studio.companies ADD COLUMN IF NOT EXISTS hsk_token text;
ALTER TABLE studio.companies ADD COLUMN IF NOT EXISTS hsk_anchor_tx text;
ALTER TABLE studio.companies ADD COLUMN IF NOT EXISTS hsk_merkle_root text;
ALTER TABLE studio.companies ADD COLUMN IF NOT EXISTS hsk_block bigint;
ALTER TABLE studio.companies ADD COLUMN IF NOT EXISTS hsk_anchored_at timestamptz;
ALTER TABLE studio.companies ADD COLUMN IF NOT EXISTS sync jsonb NOT NULL DEFAULT '{}';
ALTER TABLE studio.companies ADD COLUMN IF NOT EXISTS valuation_report_hash text;  -- keccak256(canonical report JSON), studio/report_hash.py
CREATE TABLE IF NOT EXISTS studio.holders (id serial PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id) ON DELETE CASCADE, name text NOT NULL, wallet text NOT NULL, pct numeric NOT NULL, shares bigint NOT NULL);
CREATE TABLE IF NOT EXISTS studio.marks (id serial PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id) ON DELETE CASCADE, at timestamptz NOT NULL DEFAULT now(), valuation_aud numeric NOT NULL, mark_aud numeric NOT NULL, source text NOT NULL, ref text);
CREATE TABLE IF NOT EXISTS studio.events (id serial PRIMARY KEY, company_id int REFERENCES studio.companies(id) ON DELETE CASCADE, kind text NOT NULL, at timestamptz NOT NULL DEFAULT now(), chain text, tx_hash text, block bigint, data jsonb NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS studio.mints (id serial PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id), to_wallet text NOT NULL, holder_name text NOT NULL, shares bigint NOT NULL, reason text, status text NOT NULL, requested_by text, tx_hash text, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS studio.dividends (id serial PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id), total_units bigint NOT NULL, merkle_root text, claims jsonb, status text NOT NULL, requested_by text, round_id int, tx_hash text, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS studio.issuer_wallets (address text PRIMARY KEY, label text NOT NULL, status text NOT NULL, granted_by text, granted_at timestamptz, revoked_at timestamptz);
CREATE TABLE IF NOT EXISTS studio.audit (id serial PRIMARY KEY, at timestamptz NOT NULL DEFAULT now(), actor text NOT NULL, action text NOT NULL, target text, detail jsonb NOT NULL DEFAULT '{}');
-- secondary transfers (studio/transfers.py): free = holder-signed transfer, approval = admin -> issuer forcedTransfer
ALTER TABLE studio.companies ADD COLUMN IF NOT EXISTS transfer_mode text NOT NULL DEFAULT 'free';
CREATE TABLE IF NOT EXISTS studio.transfers (id serial PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id) ON DELETE CASCADE, from_wallet text NOT NULL, to_wallet text NOT NULL, to_name text NOT NULL DEFAULT '', shares bigint NOT NULL, mode text NOT NULL, status text NOT NULL, tx_hash text UNIQUE, block bigint, note text, requested_by text, decided_by text, decided_at timestamptz, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS studio.kyc_requests (id serial PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id) ON DELETE CASCADE, wallet text NOT NULL, name text NOT NULL, status text NOT NULL, tx_hash text, note text, requested_by text, decided_by text, decided_at timestamptz, created_at timestamptz NOT NULL DEFAULT now());
-- per-company admin wallets (studio/company_admins.py); on-chain roles on the company's BlockID contracts via issuer/roles.py
CREATE TABLE IF NOT EXISTS studio.company_admins (
  id serial PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id) ON DELETE CASCADE,
  address text NOT NULL,                                   -- EIP-55 checksum
  label text NOT NULL DEFAULT '',
  role text NOT NULL DEFAULT 'manager' CHECK (role IN ('owner','manager')),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','pending_grant','revoked')),
  onchain boolean NOT NULL DEFAULT false,                  -- holds (or is being granted) roles on the BlockID contracts
  grant_tx text, revoke_tx text, error text,
  added_by text, added_at timestamptz NOT NULL DEFAULT now(), revoked_at timestamptz,
  UNIQUE (company_id, address));
CREATE INDEX IF NOT EXISTS company_admins_address_idx ON studio.company_admins (lower(address));
-- backfill: the wallet that created a company is its first owner (idempotent; a revoked row is never re-added)
INSERT INTO studio.company_admins (company_id, address, label, role, status, added_by)
  SELECT id, created_by, 'creator', 'owner', 'active', 'backfill' FROM studio.companies
  WHERE created_by ~ '^0x[0-9a-fA-F]{40}$' ON CONFLICT (company_id, address) DO NOTHING;
-- default BLKD gas allowance per wallet (studio/gas.py): at most one issuer /drip per wallet per 24 h, global daily cap
CREATE TABLE IF NOT EXISTS studio.gas_drips (address text PRIMARY KEY, amount_wei numeric NOT NULL, tx_hash text, reason text, created_at timestamptz NOT NULL DEFAULT now());
-- accounts for guest / Google sign-in (keys stay in the browser; accounts.py)
CREATE TABLE IF NOT EXISTS studio.accounts (id serial PRIMARY KEY, provider text NOT NULL, subject text NOT NULL, email text, name text, picture text, created_at timestamptz NOT NULL DEFAULT now(), last_login_at timestamptz, UNIQUE (provider, subject));
CREATE TABLE IF NOT EXISTS studio.account_wallets (account_id int NOT NULL REFERENCES studio.accounts(id) ON DELETE CASCADE, address text NOT NULL, kind text NOT NULL DEFAULT 'device', linked_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (account_id, address));
ALTER TABLE studio.sessions ADD COLUMN IF NOT EXISTS account_id int;
ALTER TABLE studio.sessions ADD COLUMN IF NOT EXISTS auth_method text;
-- business updates (studio/updates.py, studio/update_draft.py): KPI values per period, drafted updates,
-- approved by a person, then the issuer records the content hash on BlockID Chain (issuer/service.py disclose)
CREATE TABLE IF NOT EXISTS studio.kpi_values (
  id bigserial PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id) ON DELETE CASCADE,
  period_end date NOT NULL, metric text NOT NULL, value numeric NOT NULL, unit text NOT NULL DEFAULT 'AUD',
  source text NOT NULL DEFAULT 'manual', entered_by text, created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (company_id, metric, period_end));
-- KPI values are kept per cadence (a weekly figure must not overwrite the monthly one ending the same day). One-time
-- backfill when the column is added: a value takes the cadence of the only update of its company ending that day.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='studio' AND table_name='kpi_values'
                 AND column_name='cadence') THEN
    ALTER TABLE studio.kpi_values ADD COLUMN cadence text NOT NULL DEFAULT 'monthly';
    IF to_regclass('studio.updates') IS NOT NULL THEN
      UPDATE studio.kpi_values k SET cadence = u.cadence FROM studio.updates u
        WHERE u.company_id = k.company_id AND u.period_end = k.period_end
          AND (SELECT count(DISTINCT u2.cadence) FROM studio.updates u2
               WHERE u2.company_id = k.company_id AND u2.period_end = k.period_end) = 1;
    END IF;
  END IF;
END $$;
ALTER TABLE studio.kpi_values ADD COLUMN IF NOT EXISTS cadence text NOT NULL DEFAULT 'monthly';
ALTER TABLE studio.kpi_values DROP CONSTRAINT IF EXISTS kpi_values_company_id_metric_period_end_key;
CREATE UNIQUE INDEX IF NOT EXISTS kpi_values_cadence_uidx ON studio.kpi_values (company_id, cadence, metric, period_end);
CREATE TABLE IF NOT EXISTS studio.updates (
  id text PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id) ON DELETE CASCADE,
  cadence text NOT NULL CHECK (cadence IN ('weekly','monthly','quarterly','annual')),
  period_start date NOT NULL, period_end date NOT NULL,
  status text NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','pending_approval','publishing','published','rejected','failed')),
  title text NOT NULL DEFAULT '', body jsonb NOT NULL DEFAULT '{}',   -- {summary, highlights[], risks[], kpis[], note}
  content_hash text, anchor jsonb,                                     -- {chain, chain_id, tx_hash, block, to}
  created_by text, approved_by text, published_at timestamptz, error text, reason text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (company_id, cadence, period_end));
CREATE INDEX IF NOT EXISTS updates_status_idx ON studio.updates (status, company_id);
-- automatic dividends (studio/dividend_policy.py): one standing policy per company, approved once by a platform admin.
-- When a matching business update with a net profit is published, the API declares a dividend (source 'policy',
-- status 'scheduled', approved_by 'policy:<id>'); after pay_after (the veto window) it is handed to the issuer.
CREATE TABLE IF NOT EXISTS studio.dividend_policies (
  id serial PRIMARY KEY, company_id int NOT NULL UNIQUE REFERENCES studio.companies(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('payout_ratio','fixed')),
  ratio_pct numeric, fixed_maud numeric, max_maud_per_round numeric NOT NULL,
  frequency text NOT NULL CHECK (frequency IN ('monthly','quarterly')),
  veto_hours int NOT NULL DEFAULT 24 CHECK (veto_hours BETWEEN 1 AND 168),
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','pending_approval','active','paused','rejected')),
  reason text, active_since timestamptz,
  created_by text, approved_by text, approved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
ALTER TABLE studio.dividends ADD COLUMN IF NOT EXISTS policy_id int;
ALTER TABLE studio.dividends ADD COLUMN IF NOT EXISTS update_id text;
ALTER TABLE studio.dividends ADD COLUMN IF NOT EXISTS pay_after timestamptz;
ALTER TABLE studio.dividends ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'manual';
ALTER TABLE studio.dividends ADD COLUMN IF NOT EXISTS approved_by text;
ALTER TABLE studio.dividends ADD COLUMN IF NOT EXISTS note text;
CREATE UNIQUE INDEX IF NOT EXISTS dividends_update_uidx ON studio.dividends (update_id) WHERE update_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS dividends_status_idx ON studio.dividends (status, pay_after);
-- simulated share offering (studio/offerings.py, docs/UPGRADE-INVESTOR-PLAN.md 3f): terms + information pack approved by a
-- platform admin, reservations are DB commitments (no money moves on testnet), settlement = ONE issuer job that mints
-- every allocation through studio.mints (offering_id set), then one re-sync of the public copies.
CREATE TABLE IF NOT EXISTS studio.offerings (
  id serial PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id) ON DELETE CASCADE,
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','pending_approval','rejected','cancelled','open',
    'awaiting_settlement','settling','settled','released','failed')),
  price_aud numeric NOT NULL CHECK (price_aud > 0), shares_offered bigint NOT NULL CHECK (shares_offered > 0),
  min_raise_aud numeric NOT NULL DEFAULT 0 CHECK (min_raise_aud >= 0),
  max_per_investor_shares bigint NOT NULL CHECK (max_per_investor_shares > 0), max_holders int,
  closes_at timestamptz NOT NULL, cooling_off_days int NOT NULL DEFAULT 5,
  use_of_funds text NOT NULL DEFAULT '', pack jsonb, pack_hash text, reason text, close_reason text,
  created_by text, submitted_at timestamptz, approved_by text, approved_at timestamptz, opened_at timestamptz,
  closed_at timestamptz, closed_by text, settle_approved_by text, settle_approved_at timestamptz, settled_at timestamptz,
  error text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
-- at most one offering in progress per company
CREATE UNIQUE INDEX IF NOT EXISTS offerings_active_uidx ON studio.offerings (company_id)
  WHERE status IN ('draft','pending_approval','rejected','open','awaiting_settlement','settling','failed');
CREATE INDEX IF NOT EXISTS offerings_status_idx ON studio.offerings (status, closes_at);
CREATE TABLE IF NOT EXISTS studio.reservations (
  id serial PRIMARY KEY, offering_id int NOT NULL REFERENCES studio.offerings(id) ON DELETE CASCADE,
  company_id int NOT NULL REFERENCES studio.companies(id) ON DELETE CASCADE,
  wallet text NOT NULL, account_id int, name text NOT NULL DEFAULT '',
  shares bigint NOT NULL CHECK (shares > 0), amount_aud numeric NOT NULL,
  status text NOT NULL DEFAULT 'reserved' CHECK (status IN ('reserved','withdrawn','released','allocated')),
  risk_ack_at timestamptz NOT NULL, cooling_off_until timestamptz NOT NULL, withdrawn_at timestamptz, mint_id int,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS reservations_offering_idx ON studio.reservations (offering_id, status);
CREATE INDEX IF NOT EXISTS reservations_wallet_idx ON studio.reservations (lower(wallet));
ALTER TABLE studio.mints ADD COLUMN IF NOT EXISTS offering_id int;
CREATE UNIQUE INDEX IF NOT EXISTS mints_offering_wallet_uidx ON studio.mints (offering_id, lower(to_wallet))
  WHERE offering_id IS NOT NULL;
-- founding-team / person reviews (hr.blockid.au; studio/hr.py, agents/people.py, docs/PLAN-HR.md). A report is a
-- "team" (founding team of a business) or a "person" (one person vs a business or a role). The People Analyst runs in
-- the worker (studio/hr_store.py HrRunner); a done team report linked to a valuation re-scores its founder_quality.
CREATE TABLE IF NOT EXISTS studio.hr_teams (
  id text PRIMARY KEY, mode text NOT NULL DEFAULT 'team' CHECK (mode IN ('team','person')),
  valuation_id text REFERENCES studio.valuations(id) ON DELETE SET NULL,
  company_id int REFERENCES studio.companies(id) ON DELETE SET NULL,
  name text NOT NULL, website text, target jsonb,
  requested_by text NOT NULL, consent boolean NOT NULL DEFAULT false, consented_at timestamptz,
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','queued','running','done','failed')),
  steps jsonb NOT NULL DEFAULT '[]', result jsonb, error text, share_token text UNIQUE,
  started_at timestamptz, finished_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS hr_teams_requester_idx ON studio.hr_teams (lower(requested_by), created_at);
CREATE INDEX IF NOT EXISTS hr_teams_valuation_idx ON studio.hr_teams (valuation_id);
CREATE INDEX IF NOT EXISTS hr_teams_status_idx ON studio.hr_teams (status, updated_at);
CREATE TABLE IF NOT EXISTS studio.hr_people (
  id serial PRIMARY KEY, team_id text NOT NULL REFERENCES studio.hr_teams(id) ON DELETE CASCADE,
  full_name text NOT NULL, role text NOT NULL DEFAULT '',
  kind text NOT NULL DEFAULT 'employee' CHECK (kind IN ('founder','cofounder','executive','employee','advisor')),
  headline text, full_time boolean, start_year int, equity_pct numeric, urls jsonb NOT NULL DEFAULT '[]',
  bio text, cv text, position int NOT NULL DEFAULT 0, created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS hr_people_team_idx ON studio.hr_people (team_id, position);
-- one row per run request (daily per-wallet limit, HR_RUNS_PER_DAY)
CREATE TABLE IF NOT EXISTS studio.hr_runs (id serial PRIMARY KEY, team_id text NOT NULL, requested_by text NOT NULL,
  at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS hr_runs_requester_idx ON studio.hr_runs (lower(requested_by), at);
