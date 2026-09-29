# Runbook: incidents (ops monitor)

One section per ops check (`agents/src/blockid_agents/ops/checks.py`). Incident emails and **Admin > Ops** link to
these sections by anchor. Plan: [PLAN-OPS.md](PLAN-OPS.md); where things run: [RUNBOOK-STUDIO.md](RUNBOOK-STUDIO.md).

Conventions used below (single host, eth.blockid.au):

```bash
cd ~/blockid-eth-platform/deploy/vm-app
DC="sudo docker compose --env-file /opt/blockid/app.env"     # then: $DC ps, $DC logs ..., $DC restart ...
```

- Containers: `agents-api` (127.0.0.1:8080, `/api/` behind nginx), `agents-worker`, `issuer` (internal :8090),
  `postgres`, `evmd` (RPC 127.0.0.1:8545), `explorer`. Blockscout lives in `deploy/blockscout`.
- Logs are JSON lines (`docker compose logs`), rotated 20 MB x 10 per container. ERROR+ records are also in
  **Admin > Ops > Logs** with the traceback (30 days).
- After fixing, the incident resolves itself on the next monitor round (60 s) when the check passes; acknowledge
  it in Admin > Ops to stop reminders while you work.
- Severities: **critical** = emailed immediately; **warn** = batched digest every 15 min; **info** = Admin only.

| Check | Severity | Section |
|---|---|---|
| `site.up` | critical | [site-down](#site-down) |
| `api.5xx_rate` | critical | [api-5xx](#api-5xx) |
| `app.errors` | warn | [app-errors](#app-errors) |
| `worker.heartbeat` | critical | [worker-down](#worker-down) |
| `jobs.backlog` | critical | [queue-backlog](#queue-backlog) |
| `jobs.failures` | warn | [job-failures](#job-failures) |
| `issuer.health` | critical | [issuer-down](#issuer-down) |
| `wallet.balances` | critical | [wallet-balances](#wallet-balances) |
| `chain.sync` | warn | [chain-sync](#chain-sync) |
| `chain.blocks` | critical | [chain-halted](#chain-halted) |
| `bridge.health` | warn | [claude-bridge](#claude-bridge) |
| `ai.models` | critical | [ai-gateway](#ai-gateway) |
| `search.brave` | warn | [brave-quota](#brave-quota) |
| `db.postgres` | critical | [postgres](#postgres) |
| `disk.space` | critical | [disk-space](#disk-space) |
| `tls.expiry` | critical | [tls-expiry](#tls-expiry) |
| `automation.errors` | warn | [automation](#automation) |
| `email.delivery` | warn | [email-delivery](#email-delivery) |

---

<a id="site-down"></a>
## site-down

**Site down** — check `site.up`

**Detects:** GET of `https://eth.blockid.au/api/healthz`, `https://eth.blockid.au/`, `https://hr.blockid.au/`,
`https://scan.blockid.au/` (OPS_PROBE_URLS) fails or returns >= 400 in two consecutive rounds.

**Diagnose**
```bash
curl -sS -o /dev/null -w '%{http_code} %{time_total}s\n' https://eth.blockid.au/api/healthz
curl -sS http://127.0.0.1:8080/healthz                      # API directly (bypasses nginx + Cloudflare)
$DC ps agents-api && $DC logs --tail=200 agents-api
sudo tail -50 /var/log/nginx/eth.blockid.au.error.log        # "connect() failed (111)" = API down
sudo nginx -t
```
**Fix**
1. API down / restarting: read the startup error in the log, fix (usually env in `/opt/blockid/app.env`), then
   `$DC up -d --no-build agents-api`.
2. nginx: `sudo nginx -t && sudo systemctl reload nginx` (`sudo systemctl restart nginx` if it is not running).
3. Web root 404/500: `ls -la ~/blockid-eth-platform/web/dist/index.html`; rebuild with `scripts/build-web.sh`.
4. scan.blockid.au: `cd ~/blockid-eth-platform/deploy/blockscout && sudo docker compose --env-file
   /opt/blockid/blockscout.env ps`, then `... restart frontend backend`.
5. Only through Cloudflare fails (direct works): check the Cloudflare dashboard (DNS proxied, SSL mode Full strict)
   and the origin certificate ([tls-expiry](#tls-expiry)).

<a id="api-5xx"></a>
## api-5xx

**API 5xx rate** — check `api.5xx_rate`

**Detects:** share of `/api/` requests answered 5xx in the last 15 min of `/var/log/nginx/eth.blockid.au.access.log`
(warn >= 2 %, critical >= 10 %, at least 5 errors).

**Diagnose**
```bash
sudo awk '$9 >= 500' /var/log/nginx/eth.blockid.au.access.log | tail -30          # which routes
sudo awk '$9 >= 500 {print $9, $7}' /var/log/nginx/eth.blockid.au.access.log | sort | uniq -c | sort -rn | head
sudo tail -50 /var/log/nginx/eth.blockid.au.error.log                               # 502/504 cause
$DC logs --since=30m agents-api | grep '"level": "ERROR"' | tail -20
```
**Fix**
1. 502/504 only: the API is down or blocked — see [site-down](#site-down); a long request (valuation start) timing
   out = check [ai-gateway](#ai-gateway).
2. 500: open **Admin > Ops > Logs**, newest fingerprint, read the traceback; the `request_id` matches the access
   line (`X-Request-ID` header) in `$DC logs agents-api | grep <request_id>`.
3. 502 from approvals = issuer down ([issuer-down](#issuer-down)).
4. After a bad deploy: roll back (`git checkout <previous sha>`, rebuild + `up -d --no-build agents-api`), then
   `scripts/record-deploy.sh rollback`.

<a id="app-errors"></a>
## app-errors

**Application errors** — check `app.errors`

**Detects:** >= 20 ERROR log records (api + worker + issuer, OPS_ERRORS_WARN) within 15 min.

**Diagnose**
```bash
$DC logs --since=30m agents-api agents-worker issuer | grep '"level": "ERROR"' | tail -40
```
Admin > Ops > Logs: sort by count; `source` tells which container.

**Fix** — depends on the error: config (missing env → edit `/opt/blockid/app.env`, recreate the container),
upstream outage (LLM / RPC: wait or pause the model in Admin > AI health), bug (fix + deploy). Restart a wedged
container with `$DC restart <service>`.

<a id="worker-down"></a>
## worker-down

**Worker down** — check `worker.heartbeat`

**Detects:** the worker writes a heartbeat every 30 s (`studio.ops_checks_state` row `_hb:worker`); older than
5 min (OPS_WORKER_STALE_SECONDS) = critical. "No heartbeat recorded yet" means the worker runs an image without ops.

**Diagnose**
```bash
$DC ps agents-worker
$DC logs --tail=200 agents-worker
sudo docker stats --no-stream blockid-app-agents-worker-1
```
**Fix**
1. `$DC restart agents-worker` (or `$DC up -d --no-build agents-worker` if it exited).
2. Crash loop at startup: usually Postgres unreachable or bad env; fix and restart.
3. Out of memory: `dmesg | tail`; lower concurrency (`AI_CONCURRENCY_*`) and restart.

<a id="queue-backlog"></a>
## queue-backlog

**Queue backlog** — check `jobs.backlog`

**Detects:** oldest `queued` valuation / HR run waiting > 15 min (warn) or > 60 min (critical).

**Diagnose**
```bash
sudo docker exec blockid-app-postgres-1 psql -U blockid -c "SELECT status, count(*), min(updated_at) FROM studio.valuations GROUP BY 1"
sudo docker exec blockid-app-postgres-1 psql -U blockid -c "SELECT status, count(*), min(updated_at) FROM studio.hr_teams GROUP BY 1"
$DC logs --since=1h agents-worker | tail -50
```
**Fix**
1. Worker dead → [worker-down](#worker-down).
2. A `running` row that never finishes blocks the worker: restart the worker; HR runs are re-queued by the HR
   watchdog, valuations can be retried by the user.
3. All LLMs skipped → [ai-gateway](#ai-gateway).
4. Real load: raise `VALUATIONS_MAX_ACTIVE` / `HR_MAX_ACTIVE` cautiously (quota!), recreate the worker.

<a id="job-failures"></a>
## job-failures

**Valuation / HR failures** — check `jobs.failures`

**Detects:** >= 3 failed valuations or HR runs in the last hour; any valuation `running` without progress for 30 min;
any HR run without heartbeat for 20 min.

**Diagnose**
```bash
sudo docker exec blockid-app-postgres-1 psql -U blockid -c "SELECT id, url, left(error,200), updated_at FROM studio.valuations WHERE status='failed' ORDER BY updated_at DESC LIMIT 10"
sudo docker exec blockid-app-postgres-1 psql -U blockid -c "SELECT id, name, error_code, left(error_detail,200) FROM studio.hr_teams WHERE status='failed' ORDER BY updated_at DESC LIMIT 10"
$DC logs --since=2h agents-worker | grep -i -E 'error|failed' | tail -40
```
**Fix** — common causes: every model skipped / circuit open ([ai-gateway](#ai-gateway)), Brave quota
([brave-quota](#brave-quota)), target site unreachable (user error, nothing to do). Stalled rows: `$DC restart
agents-worker`.

<a id="issuer-down"></a>
## issuer-down

**Issuer down** — check `issuer.health`

**Detects:** the API cannot get `GET /health` from the issuer (two rounds), or its job queue has > 20 pending jobs.

**Diagnose**
```bash
$DC ps issuer
$DC logs --tail=200 issuer
ls -la /opt/blockid/keys                                     # uid 10001, read-only
```
**Fix**
1. `$DC up -d --no-build issuer`.
2. Keystore/password errors at startup: check `/opt/blockid/keys` ownership (10001) and `/opt/blockid/issuer.env`.
3. Backlog: jobs run one at a time; a slow external RPC (Hoodi / HSK) makes it grow — check `HOODI_RPC_URL` /
   `HSK_RPC_URL`; it drains by itself once the RPC answers.
4. Then re-run failed approvals (Admin > Companies > Re-sync).

<a id="wallet-balances"></a>
## wallet-balances

**Issuer gas balances** — check `wallet.balances`

**Detects:** issuer wallet `0x2567…5ddf` balances from the issuer health: HSK < 0.02 (warn) / < 0.005 (critical),
Hoodi ETH < 0.05 / < 0.01, BLKD < 10 / < 1 (OPS_*_WARN / OPS_*_CRIT). "Days left" = balance / average daily burn
over the last week (shown in the weekly report).

**Diagnose** — Admin > Wallets, or:
```bash
cast balance 0x2567…5ddf --rpc-url "$HOODI_RPC_URL" --ether
cast balance 0x2567…5ddf --rpc-url "$HSK_RPC_URL" --ether
cast balance 0x2567…5ddf --rpc-url http://127.0.0.1:8545 --ether
```
(full address: `ADMIN_WALLETS` / Admin > Wallets; RPC URLs in `/opt/blockid/app.env`).

**Fix**
1. Hoodi ETH: https://hoodi-faucet.pk910.de (PoW faucet) to the issuer address; ~0.004 ETH per company.
2. HSK: HashKey Chain testnet faucet (https://faucet.hsk.xyz) to the issuer address.
3. BLKD (BlockID Chain): from the validator key inside `evmd`:
   ```bash
   sudo docker exec -it blockid-app-evmd-1 evmd debug addr 0x2567…5ddf          # -> bech32
   sudo docker exec -it blockid-app-evmd-1 evmd tx bank send validator <bech32> 100000000000000000000ablkd \
     --keyring-backend file --home /root/.evmd --chain-id blockid_262626-1 --gas-prices 10000000000ablkd -y
   ```
   (keyring password = `EVMD_KEYRING_PASSWORD`).
4. Re-sync companies left `partially_anchored` (Admin > Companies > Re-sync).

<a id="chain-sync"></a>
## chain-sync

**Chain sync** — check `chain.sync`

**Detects:** companies in `failed` / `partially_anchored`, or stuck in `issuing` / `anchoring` for 30+ min
(issue on BlockID Chain, then mirror + anchor on Hoodi and HashKey; see `issuer/syncstate.py`).

**Diagnose**
```bash
sudo docker exec blockid-app-postgres-1 psql -U blockid -c "SELECT ticker, status, left(error,200), sync->'errors' FROM studio.companies WHERE status IN ('failed','partially_anchored','issuing','anchoring')"
$DC logs --since=2h issuer | grep -i -E 'revert|error|insufficient'
```
**Fix**
1. `insufficient funds` → [wallet-balances](#wallet-balances), then **Re-sync** (approve-anchor) re-runs only the
   failed chain.
2. BlockID revert → status `failed`: retry = approve-issue again (Admin > Companies).
3. Stuck `issuing`/`anchoring`: issuer restarted mid-job → `$DC restart issuer`, then Re-sync.
4. External RPC down (Hoodi / HSK): wait, then Re-sync; switch RPC in `/opt/blockid/app.env` if it stays down.

<a id="chain-halted"></a>
## chain-halted

**BlockID Chain halted** — check `chain.blocks`

**Detects:** `eth_blockNumber` on LOCAL_RPC_URL unchanged for 3 min, or the RPC fails (two rounds).

**Diagnose**
```bash
cast block-number --rpc-url http://127.0.0.1:8545; sleep 10; cast block-number --rpc-url http://127.0.0.1:8545
$DC ps evmd && $DC logs --tail=200 evmd
curl -s 127.0.0.1:26657/status | head -40
df -h /mnt/app-data
```
**Fix**
1. Disk full stops CometBFT → [disk-space](#disk-space).
2. `$DC restart evmd` (single validator, data in `/mnt/app-data/evmd`); blocks resume within seconds.
3. Consensus error / app hash mismatch in the log: do not wipe data; stop and escalate (snapshot of
   `/mnt/app-data` first).

<a id="claude-bridge"></a>
## claude-bridge

**Claude bridge** — check `bridge.health`

**Detects:** `GET $CLAUDE_SEARCH_URL/healthz` fails (two rounds), or the daily caps: >= 80 % info, >= 100 % warn
(search `today/max_per_day`, completions `complete_today/complete_max_per_day`).

**Diagnose**
```bash
curl -s http://172.18.0.1:8765/healthz
sudo systemctl status claude-search-bridge
sudo journalctl -u claude-search-bridge -n 100 --no-pager
```
**Fix**
1. `sudo systemctl restart claude-search-bridge`.
2. Cap reached: counters reset at midnight host time; raise `BRIDGE_MAX_PER_DAY` / `BRIDGE_COMPLETE_MAX_PER_DAY` in
   `/opt/blockid/search-bridge.env` only deliberately (Claude plan limits), then restart the service.
3. Claude CLI logged out on the host: log in again as the service user.

<a id="ai-gateway"></a>
## ai-gateway

**AI gateway models** — check `ai.models`

**Detects:** from the AI gateway health (same data as Admin > AI health): a model with circuit **open** or
**skipped** (quota >= 95 %) = warn; quota >= 80 % = info; no LLM model usable = critical; DeepInfra spend today
>= 80 % of `DEEPINFRA_DAILY_BUDGET_USD` info, >= 100 % warn.

**Diagnose** — Admin > AI health (`last_error`, windows, recent fallbacks), and
```bash
$DC logs --since=1h agents-worker | grep -i -E 'sambanova|deepinfra|bridge|rate|429|timeout' | tail -40
```
**Fix**
1. Circuit open: provider outage or bad key — check the provider status page / key; the circuit half-opens by itself.
2. Skipped (quota): wait for the reset shown in Admin, or pause it and rely on the others; add models via
   `SAMBANOVA_MODELS` / `DEEPINFRA_MODELS` in `/opt/blockid/app.env`, then
   `$DC up -d --no-build --force-recreate agents-worker agents-api`.
3. All down: valuations/HR fail until one recovers; tell users via the status message if long.
4. DeepInfra budget: raise `DEEPINFRA_DAILY_BUDGET_USD` only deliberately; it resets at 00:00 UTC.

<a id="brave-quota"></a>
## brave-quota

**Brave quota** — check `search.brave`

**Detects:** Brave search month window >= 80 % of `BRAVE_MONTHLY_QUOTA` (default 2000).

**Fix** — check the real usage at api.search.brave.com; upgrade the plan or accept degraded search (research falls
back to the Claude bridge, then to no search with a "Search unavailable" warning) until the month resets.

<a id="postgres"></a>
## postgres

**Postgres** — check `db.postgres`

**Detects:** `SELECT pg_database_size(...)` fails (critical) or the database is larger than OPS_DB_SIZE_WARN_GB (20).
If Postgres is unreachable the monitor cannot store anything: it emails directly (max once an hour, SMTP needed).

**Diagnose**
```bash
$DC ps postgres && $DC logs --tail=100 postgres
df -h /mnt/app-data
sudo docker exec blockid-app-postgres-1 psql -U blockid -c "SELECT relname, pg_size_pretty(pg_total_relation_size(relid)) FROM pg_statio_user_tables ORDER BY pg_total_relation_size(relid) DESC LIMIT 10"
```
**Fix**
1. Down: `$DC restart postgres`, then `$DC restart agents-api agents-worker issuer`.
2. Disk full → [disk-space](#disk-space) first.
3. Too big: largest tables are usually `studio.ai_usage`, `studio.ai_cache`, langgraph checkpoints — prune old rows
   (e.g. `DELETE FROM studio.ai_cache WHERE at < now() - interval '7 days'`), then `VACUUM`.

<a id="disk-space"></a>
## disk-space

**Disk space** — check `disk.space`

**Detects:** `shutil.disk_usage` on `/data` (= `/mnt/app-data/agents`), the nginx log mount and `/`
(OPS_DISK_PATHS): warn >= 80 %, critical >= 90 %.

**Diagnose**
```bash
df -h / /mnt/app-data
sudo du -xh --max-depth=2 /mnt/app-data | sort -h | tail -15
sudo docker system df
```
**Fix**
1. `sudo docker image prune -f && sudo docker builder prune -f` (never `docker volume prune`).
2. `sudo journalctl --vacuum-time=7d`; container logs are capped (20 MB x 10); nginx logs rotate daily (14 days).
3. Old web assets: `scripts/build-web.sh` prunes hashed assets older than KEEP_DAYS.
4. Still short: grow the disk in GCP, then `sudo growpart` / `sudo resize2fs`.

<a id="tls-expiry"></a>
## tls-expiry

**TLS certificates** — check `tls.expiry`

**Detects:** hourly TLS handshake to eth / hr / scan: the Cloudflare **edge** certificate (public DNS) and, with
OPS_TLS_ORIGIN (compose: `host.docker.internal`), the **origin** certificate served by host nginx (certbot).
Warn < 14 days, critical < 3 days or an invalid / expired certificate.

**Diagnose**
```bash
sudo certbot certificates
for h in eth.blockid.au hr.blockid.au scan.blockid.au; do
  echo | openssl s_client -connect 127.0.0.1:443 -servername $h 2>/dev/null | openssl x509 -noout -enddate; done
systemctl list-timers | grep certbot
```
**Fix**
1. Origin: `sudo certbot renew` then `sudo systemctl reload nginx`; if renewal fails, read
   `/var/log/letsencrypt/letsencrypt.log` (HTTP-01 challenge must reach nginx on :80).
2. Edge: Cloudflare renews automatically; check SSL/TLS > Edge Certificates in the Cloudflare dashboard.

<a id="automation"></a>
## automation

**Dividend / offering automation** — check `automation.errors`

**Detects:** errors logged by `studio/dividend_policy.py` or `studio/offerings.py` in the last 30 min, offerings in
status `failed`, dividends `failed` or `paying` for more than 2 h.

**Diagnose**
```bash
$DC logs --since=1h agents-api | grep -E 'dividend|offering' | tail -40
sudo docker exec blockid-app-postgres-1 psql -U blockid -c "SELECT id, company_id, status, left(error,200) FROM studio.offerings WHERE status='failed'"
sudo docker exec blockid-app-postgres-1 psql -U blockid -c "SELECT id, company_id, status, created_at FROM studio.dividends WHERE status IN ('failed','paying')"
```
**Fix**
1. Issuer down or out of gas is the usual cause → [issuer-down](#issuer-down), [wallet-balances](#wallet-balances).
2. Failed offering: Admin > Offerings > retry settlement (or reject/refund).
3. Dividend stuck `paying`: check `$DC logs issuer | grep -i dividend`; the issuer finishes or marks it failed.
4. `DIVIDEND_AUTOMATION_SECONDS=0` / `OFFERING_AUTOMATION_SECONDS=0` stop the loops while you investigate.

<a id="email-delivery"></a>
## email-delivery

**Email delivery** — check `email.delivery`

**Detects:** with SMTP configured, the last 2–3 sends (ops or welcome mail) in 2 h all failed. Without SMTP the
check is `unknown` and every incident / report shows "not emailed — SMTP not configured".

**Fix**
1. Admin > Ops > **Send test email** (or `POST /api/v1/admin/ops/test-email`); the reason says what failed.
2. App Password: `SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_USER=admin@blockid.au SMTP_PASSWORD=<App Password>`.
3. Workspace SMTP relay: `SMTP_HOST=smtp-relay.gmail.com`, VM IP 34.151.170.203 (ephemeral, see "Public IP changes") allow-listed, no user/password.
4. Edit `/opt/blockid/app.env`, then `$DC up -d --no-build --force-recreate agents-api`; stored incidents and the
   latest report (< 8 days) are sent on the next round.
