# Security & legal

## Security model

| Risk | Mitigation in the framework |
|---|---|
| Agent self-signing/transferring assets | No keys in the runtime. Registry/Dividend only create **unsigned** Safe batches. Sign/send/deploy tools are forbidden in `policy.py` |
| Prompt injection from documents/web | Content is always wrapped in `<data>` and marked as untrusted. Permissions are enforced by code, not by the prompt. Output must pass a Pydantic schema. Research automatically discards claims citing URLs that don't actually exist |
| PII leaving the server | Agents that handle PII are restricted to the `local` tier (enforced by code). The gateway never falls back to cloud. Founder names are anonymized before valuation calls the model. Brave queries are filtered to strip email/phone numbers |
| AI fabricating numbers | SVI scores and valuation are computed by code (deterministic, hashed). The LLM only proposes qualitative scores, which must go through an approver |
| Faulty contracts | Fixed templates + 20 tests/fuzzing + dry-run + Slither. Gate 2 hard-rejects on any failure. Deployment is run by a human using their own keystore |
| History tampering | Hash-chained audit log (`verify-audit`). The head hash should be anchored on-chain daily |
| Server compromise | The AI VM has no public IP and only exposes port :4000 to the app VM. SSH only via IAP. Secrets live in Secret Manager. Service account has minimal privileges (the app can only *start* the AI VM) |
| Data loss | Daily snapshots of the data disk, retained for 14 days. Postgres/evmd live on a separate disk |

## Mandatory work before onboarding real customers

1. **Contract:**
   - Replace `IdentityRegistry` and compliance logic with the official **ERC-3643 (T-REX) + ONCHAINID** stack. The current token keeps the same `isVerified()` interface to make migration easy.
   - Commission an **independent audit**.
   - Set the Safe threshold to at least 2/3.
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
   - The Privacy Act 1988 (APP 8) applies when data is processed overseas, and the AI VM is located in Singapore.
   - If KYC records must remain entirely within Australia, run intake on an AI machine located in Australia (a T4 in Sydney, or an Australian GPU provider).
5. **Operations:**
   - Pin image tags (`vllm`, `litellm`).
   - Enable Cloud Monitoring alerts.
   - Rehearse recovery from snapshot.

## Issuance Studio (single-host deployment, 2026-09)

Controls added after the internal security review (all verified on the live site):

| Area | Control |
|---|---|
| Keys | Only the `issuer` container holds keys (`/opt/blockid/keys`, read-only, uid 10001). It is on internal networks `issuer` (agents-api only) and `issuer-backend` (postgres, evmd) plus an egress-only network; `agents-worker`, which processes untrusted websites, cannot reach it and does not receive `ISSUER_INTERNAL_TOKEN` (`/opt/blockid/issuer.env`). |
| Approvals | Company issue/anchor and mint/dividend execution are claimed atomically from admin-approved states; retries check on-chain results first. |
| Auth | SIWE (EIP-4361, single-use nonces, domain/URI/chain checks) or admin password (bcrypt, lockout keyed by real client IP via Cloudflare `CF-Connecting-IP`). Cookie `__Host-bid_session` (HttpOnly, Secure, SameSite=Lax). |
| CSRF | Origin/Referer allowlist (`ALLOWED_ORIGINS`) on every state-changing request. |
| SSRF | All crawling goes through `tools/safefetch.py`: public addresses only, redirects re-checked per hop, DNS pinned to the validated IP, 2 MB and 20 s per page, 120 s per crawl, robots.txt respected. |
| Abuse | Valuations: 3/wallet/day, 60/day globally, max 5 active. |
| Public RPC | `/rpc` goes through `POST /v1/rpc` (eth_/net_/web3_ only). `/cometbft/` only exposes read routes. |
| Web | CSP (self + hashed inline bootstrap, Google Fonts, Hoodi RPC), X-Frame-Options DENY, HSTS, nosniff; API docs disabled in production. |

Known testnet-only choices: admin login is a SIWE wallet in `ADMIN_WALLETS` or a username/password configured via
`ADMIN_PASSWORD_HASH` (bcrypt; rotate before any real use); the issuer key is a hot key on the server (production must move issuance to a Safe multisig — see above).
