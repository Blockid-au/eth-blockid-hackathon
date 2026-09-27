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

## Sign-in without MetaMask and email (27 Sep 2026)

- **Try it now (guest):** the browser creates a private key (`web/app/src/devicewallet.ts`, IndexedDB, AES-GCM with a
  non-extractable key) and signs SIWE with `method: "guest"`. Guest sessions last 30 days and are never admin.
  `OPEN_ISSUE=1` (default) lets any signed-in wallet submit its company; admin approval is still required.
- **Google:** set `GOOGLE_CLIENT_ID=<id>.apps.googleusercontent.com` in `/opt/blockid/app.env` (OAuth client of type
  *Web application*, authorised JavaScript origin `https://eth.blockid.au`, no redirect URI needed), then recreate
  `agents-api`. The API verifies the ID token (`studio/accounts.py`) and links `google:<sub>` to the browser key's address.
- **Email from info@blockid.au** (`studio/mailer.py`, Google Workspace): either
  `SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_USER=info@blockid.au SMTP_PASSWORD=<App Password>` or the Workspace SMTP
  relay `SMTP_HOST=smtp-relay.gmail.com` with this VM's IP 34.151.85.207 allow-listed (no user/password).
  `MAIL_FROM="BlockID Business Passport <info@blockid.au>"`; replies go to info@blockid.au. Test as admin:
  `POST /api/v1/admin/mail/test {"to": "..."}`. A welcome email is sent on the first Google sign-in.
- CSP allows `https://accounts.google.com/gsi/*` (copy of the live snippet: `deploy/nginx/blockid-security-headers.conf`).
- First-visit check: `scripts/screenshots/try-demo.mjs` (home → Try it now → portfolio → account → /start).

## Operations: incidents, logs, usage statistics, weekly report (27 Sep 2026)

Plan: [PLAN-OPS.md](PLAN-OPS.md) · per-incident fixes: [RUNBOOK-INCIDENTS.md](RUNBOOK-INCIDENTS.md) · code
`agents/src/blockid_agents/ops/` (API contract in `ops/__init__.py`) · admin page `/admin/ops`.

- **Monitor:** a thread in `agents-api` runs the check registry (`ops/checks.py`) every 60 s. Only one API process
  runs it (Postgres advisory lock `blockid.ops.monitor`). Failing checks open incidents (`studio.ops_incidents`,
  one per fingerprint), recovery resolves them. Emails go to `OPS_ALERT_TO`: critical immediately, warnings batched
  every 15 min, a reminder after 2 h if not acknowledged, one on resolve, at most 10 an hour.
- **Without SMTP** everything is stored and shown in Admin > Ops with "not emailed — SMTP not configured". Once
  `SMTP_*` is set (see "Email from info@blockid.au" above) and `agents-api` is recreated, open incidents and the
  latest report (< 8 days) are sent on the next round. Test: Admin > Ops > Send test email, or
  `POST /api/v1/admin/ops/test-email`.
- **Worker heartbeat:** `agents-worker` writes `studio.ops_checks_state` row `_hb:worker` every 30 s.
- **Logs:** api / worker / issuer log JSON lines (`LOG_FORMAT=text` for the old format); each API response carries
  `X-Request-ID`, and one `blockid.access` line per request has route template, status, latency and a hashed user
  (never the IP or address). Docker rotates app-container logs (json-file 20 MB x 10). ERROR+ records (with
  traceback) are also stored in `studio.ops_errors` for 30 days, deduplicated by fingerprint with a count
  (Admin > Ops > Logs).
- **nginx logs → traffic:** compose mounts the host's `/var/log/nginx` read-only at `/host-logs/nginx` in
  `agents-api` and adds group `adm` (gid 4; the live logs are `www-data:adm 0640`). Hourly, the leader re-reads
  `<host>.access.log`, `.1` and `.2.gz` for eth / hr / scan and upserts `studio.ops_traffic_daily` (UTC days; a
  day is only replaced by a parse that saw at least as many requests). Unique visitors = daily-salted HMAC of
  IP + user agent, computed in memory only; no raw IP is stored; bots / scanners / HeadlessChrome are filtered.
  Host logrotate keeps 14 days (`/etc/logrotate.d/nginx`). Countries appear only if nginx logs `$http_cf_ipcountry`
  as an extra quoted field (see `ops/traffic.py`).
- **Weekly report:** Monday 08:00 Australia/Sydney to `OPS_REPORT_TO`, stored in `studio.ops_reports` (Admin > Ops
  > Reports: preview, history, send now). Deploys section: run `scripts/record-deploy.sh "<what>"` after each
  deploy (appends to `/mnt/app-data/agents/deploys.log` = `/data/deploys.log` in the container); optional
  `OPS_GIT_DIR` (read-only repo mount) adds the week's `git log`.
- **First deploy of ops** (compose changed: nginx log mount, `group_add`, `extra_hosts`, log rotation):
  rebuild + `up -d --no-build agents-api agents-worker issuer` (the containers are recreated), then
  `scripts/record-deploy.sh "ops monitor"`.

| Env (app.env) | Default | Meaning |
|---|---|---|
| `OPS_ENABLED` | `1` | `0` stops the monitor (checks, mail, reports); error capture stays on |
| `OPS_ALERT_TO` / `OPS_REPORT_TO` | `admin@blockid.au` | incident emails / reports (comma list allowed; report defaults to alert) |
| `OPS_DAILY_DIGEST` | `0` | `1` = daily digest at 08:00 Sydney as well |
| `OPS_INTERVAL_SECONDS` | `60` | monitor round |
| `OPS_MAX_EMAILS_PER_HOUR` / `OPS_WARN_BATCH_MINUTES` / `OPS_REMINDER_HOURS` | `10` / `15` / `2` | email policy |
| `OPS_HSK_WARN` / `OPS_ETH_WARN` / `OPS_BLKD_WARN` | `0.02` / `0.05` / `10` | issuer balance warn (critical: `*_CRIT` 0.005 / 0.01 / 1) |
| `OPS_DISK_WARN_PCT` / `OPS_DISK_CRIT_PCT` | `80` / `90` | disk |
| `OPS_TLS_WARN_DAYS` / `OPS_TLS_CRIT_DAYS` | `14` / `3` | certificates (edge + origin via `OPS_TLS_ORIGIN`, compose `host.docker.internal`) |
| `OPS_5XX_WARN_PCT` / `OPS_5XX_CRIT_PCT` / `OPS_5XX_MIN_COUNT` | `2` / `10` / `5` | API 5xx share over 15 min |
| `OPS_WORKER_STALE_SECONDS` / `OPS_QUEUE_WARN_MINUTES` / `OPS_QUEUE_CRIT_MINUTES` | `300` / `15` / `60` | worker / queue |
| `OPS_ERRORS_WARN` / `OPS_ERROR_RETENTION_DAYS` | `20` / `30` | error-log burst / retention |
| `OPS_DB_SIZE_WARN_GB` | `20` | Postgres size |
| `OPS_PROBE_URLS` | eth `/api/healthz`, eth `/`, hr `/`, scan `/` | `site.up` probes |
| `OPS_DEPLOY_LOG` / `OPS_GIT_DIR` | `/data/deploys.log` / empty | deploys in the weekly report |
| `OPS_IP_SALT_SECRET` | `SESSION_SECRET` | secret of the daily visitor-hash salt |

All thresholds and paths: `agents/src/blockid_agents/ops/config.py`.
