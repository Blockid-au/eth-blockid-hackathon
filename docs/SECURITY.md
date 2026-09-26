# Security & legal

## Security model

| Risk | Mitigation in the framework |
|---|---|
| Agent self-signing/transferring assets | No keys in the agent runtime. Sign/send/deploy/key/shell tools are forbidden for every agent in `policy.py`. Only the isolated issuer signs, and only for admin-approved rows (one issuance approval; mints and dividends each need their own). The legacy data-room agents only produce **unsigned** Safe batches |
| Prompt injection from documents/web | Content is always wrapped in `<data>` and marked as untrusted. Permissions are enforced by code, not by the prompt. Output must pass a Pydantic schema. Research automatically discards claims citing URLs that don't actually exist |
| PII leaving the server | The live valuation reads only public websites; emails/phone numbers are stripped before any model call and search queries are sanitised. Agents that handle PII (legacy data-room intake/registry) are restricted to the `local` tier in code and never fall back to cloud. Shareholder PII never goes on-chain (KYC is a hash) |
| AI fabricating numbers | SVI index and valuation range are computed by code (`tools/svi.py`). The LLM only proposes 5 qualitative scores, which an admin approves or overrides; uncited findings are dropped. The anchored report hash (keccak256 of the canonical report JSON) lets anyone check at `/verify` that the approved report was not changed |
| Faulty contracts | Fixed contract templates (no agent writes Solidity), 37 Foundry tests incl. fuzz, Slither in CI. The legacy contract gate hard-rejects if tests, dry-run or Slither fail. Contracts are unaudited (testnet) |
| History tampering | Hash-chained audit log (`verify-audit`). The head hash should be anchored on-chain daily |
| Server compromise | Only the `issuer` container holds keys (encrypted keystores, read-only mount) on internal networks the worker cannot reach; secrets in root-only env files under `/opt/blockid`. The issuer key is still a hot key — see the checklist below. (The earlier two-VM design also kept the GPU VM without a public IP, SSH via IAP, secrets in Secret Manager.) |
| Data loss | Postgres/evmd data on the attached SSD (`/mnt/app-data`) with daily disk snapshots |

## Mandatory work before onboarding real customers

1. **Contract:**
   - Replace `IdentityRegistry` and compliance logic with the official **ERC-3643 (T-REX) + ONCHAINID** stack. The current token keeps the same `isVerified()` interface to make migration easy.
   - Commission an **independent audit**.
   - Move admin roles to a Safe multisig (threshold at least 2-of-3) and narrow the issuer key to `ISSUER_ROLE` / `RECORDER_ROLE` (roadmap item 1).
2. **Chain:**
   - Run at least **4 independent validators**. A single node is only good enough for a demo.
   - Pin the `cosmos/evm` version.
   - Review the genesis file.
   - Do not expose port `26657` publicly unless an explorer requires it.
3. **Legal (Australia)** *(not legal advice)*:
   - ASIC treats tokenised securities as a financial product.
   - The Digital Assets Framework Act 2026 takes effect on **9 April 2027**, requiring an AFSL license for digital asset platforms and tokenised custody platforms.
   - Custody, transfer agent, and dividend distribution services that charge fees need review by a fintech lawyer.
   - AML/CTF obligations with AUSTRAC may apply in parallel.
4. **Personal data:**
   - The Privacy Act 1988 (APP 8) applies when data is processed overseas: the cloud LLM providers (SambaNova, Anthropic, DeepInfra) only receive public website text today.
   - If KYC records or data rooms must remain in Australia, run the PII agents on the `local` tier on an Australian machine.
5. **Operations:**
   - Pin image tags.
   - Add on-chain alerting and tracing (roadmap item 5).
   - Rehearse recovery from snapshot.

## Live single-host deployment controls (2026-09)

Controls added after the internal security review (all verified on the live site):

| Area | Control |
|---|---|
| Keys | Only the `issuer` container holds keys (`/opt/blockid/keys`, read-only, uid 10001). It is on internal networks `issuer` (agents-api only) and `issuer-backend` (postgres, evmd) plus an egress-only network; `agents-worker`, which processes untrusted websites, cannot reach it and does not receive `ISSUER_INTERNAL_TOKEN` (`/opt/blockid/issuer.env`). |
| Approvals | One issuance approval (`approve-issue`) runs BlockID → Hoodi → HashKey; `approve-anchor` only re-syncs missing/failed chains. Issuance and mint/dividend execution are claimed atomically from admin-approved states; retries check on-chain results first. |
| Auth | SIWE (EIP-4361, single-use nonces, domain/URI/chain checks; admin = wallet in `ADMIN_WALLETS`: `0xc309…4585`, `0xC400…a21F`, `0x02B1…1E2F`) or the admin account (bcrypt password, lockout keyed by real client IP via Cloudflare `CF-Connecting-IP`). Cookie `__Host-bid_session` (HttpOnly, Secure, SameSite=Lax). |
| CSRF | Origin/Referer allowlist (`ALLOWED_ORIGINS`) on every state-changing request. |
| SSRF | All crawling goes through `tools/safefetch.py`: public addresses only, redirects re-checked per hop, DNS pinned to the validated IP, 2 MB and 20 s per page, 120 s per crawl, robots.txt respected. |
| Abuse | Valuations: 3/wallet/day, 60/day globally, max 5 active. |
| Public RPC | `/rpc` goes through `POST /v1/rpc` (eth_/net_/web3_ only). `/cometbft/` only exposes read routes. |
| Web | CSP (self + hashed inline bootstrap, Google Fonts, Hoodi RPC), X-Frame-Options DENY, HSTS, nosniff; API docs disabled in production. |

Known testnet-only choices: admin login is a SIWE wallet in `ADMIN_WALLETS` or a username/password configured via
`ADMIN_PASSWORD_HASH` (bcrypt; rotate before any real use); the issuer key is a hot key on the server (production must move issuance to a Safe multisig — see above).
