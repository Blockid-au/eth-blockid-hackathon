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
