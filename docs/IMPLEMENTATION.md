# BlockID Issuance Studio — implementation spec

> **Update (26 Sep 2026):** issuance is now one admin approval that runs BlockID → Hoodi → HashKey (`approve-anchor` is only a retry/re-sync), and `anchorValuation` stores keccak256 of the canonical report JSON (see `studio/report_hash.py`, `/verify`). Current diagrams: [ARCHITECTURE-DIAGRAMS.md](ARCHITECTURE-DIAGRAMS.md).


Source of truth for the parallel build. Plan: https://claude.ai/artifact/YaGUNf6oJfiUmc3UwNrzhg ·
visual prototype (copy its design, copy and charts): https://claude.ai/artifact/8Sr8pjR2ZhaiivVcNiKjjw
(local copy: `docs/prototype.html`).

## Ground rules

- AI agents (research/valuation/etc.) never sign or send transactions. Only the **issuer service** holds keys,
  and it only acts on a DB row that an **admin** approved.
- Testnet only. Every page shows "Testnet demo. Not an offer of securities."
- Default language English; Vietnamese only when the user clicks the VI flag (persist in localStorage).
- Default issue price **A$1.00 per share**: `total_shares = round(valuation_mid_aud / 1)`.
- Share tokens: `decimals = 0`, ticker = 3 uppercase letters (ASX style).

## Runtime topology (docker compose project `blockid-app`, `deploy/vm-app/`)

| service | port (host) | notes |
|---|---|---|
| nginx (host) | 443 | `/` → static `web/dist`, `/api/` → agents-api, `/rpc` → evmd, `/explorer/` → ping.pub |
| agents-api | 127.0.0.1:8080 | FastAPI (`python -m blockid_agents api`), exposes `/v1/...` (nginx strips `/api`) |
| agents-worker | – | job queue worker (AI graphs) |
| issuer | internal :8090 only | `python -m blockid_agents issuer`; keystores mounted read-only |
| postgres | internal | db `blockid`; studio tables in schema `studio` |
| evmd | 127.0.0.1:8545 | BlockID Chain, EVM chain id 262626 |
| blockscout | scan.blockid.au | EVM explorer |

Env (in `/opt/blockid/app.env`, passed to api/worker/issuer):
`DATABASE_URL, BLOCKID_API_KEY, ADMIN_WALLETS (comma list), ADMIN_USERNAME=admin, ADMIN_PASSWORD_HASH (bcrypt),
SESSION_SECRET, ISSUER_URL=http://issuer:8090, ISSUER_INTERNAL_TOKEN, LOCAL_RPC_URL=http://evmd:8545,
LOCAL_CHAIN_ID=262626, HOODI_RPC_URL, HOODI_CHAIN_ID=560048, HOODI_CAPTABLE_ANCHOR, LOCAL_DEMO_AUD,
KEYSTORE_DIR=/keys, DEPLOYER_ACCOUNT=blockid-deployer, RELAYER_ACCOUNT=blockid-relayer, (password files in /keys/*.password),
CONTRACTS_OUT=/app/contracts/out, PUBLIC_BASE_URL=https://eth.blockid.au, VALUATIONS_PER_DAY=3`.

Admin wallets: `0xc309691C60957A55bB619383A06d3F69A94f4585` (owner MetaMask), `0xC40052702B48631C26AD7c88b499bF230faCa21F` (server keystore `blockid-admin`).
Issuer (deployer) `0x2567Bb502ac840cF93957C60A410160a8cCb5ddf`, relayer `0x1B43f0d3297F79cE6c8BbA12F4FadFBE9112DA4a`.

## Database (Postgres, schema `studio`) — file `agents/src/blockid_agents/studio/schema.sql`, applied idempotently at API start

```sql
CREATE SCHEMA IF NOT EXISTS studio;
CREATE TABLE IF NOT EXISTS studio.admin_users (username text PRIMARY KEY, password_hash text NOT NULL, must_change boolean NOT NULL DEFAULT true);
CREATE TABLE IF NOT EXISTS studio.sessions (id text PRIMARY KEY, address text, username text, role text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL);
CREATE TABLE IF NOT EXISTS studio.nonces (nonce text PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS studio.valuations (id text PRIMARY KEY, url text NOT NULL, requested_by text, status text NOT NULL, steps jsonb NOT NULL DEFAULT '[]', result jsonb, error text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
ALTER TABLE studio.valuations ADD COLUMN IF NOT EXISTS self_reported jsonb;  -- founder-provided figures (optional)
CREATE TABLE IF NOT EXISTS studio.companies (
  id serial PRIMARY KEY, ticker text UNIQUE NOT NULL, name text NOT NULL, website text, valuation_id text REFERENCES studio.valuations(id),
  svi numeric, grade text, valuation_aud numeric NOT NULL, share_price_aud numeric NOT NULL DEFAULT 1, total_shares bigint NOT NULL,
  status text NOT NULL,          -- draft|pending_issue|issuing|issued|pending_anchor|anchoring|anchored|rejected|failed
  created_by text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  local_registry text, local_token text, local_distributor text, local_block bigint,
  hoodi_registry text, hoodi_token text, hoodi_anchor_tx text, merkle_root text, anchored_block bigint, anchored_at timestamptz,
  error text);
CREATE TABLE IF NOT EXISTS studio.holders (id serial PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id) ON DELETE CASCADE, name text NOT NULL, wallet text NOT NULL, pct numeric NOT NULL, shares bigint NOT NULL);
CREATE TABLE IF NOT EXISTS studio.marks (id serial PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id) ON DELETE CASCADE, at timestamptz NOT NULL DEFAULT now(), valuation_aud numeric NOT NULL, mark_aud numeric NOT NULL, source text NOT NULL, ref text);
CREATE TABLE IF NOT EXISTS studio.events (id serial PRIMARY KEY, company_id int REFERENCES studio.companies(id) ON DELETE CASCADE, kind text NOT NULL, at timestamptz NOT NULL DEFAULT now(), chain text, tx_hash text, block bigint, data jsonb NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS studio.mints (id serial PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id), to_wallet text NOT NULL, holder_name text NOT NULL, shares bigint NOT NULL, reason text, status text NOT NULL, requested_by text, tx_hash text, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS studio.dividends (id serial PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id), total_units bigint NOT NULL, merkle_root text, claims jsonb, status text NOT NULL, requested_by text, round_id int, tx_hash text, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS studio.issuer_wallets (address text PRIMARY KEY, label text NOT NULL, status text NOT NULL, granted_by text, granted_at timestamptz, revoked_at timestamptz);
CREATE TABLE IF NOT EXISTS studio.audit (id serial PRIMARY KEY, at timestamptz NOT NULL DEFAULT now(), actor text NOT NULL, action text NOT NULL, target text, detail jsonb NOT NULL DEFAULT '{}');
```
`events.kind` values: `issued, kyc, drip, minted, valuation_anchored, revalued, hoodi_mirrored, anchored, dividend_created, dividend_claimed, mint_requested, rejected`.
`marks.source`: `issuance | revaluation`. Mark at issuance = 1.00; revaluation mark = new_valuation / total_shares.

## HTTP API (agents-api; public path prefix `/api`)

Auth: cookie `bid_session` (HttpOnly, Secure, SameSite=Lax, 12 h). Roles: `user` (any SIWE wallet), `admin`
(SIWE wallet in ADMIN_WALLETS, or username/password). JSON errors: `{"detail": "..."}`.

| method & path | role | body → response |
|---|---|---|
| GET `/v1/auth/nonce` | – | → `{nonce}` |
| POST `/v1/auth/siwe` | – | `{message, signature}` (EIP-4361, domain `eth.blockid.au`, chain 262626 or 560048) → `{address, role}` + cookie |
| POST `/v1/auth/login` | – | `{username, password}` → `{role:"admin", must_change}`; 5 failures / 15 min per IP → 429 |
| POST `/v1/auth/change-password` | admin(pw) | `{current, new}` (min 10 chars) → `{ok}` |
| POST `/v1/auth/logout` | any | → `{ok}` |
| GET `/v1/auth/me` | any | → `{address?, username?, role, must_change?}` or 401 |
| POST `/v1/studio/valuations` | user | `{url, metrics?:{revenue_ttm_aud,revenue_growth_yoy_pct,gross_margin_pct,customers,raised_to_date_aud,runway_months,employees}}` (all optional; founder-provided, stored in `studio.valuations.self_reported`, overrides website figures, scored dimensions get basis `self_reported`) → `{id}` (429 after VALUATIONS_PER_DAY per wallet/day; admin unlimited) |
| GET `/v1/studio/valuations/{id}` | owner/admin | → `{id,url,status,steps:[{key,status,detail,at}],counters:{pages,competitors,sources},profile,competitors:[{name,url,raised_aud|null,note,sources}],market,svi:{index,band,dimensions:{name:{score,basis,rationale}},weights,valuation_low_aud,valuation_mid_aud,valuation_high_aud,method,narrative},self_reported:{...}|null,warnings:[...],error}`; basis: `computed|ai_suggested|human|self_reported`; status: `queued|running|waiting_approval|approved|rejected|failed` |
| GET `/v1/studio/valuations/{id}/evidence` | owner/admin | → `[{url,title,snippet,retrieved_at}]` |
| POST `/v1/studio/valuations/{id}/decision` | admin | `{approved, overrides?:{dimension:score}}` → updated valuation |
| GET `/v1/studio/tickers/suggest?name=` | user | → `{candidates:[{ticker,available,rule}]}` (3 suggestions, first available preferred) |
| POST `/v1/studio/companies` | user | `{valuation_id, name, ticker, share_price_aud?=1, total_shares?, holders:[{name,wallet,pct}]}` → company (status `draft`); validates pct sum = 100.00, EIP-55 addresses, unique ticker, approved valuation |
| POST `/v1/studio/companies/{id}/submit` | owner | → status `pending_issue` |
| GET `/v1/admin/approvals` | admin | → `{valuations:[...waiting_approval], companies:[pending_issue|issued (awaiting anchor)], mints:[pending], dividends:[pending]}` |
| POST `/v1/admin/companies/{id}/approve-issue` | admin | → 202; issuer issues on BlockID Chain; status issuing→issued (or failed) |
| POST `/v1/admin/companies/{id}/approve-anchor` | admin | → 202; issuer mirrors + anchors on Hoodi; anchoring→anchored |
| POST `/v1/admin/companies/{id}/reject` | admin | `{reason}` |
| POST `/v1/admin/companies/{id}/revalue` | admin | `{valuation_aud, note}` → new mark + event `revalued` (+ re-anchor) |
| GET `/v1/companies` | – | → `[{ticker,name,website,grade,svi,valuation_aud,total_shares,mark_aud,change_7d,change_30d,spark_30d:[number],holders,status,local_token,hoodi_token,anchored}]` |
| GET `/v1/companies/{ticker}` | – | → above + `{cap_table:[{name,wallet,shares,pct}], events:[...], marks:[{at,mark_aud,source}], local:{chain_id,registry,token,distributor,block}, hoodi:{chain_id,registry,token,anchor_tx,merkle_root,block}}` (cap table balances read from chain) |
| POST `/v1/companies/{ticker}/mints` | owner/admin | `{to_wallet, holder_name, shares, reason}` → pending mint |
| POST `/v1/admin/mints/{id}/approve` | admin | → issuer: KYC+drip if new, `issue`, re-anchor |
| POST `/v1/companies/{ticker}/dividends` | owner/admin | `{total_maud}` → pending dividend with merkle plan (pro-rata by chain balances, round down) |
| POST `/v1/admin/dividends/{id}/approve` | admin | → issuer: approve + createRound on local distributor (DemoAUD), relayer `claimFor` all |
| GET `/v1/platform/stats` | – | → `{as_of, block, kpis:{companies,tokens,shares,tx_value_aud,total_valuation_aud,avg_valuation_aud,median_valuation_aud,avg_mark,anchored,anchored_total}, series:{days:[iso], value_aud:[..], companies:[..]}, grades:{A..E:n}, movers:[{ticker,name,change_30d}], activity:[{at,ticker,kind,text,tx_hash,chain}]}` |
| GET/POST `/v1/admin/issuer-wallets` | admin | list / `{address,label}` add (status active) |
| POST `/v1/admin/issuer-wallets/{address}/revoke` | admin | |
| GET `/v1/admin/audit` | admin | → last 200 audit rows |
| GET `/v1/admin/wallets` | admin | → `{admins:[...], issuer:{address,local_balance,hoodi_balance}, relayer:{...}}` (admin wallet addresses shown only here) |

Only wallets that are admins or active `issuer_wallets` may call `POST /v1/studio/companies/{id}/submit`.

## Issuer service (internal, `blockid_agents/issuer/`)

HTTP on :8090, header `X-Internal-Token: $ISSUER_INTERNAL_TOKEN`. All endpoints return 202 and do the work in a
background thread, updating `studio.companies/mints/dividends` status + `studio.events` rows with tx hashes.

- `POST /issue {company_id}` (company must be `issuing`): on BlockID Chain deploy IdentityRegistry(issuer) → grant KYC_AGENT_ROLE
  to issuer → BlockIDShareToken(issuerSafe=issuer, transferAgent=issuer, lockupUntil=0, maxShareholders=500) →
  DividendDistributor(token, issuer) → for each holder `registerInvestor(wallet, 36, now+1y, keccak(holder name))` + drip
  0.01 BLKD if balance < 0.001 → `issue(wallet, shares, keccak("studio-issue:"+id))` → `anchorValuation(keccak(valuation id), round(mark*100))`
  → marks row (1.00, issuance) → status `issued`.
- `POST /anchor {company_id}` (status `anchoring`): on Hoodi deploy IdentityRegistry + BlockIDShareToken mirror (same name/ticker),
  register + issue same balances, `pause()`; compute OZ Merkle root over `(holder, balance)` leaves
  (`keccak256(bytes.concat(keccak256(abi.encode(address,uint256))))`, sorted pairs) and call
  `CapTableAnchor.anchor(ticker, localToken, 262626, localBlock, root, totalSupply, uri)` → status `anchored`.
- `POST /mint {mint_id}`, `POST /dividend {dividend_id}`, `POST /revalue {company_id}` (re-anchor), `GET /health` → addresses + balances.
- Keys: decrypt `/keys/blockid-deployer` and `/keys/blockid-relayer` (Foundry/geth JSON keystores) with the matching
  `/keys/*.password` using `eth_account.Account.decrypt`. Never log keys.
- ABIs/bytecode from `CONTRACTS_OUT/<File>.sol/<Contract>.json` (`abi`, `bytecode.object`).
- Nonce handling: one lock per chain; wait for each receipt; on failure set status `failed` + `error`.

## Contracts (`contracts/`)

- `src/CapTableAnchor.sol` (Hoodi, deployed once): AccessControl, `ANCHOR_ROLE`;
  `anchor(string ticker, address localToken, uint256 localChainId, uint64 localBlock, bytes32 merkleRoot, uint256 totalSupply, string uri)`
  → stores `latest[ticker]` struct + emits `Anchored(ticker indexed hash, ticker, localToken, localChainId, localBlock, merkleRoot, totalSupply, uri, anchorIndex)`;
  `latest(string) view`, `anchorCount(string) view`, `verify(string ticker, address holder, uint256 balance, bytes32[] proof) view returns (bool)`.
- `src/DemoAUD.sol`: move from `script/HoodiDemo.s.sol` (owner-mintable, 6 decimals); deployed once on BlockID Chain for dividends.
- `script/DeployPlatform.s.sol`: deploys CapTableAnchor on Hoodi (grants ANCHOR_ROLE to issuer) and DemoAUD on BlockID Chain.
- Tests in `test/CapTableAnchor.t.sol` (incl. proof verification with an OZ-compatible tree).

## Frontend (`web/app` → build to `web/dist`)

Vite + React + TypeScript + react-router, i18n via a small dictionary module (EN default, VI on flag click, persisted),
viem for MetaMask (SIWE, `wallet_addEthereumChain`, `wallet_switchEthereumChain`, `wallet_watchAsset`). Charts are
hand-drawn SVG as in the prototype. Routes: `/` home, `/new` wizard (8 steps), `/v/:id` valuation progress/report,
`/c/:ticker` company (cap table, contract address cards, add-to-wallet, mint/dividend), `/companies` list,
`/admin` (login: SIWE wallet in ADMIN_WALLETS or a username/password configured via ADMIN_PASSWORD_HASH; overview dashboard, approvals queue, companies, issuer wallets, audit).
Design tokens, copy, flows and charts: copy the prototype.

## File ownership during the build

- contracts + issuer: `contracts/**`, `agents/src/blockid_agents/issuer/**`, `agents/tests/test_issuer*.py`
- backend: all other `agents/**` (incl. `pyproject.toml`, `studio/**`, `api.py`, `graph.py`, agents, tools, tests)
- frontend: `web/app/**`
- infra (lead): `deploy/**`, nginx, `/opt/blockid/app.env`, Blockscout, evmd config, `docs/**`
