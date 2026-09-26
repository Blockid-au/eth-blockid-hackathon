# Runbook: BlockID Startup Passport (single host, eth.blockid.au)

The live deployment (platform codename: Issuance Studio). Spec: [IMPLEMENTATION.md](IMPLEMENTATION.md) · facts: [FACTS.md](FACTS.md). Testnet only.

## What runs where

| Piece | Where | Notes |
|---|---|---|
| Web app (SPA) | `web/dist`, served by host nginx | source `web/app`; build: see below |
| API | container `agents-api` → `127.0.0.1:8080`, public at `https://eth.blockid.au/api/` | FastAPI; studio tables in Postgres schema `studio` |
| AI worker | container `agents-worker` | runs `site_valuation` jobs (LLM chain SambaNova → Claude bridge → DeepInfra; ≤3 web searches via Brave → Claude web-search bridge; see LLM-ROUTING.md) |
| Issuer | container `issuer`, internal `:8090` only | the only holder of keys (`/opt/blockid/keys`, read-only, uid 10001) |
| BlockID Chain | container `evmd`, RPC `127.0.0.1:8545`, public `https://eth.blockid.au/rpc` | EVM chain id 262626, gas price 0 |
| Blockscout | `deploy/blockscout`, `https://scan.blockid.au` | backend :8200, frontend :8201 |
| Ping.pub (Cosmos) | container `explorer`, `/explorer/` | Cosmos view of the same chain |

Compose: `cd deploy/vm-app && sudo docker compose --env-file /opt/blockid/app.env <cmd>`.
Blockscout: `cd deploy/blockscout && sudo docker compose --env-file /opt/blockid/blockscout.env <cmd>`.

## Secrets and keys

- `/opt/blockid/app.env` (root, 600): DB, API keys (SambaNova, DeepInfra, Brave), LLM/search chain, bridge URL + token, admin wallets + hash, session secret, RPC URLs, contract addresses.
  Values containing `$` (the bcrypt hash) must be single-quoted.
- `/opt/blockid/issuer.env`: `ISSUER_INTERNAL_TOKEN`, loaded only by `agents-api` and `issuer` (never the worker).
- `/opt/blockid/search-bridge.env`: token and daily caps for the host Claude bridge (`claude-search-bridge.service`).
- `/opt/blockid/blockscout.env`: Blockscout compose env.
- Keystores (encrypted, Foundry format): `~/.foundry/keystores/blockid-{deployer,relayer,admin}`, passwords in `~/.blockid/*.password` (600).
  Copies for the issuer: `/opt/blockid/keys` (owned by uid 10001, read-only mount).
- Wallets: issuer/deployer `0x2567…5ddf`, relayer `0x1B43…DA4a`, server admin `0xC400…a21F`, owner admin (MetaMask) `0xc309…4585`, project admin `0x02B1…1E2F`. Admin list = `ADMIN_WALLETS` in app.env (restart agents-api after editing).
- Admin login: SIWE wallet in `ADMIN_WALLETS`, or the username/password configured via `ADMIN_PASSWORD_HASH` (change it with `POST /api/v1/auth/change-password`).
- Platform contracts: CapTableAnchor (Hoodi) `0xF3dC95D5d207dE9f2aC98184Fd32b45B72334263`, CapTableAnchor (HashKey) `0x728c834DE493DC3e9Ae2f7C0e79d86701B6F9F04`, AgentProvenance (HashKey) `0x6B96bcE8937e1416Ec1DAC4ADAdD71FE879F8e84`, DemoAUD (BlockID) `0x286C1eD22A741F4939A3C7637011B0fAE2C7FFBc`.

## Common tasks

| Task | Command |
|---|---|
| Rebuild + restart backend | `sudo docker compose --env-file /opt/blockid/app.env build agents-api agents-worker issuer && sudo docker compose --env-file /opt/blockid/app.env up -d --no-build agents-api agents-worker issuer` |
| Build web app | `scripts/build-web.sh` (typecheck + build in node:20, keeps old hashed assets so open tabs keep working, swaps `index.html` atomically) |
| Backend tests | `cd agents && .venv/bin/python -m pytest -q` (Postgres flows need `TEST_DATABASE_URL`) |
| Contract tests | `cd contracts && ~/.foundry/bin/forge test` |
| Issuer health | `curl -s https://eth.blockid.au/api/v1/admin/wallets` with an admin session |
| Logs | `sudo docker compose --env-file /opt/blockid/app.env logs -f agents-worker issuer` |
| Seed real companies | `scripts/seed-companies.sh "https://site|Name|revalue_pct" ...` |
| Hoodi-only demo | `scripts/hoodi-demo.sh` |
| Token / contract registry → [DEPLOYMENTS.md](DEPLOYMENTS.md) | `agents/.venv/bin/python scripts/export-deployments.py` (Postgres + on-chain supply check on all three chains) |
| Retake screenshots | `scripts/screenshots/run.sh` (read-only; `ONLY='^15'` for a subset) |
| LLM chain (see [LLM-ROUTING.md](LLM-ROUTING.md)) | edit `LLM_PROVIDER_ORDER` / `SAMBANOVA_MODELS` / `DEEPINFRA_MODELS` in `/opt/blockid/app.env`, then `up -d --no-build --force-recreate agents-worker`; the startup log prints `cloud LLM chain: …` |
| Claude bridge (`/search` + `/complete`) | `sudo systemctl restart claude-search-bridge`; health `curl -s http://172.18.0.1:8765/healthz` (daily counters for both endpoints) |
| BlockID Chain gas | `cast gas-price --rpc-url http://127.0.0.1:8545` → 0; feemarket params `curl -s 127.0.0.1:1317/cosmos/evm/feemarket/v1/params`. Gov proposal #1 sets `no_base_fee=true` (expedited, voting ends 2026-09-27 04:08 UTC) |
| Demo holder wallets | `~/.blockid/holder-wallets/{ART,ARW}/` encrypted keystores + `password` + `index.tsv` (label → address); sign with `cast … --keystore <file> --password-file ~/.blockid/holder-wallets/password` |

## Funding

- **Hoodi ETH** for the issuer `0x2567…5ddf`: about 0.004 ETH per company (mirror + anchor). Faucet: https://hoodi-faucet.pk910.de.
- **BLKD** on BlockID Chain (gas is 0, but accounts need a balance for some wallets): send from the validator key inside `evmd`:
  `evmd debug addr <0x…>` → bech32, then `evmd tx bank send validator <bech32> <amount>ablkd --keyring-backend file --home /root/.evmd --chain-id blockid_262626-1 --gas-prices 10000000000ablkd -y`
  (keyring password = `EVMD_KEYRING_PASSWORD`). The issuer drips 0.01 BLKD to new holder wallets automatically.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Valuation shows "Search unavailable" warning | Brave quota exhausted or key missing; competitors come from the model and are verified by fetching their sites |
| Company stuck `issuing`/`anchoring` | `logs issuer`; a BlockID revert turns the status `failed` (retry = approve-issue again); a Hoodi/HSK failure leaves `partially_anchored` with the chain error (usually gas: top up the issuer), then **Re-sync** (approve-anchor) re-runs only that chain |
| Approve returns 502 | issuer container down: `up -d issuer` |
| Admin endpoints 403 "password change required" | `must_change` is true for the admin account |
| Blockscout lags | `logs backend` in `deploy/blockscout`; it indexes from genesis and catches up in minutes |
| Page 404 on reload | nginx must keep `try_files $uri /index.html` for `/` |
