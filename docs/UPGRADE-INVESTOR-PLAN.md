# BlockID Business Passport — investor-first upgrade plan

Prepared 27 Sep 2026 against `/home/dovanlong/blockid-eth-platform` @ `c8e7049` (read-only review) and the live
testnet app https://eth.blockid.au. Effort: **S** ≤ 3 days · **M** 1–3 weeks · **L** > 3 weeks (one full-stack dev + Claude).
Sources are in §6; items marked *[verify]* could not be fully confirmed. Not legal advice.

Non-negotiables carried over from the current design (`docs/SECURITY.md`, `docs/IMPLEMENTATION.md` "Ground rules"):
1. **AI agents never hold keys** (`policy.py` forbids sign/send/deploy); the **issuer container is the only server-side
   key holder** and acts only on admin-approved DB rows.
2. **A human approves** every state change that affects ownership, money or published investor information.
3. **Testnet only. Not an offer of securities.** — shown on every page, including every new investor screen.
4. EN default, VI on flag click; `lib/flow.ts` stays the single source of truth for navigation.

---

## 1. New messaging (EN + VI)

> Copy note: `docs/FACTS.md` "Terms to avoid" currently bans "investment / returns / offer" in marketing copy. The
> new hero deliberately uses "invest". Keep it, but (a) always pair it with the legal line, (b) never say "returns",
> "yield", "guaranteed", "earn", and (c) describe the *information and rights* we give, not the performance of shares.
> Update the FACTS.md table: allow "invest/investor" in the hero and investor portal; keep "returns/offer" banned
> except "simulated offering (testnet)".

### 1.1 Hero line (H1)

| | EN | VI |
|---|---|---|
| **H1** | **Know the business before you invest.** | **Hiểu rõ doanh nghiệp trước khi bạn đầu tư.** |
| Eyebrow | BlockID Business Passport · Testnet demo | BlockID Business Passport · Bản demo testnet |
| Sub-headline | Every business gets a passport: valued by AI, approved by people, proven on-chain — and kept up to date for every shareholder. | Mỗi doanh nghiệp có một tấm hộ chiếu: AI định giá, con người phê duyệt, blockchain chứng minh — và luôn được cập nhật cho mọi cổ đông. |
| Tagline (unchanged) | Agents propose. Humans approve. Chains prove. | Agent đề xuất. Con người phê duyệt. Blockchain chứng minh. |

Split for the existing two-part H1 (`hero.h1a` / `hero.h1b`, `<em>` on the second part):
EN `"Know the business"` + `"before you invest."` · VI `"Hiểu rõ doanh nghiệp"` + `"trước khi bạn đầu tư."`

### 1.2 Elevator pitch

- **EN (≤ 40 words):** BlockID Business Passport gives every shareholder, large or small, a live view of the business
  they own: AI-analysed, human-approved updates and valuations, an on-chain share register as proof of ownership, and
  dividends paid straight to their wallet.
- **VI:** BlockID Business Passport cho mọi cổ đông, dù lớn hay nhỏ, một góc nhìn trực tiếp vào doanh nghiệp họ sở
  hữu: bản cập nhật và định giá do AI phân tích, con người phê duyệt, sổ cổ đông trên blockchain làm bằng chứng sở hữu,
  và cổ tức được trả thẳng vào ví.

Founder-side one-liner (for the `/start` page and decks):
- EN: Turn your website and your numbers into an investor-ready passport — valuation, share register, updates and
  dividends in one place.
- VI: Biến website và số liệu của bạn thành một tấm hộ chiếu sẵn sàng cho nhà đầu tư — định giá, sổ cổ đông, bản cập
  nhật và cổ tức ở cùng một nơi.

### 1.3 Value pillars (5)

| # | EN title — line | VI |
|---|---|---|
| 1 | **Understand it.** AI agents read the business, cite every source and score it on a transparent 7-dimension index; a person signs off. | **Hiểu rõ.** AI đọc hiểu doanh nghiệp, dẫn nguồn mọi con số và chấm điểm theo chỉ số 7 tiêu chí minh bạch; con người ký duyệt. |
| 2 | **Follow it.** Weekly pulses, monthly and quarterly updates and an annual review — every one approved and hash-anchored on-chain, so nobody can quietly rewrite it. | **Theo dõi.** Bản tin hàng tuần, cập nhật hàng tháng, hàng quý và báo cáo năm — mỗi bản đều được phê duyệt và neo mã băm trên blockchain, không ai có thể âm thầm sửa lại. |
| 3 | **Own it.** An online share register on BlockID Chain, mirrored to Ethereum and HashKey with Merkle proofs. Your wallet balance *is* your proof of ownership. | **Sở hữu.** Sổ cổ đông trực tuyến trên BlockID Chain, sao chép sang Ethereum và HashKey kèm bằng chứng Merkle. Số dư trong ví chính là bằng chứng sở hữu của bạn. |
| 4 | **Get paid.** Dividends go straight to every shareholder's wallet the moment a round is approved — no forms, no gas, no minimum holding. | **Nhận cổ tức.** Cổ tức chuyển thẳng vào ví mọi cổ đông ngay khi đợt chia được duyệt — không giấy tờ, không phí gas, không yêu cầu tỷ lệ sở hữu tối thiểu. |
| 5 | **Trust it.** AI never holds keys; you hold yours. See who can sign what, on which chain, and verify any number yourself. | **Tin cậy.** AI không bao giờ giữ khoá; bạn giữ khoá của mình. Xem ai được ký gì, trên chuỗi nào, và tự kiểm chứng mọi con số. |

### 1.4 Shareholder rights and benefits — by investor size

| For | EN | VI |
|---|---|---|
| **Every shareholder** | Same information, same time: every approved update and valuation reaches all holders at once. | Cùng thông tin, cùng lúc: mọi bản cập nhật và định giá đã duyệt đến tay tất cả cổ đông cùng một thời điểm. |
| | Proof of ownership you can check without asking anyone (wallet balance + Merkle proof on 3 chains). | Bằng chứng sở hữu tự kiểm tra được, không cần hỏi ai (số dư ví + bằng chứng Merkle trên 3 chuỗi). |
| | Pro-rata dividends straight to your wallet, gas paid by the platform. | Cổ tức theo tỷ lệ chuyển thẳng vào ví, phí gas do nền tảng trả. |
| | Your stake in detail: shares, %, value at the latest approved mark, cost basis, dilution history, dividends received. | Chi tiết phần sở hữu: số cổ phần, tỷ lệ %, giá trị theo định giá đã duyệt mới nhất, giá vốn, lịch sử pha loãng, cổ tức đã nhận. |
| | Notice before dilution: every new issue is previewed (before/after %) and published before it is minted. | Được báo trước khi bị pha loãng: mọi đợt phát hành mới đều hiển thị trước (tỷ lệ trước/sau) và công bố trước khi đúc. |
| | Lost your key? The register can restore your shares to a new wallet after identity re-check and admin approval. | Mất khoá? Sổ cổ đông có thể khôi phục cổ phần sang ví mới sau khi xác minh lại danh tính và được admin phê duyệt. |
| **Small / retail** | No minimum stake to receive updates, dividends or proofs; email sign-in with a wallet created on your own device — no MetaMask or seed phrase needed to start. | Không cần tỷ lệ tối thiểu để nhận cập nhật, cổ tức hay bằng chứng; đăng nhập bằng email với ví tạo ngay trên thiết bị của bạn — không cần MetaMask hay cụm từ khôi phục để bắt đầu. |
| | Plain-language AI summary of each update, with links to the source numbers. | Tóm tắt bằng ngôn ngữ dễ hiểu cho mỗi bản cập nhật, kèm liên kết đến số liệu gốc. |
| **Large / professional** | KPI time series and CSV export, full evidence list, valuation method and overrides, per-chain anchors and tx hashes. | Chuỗi KPI theo thời gian và xuất CSV, toàn bộ danh sách bằng chứng, phương pháp định giá và các điều chỉnh, neo và mã giao dịch trên từng chuỗi. |
| | Bring your own wallet (MetaMask, hardware wallet, later Safe multisig) for custody you control. | Dùng ví của riêng bạn (MetaMask, ví cứng, sau này Safe multisig) để tự kiểm soát lưu ký. |
| | Q&A thread on each update (founder answers are part of the anchored record). | Mục hỏi đáp cho mỗi bản cập nhật (câu trả lời của nhà sáng lập là một phần hồ sơ được neo). |

### 1.5 Three alternative heroes

| # | EN | VI |
|---|---|---|
| A | See inside the business you own. | Nhìn rõ bên trong doanh nghiệp bạn sở hữu. |
| B | Your shares, your proof, your dividends — updated every month. | Cổ phần của bạn, bằng chứng của bạn, cổ tức của bạn — cập nhật mỗi tháng. |
| C | Invest in what you can verify. | Đầu tư vào điều bạn kiểm chứng được. |

Recommendation: ship the main H1; use **A** as the investor-portal header and **C** in decks (pair with the legal line).

---

## 2. Gap analysis vs the current code

| Capability the owner wants | What exists today (file / route) | Gap |
|---|---|---|
| Brand "Business Passport", investor-first hero | Brand strings in `web/app/index.html` (title/meta/noscript), `web/app/src/dict.proto.ts` (`hero.eyebrow/h1a/h1b/pitch`, EN l.11–14, VI l.303–306), `web/app/src/dict.ts` (`hero.sub/tag` l.472, l.1130), `web/app/src/wallet.ts:137` (SIWE statement), `lib/hooks.ts` (title), `docs/FACTS.md` + 20 docs/decks | Copy only; founder-centric. SIWE statement is free text (backend `studio/auth.py` parses but does not check it) → safe to change. |
| Investor portal ("My holdings") | `GET /v1/me/companies` (`studio/company_admins.py`) lists companies a wallet *administers*; cap table per company via `GET /v1/companies/{tk}` (balances read from chain); `studio.marks` history; `DividendDistributor` `Claimed` events | No route listing companies a wallet *holds*; no per-holder position, cost basis, dilution history, dividends received; no investor nav area. Everything is company-centric (`/c/:tk/*`). |
| Email login + device key | Auth = SIWE (`studio/auth.py`, `SIWE_CHAINS={262626,560048}`) or admin username/password; `studio.sessions(address, username, role)` | No email field anywhere, no OTP/magic link, no transactional email, no embedded wallet, no recovery. |
| Periodic AI updates | One-shot `site_valuation` graph (`graph.py`, `agents/research.py`, `agents/valuation.py`, `tools/svi.py`); founder `self_reported` metrics on the valuation; admin `revalue` (`POST /v1/admin/companies/{cid}/revalue`) + re-anchor | No KPI time series, no scheduled jobs, no update/report entity, no publish step, no notifications, no Xero/Stripe connectors. Revaluation is a manual number, not an agent proposal. |
| Hash-anchored disclosures | `valuationReportHash()` on each token (`anchorValuation`), `/verify/:ticker` (`studio/verify.py`, `pages/Verify.tsx`), `AgentProvenance` on HSK only, `setLegalDocHash` on the token | No per-update anchor; AgentProvenance not wired into the studio flow; no disclosure log readable per period. |
| Position analytics | `lib/math.ts`, `components/MarkPanel.tsx` (mark chart, simulated GBM band), mint dilution preview in `Company.tsx` | Per-holder time series and P&L missing; no cost basis (issue price is always A$1.00; transfers carry no price). |
| Realtime dividends | `DividendDistributor.sol` (Merkle rounds, `claimFor`), issuer `_dividend` (`issuer/service.py:711`) creates round then relayer `claimFor` each holder → funds land in wallets right after approval | Already *push-in-effect* but: one tx per holder, manual trigger, no schedule/policy, no withholding/TFN fields, no holder receipts/notifications, mAUD only on BlockID Chain. |
| Token offering / listing | Mints (`POST /v1/companies/{tk}/mints` → admin approve), KYC requests + transfers (`studio/transfers.py`, modes `free`/`approval`), `maxShareholders` param on the token (issuer passes 500) | No offering entity, subscription, escrow/refund, disclosure bundle, caps, cooling-off. |
| Custody & transparency | Admin-only `GET /v1/admin/wallets`; public `/hsk`, `/verify`, `AddrCard` (QR, add-to-MetaMask); `CapTableAnchor.verify(ticker, holder, balance, proof)` on Hoodi/HSK | No public "who holds which role" page, no per-holder Merkle proof endpoint, audit hash head not published. |

---

## 3. Feature specs

Conventions: tables live in schema `studio` (append to `agents/src/blockid_agents/studio/schema.sql`, idempotent
`CREATE ... IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`). New routers follow the `CompanyAuthz` pattern in
`studio/company_admins.py`. New admin queues are added to `QUEUES` in `lib/flow.ts` (gate = true) and to
`GET /v1/admin/approvals`. Every new state-changing endpoint goes through the existing Origin/Referer CSRF check.

### 3a. Rebrand + investor-first navigation — effort S (copy) + M (portal)

**User story.** As an investor I land on the site, understand in 5 seconds that this is where I *see and prove* what I
own, sign in, and see all my holdings in one place.

**UX / routes.** New top nav: `Investors` (default for signed-in non-admins) · `Businesses` (founder flow, today's
`/start`) · `Companies` (market) · `Trust` (3g) · `Verify`. New area **Investor portal** under `/i`:

| Route | Screen |
|---|---|
| `/i` → redirect to `/i/holdings` | |
| `/i/holdings` | "My holdings": table per company — ticker, shares, %, value at mark, 30-day change, last update date, unread badge; totals row (total value, dividends received YTD) |
| `/i/h/:tk/position` | stake value over time (mark × shares), % over time |
| `/i/h/:tk/dilution` | dilution events (mint/offering): before/after %, new holder count, resolution ref, tx |
| `/i/h/:tk/dividends` | dividends received: round, amount mAUD, per-share, tx, withholding (when present) |
| `/i/h/:tk/updates` | updates feed for this company (3c) |
| `/i/h/:tk/rights` | shareholder rights card: what you are entitled to see/receive, register proof (3g), recovery |
| `/i/updates` | cross-company feed, newest first |
| `/i/dividends` | cross-company dividend ledger + CSV |
| `/i/offerings` | open simulated offerings (3f) |
| `/i/account` | email, wallets linked, device key backup status, notification prefs |

**flow.ts changes.** Add alongside `WS`:
```ts
export const INV = ["position", "dilution", "dividends", "updates", "rights"] as const;
export type InvSection = (typeof INV)[number];
export const invPath = (tk: string, seg: InvSection) => `/i/h/${tk}/${seg}`;
export const INV_TOP = ["holdings", "updates", "dividends", "offerings", "account"] as const;
```
and add to `WS` (company workspace, founder/admin side): `"updates"`, `"kpis"`, `"offering"`, `"investors"`, in that
order after `overview`. Rename the founder phases' rail heading from "Founder" to "Business". New page component
`pages/Investor.tsx` reusing `SideLayout`, `RailGroup`, `RailItem`, `Pager` from `components/Shell.tsx`.
Routes in `App.tsx`: `<Route path="/i/:a?/:tk?/:section?" element={<InvestorPage/>}/>` (lazy).
Home page: hero switches to investor copy; primary CTA "See a live business passport" → `/i/demo` (read-only demo
portfolio holding EBA/ARW), secondary CTA "List your business" → `/start`.

**Data model.** No new tables for Phase 0 (portfolio derived on the fly). Phase 1 adds the `holdings_ledger` (3d).

**API.**
- `GET /v1/me/holdings` (user) → `[{ticker,name,shares,pct,mark_aud,value_aud,change_30d,last_update_at,unread}]`.
  Phase 0 implementation: for each issued company, `balanceOf(session.address)` on the BlockID token (batched
  `eth_call` / multicall; cache 30 s) — the chain is the register, so no DB drift. Also include linked wallets (3b).
- `GET /v1/demo/holdings` (public) → fixed demo wallet so the landing CTA works without login.

**Contracts / agents.** None. **Gate.** None (read-only). **Anchoring.** None new.
**Dependencies.** None for Phase 0; 3b for email users.

### 3b. Email login + device-generated key (non-custodial) — effort M

**Recommendation.** Self-hosted, vendor-free **"device wallet"**:
email OTP proves the *email*; a secp256k1 key generated *in the browser* proves the *wallet* via standard SIWE. The
server never sees the private key or anything that can decrypt it.

Why not the alternatives (details and sources in §6):
- **ERC-4337 passkey smart accounts** (P-256 + EIP-7951/RIP-7212): elegant, but needs a bundler + paymaster per chain.
  HashKey testnet has EntryPoint v0.6/v0.7 deployed and the P-256 precompile at `0x100` answers, but **no hosted
  bundler** (Pimlico: "chain not supported"), so we would run Alto/Rundler/Skandha ourselves on HSK *and* BlockID Chain,
  and every `isVerified(wallet)` KYC check must register a smart-account address per chain — adds weeks. Revisit on Hoodi with EIP-7702
  later (the same EOA can gain smart-account features without changing address).
- **Privy / Dynamic / Web3Auth / Turnkey / Magic**: fastest to ship and good recovery UX, but vendor lock-in, a
  third-party dependency in the login path, per-MAU pricing, custom-chain (262626) support to verify, and a harder
  "non-custodial" story to audit. Keep as a Phase-3 option if we need cross-device sync at scale.
- **Plain key in `localStorage`**: rejected — any XSS exfiltrates it.

**Key lifecycle (client, new module `web/app/src/devicewallet.ts`).**
1. `pk = generatePrivateKey()` (viem; uses `crypto.getRandomValues`) → `account = privateKeyToAccount(pk)`.
2. Derive a **wrapping key** (AES-256-GCM `CryptoKey`, `extractable:false`):
   - preferred: **passkey with the WebAuthn PRF extension** → HKDF(prf output, "blockid-devicewallet-v1");
   - fallback: user passphrase → Argon2id (`hash-wasm`, m=64 MiB, t=3) or PBKDF2-SHA256 ≥ 600k.
3. Store `{v, address, alg, salt, iv, ciphertext, credId?}` in **IndexedDB** (`blockid-wallet` store). The raw key only
   exists in memory while unlocked; auto-lock after 15 min idle (configurable).
4. Session unlock convenience: optionally cache a *second*, non-extractable AES key in IndexedDB bound to this browser
   ("Remember this device for 30 days") — never the raw private key.
5. **Recovery kit** shown once at creation (must confirm before continuing):
   a 24-word BIP-39 mnemonic of the key (or a random 128-bit recovery code that encrypts an escrow copy) — user
   downloads a PDF / writes it down.
6. **Optional encrypted cloud backup** (recommended default ON): the same ciphertext, encrypted under a key derived from
   the recovery code, uploaded to `studio.wallet_backups`. The server holds ciphertext only; restoring on a new device =
   email OTP + recovery code (or passkey PRF if the passkey is synced by iCloud/Google).
7. **Last-resort register recovery** (unique to a permissioned share register): if the key *and* recovery code are lost,
   the holder re-verifies identity (KYC), creates a new device wallet, files a `recovery_requests` row; an **admin
   approves**, the issuer calls `forcedTransfer(old, new, balance, keccak("recovery:<id>"))` on BlockID and re-anchors
   Hoodi/HSK; the old wallet is `setFrozen` first and `revokeInvestor`'d after. Unclaimed dividends of the old wallet are
   re-issued to the new one in the next round. (Crypto held in the lost wallet, e.g. mAUD, is *not* recoverable — say so.)

**Login flow (UX).** `/signin` screen with two tabs: **Email** (default for investors) and **Wallet** (MetaMask/SIWE, as
today; admin password stays at `/admin`).
1. Email → `POST /v1/auth/email/start {email}` → 6-digit OTP + magic link (10 min, single use, 5 attempts, rate limit per
   email + IP).
2. `POST /v1/auth/email/verify {email, code}` → short-lived `email_proof` cookie (5 min), no session yet.
3. New user → create device wallet (steps above) → sign a normal EIP-4361 message with the local key (domain
   `eth.blockid.au`, chain 262626) → `POST /v1/auth/siwe` (existing endpoint) with the `email_proof` cookie → server
   links `email ↔ address` in `studio.accounts` and issues the usual `__Host-bid_session` with `auth_method="email_device"`.
4. Returning user on a known device → OTP (or passkey) + unlock → SIWE. On an unknown device → OTP → "Restore wallet"
   (recovery code or synced passkey) → SIWE.
5. Signing later (e.g. free-mode transfers, subscriptions) uses a viem `LocalAccount` wallet client on the matching RPC
   (`CHAINS` in `wallet.ts`); a confirm dialog shows decoded calldata ("Transfer 100 EBA to 0x…"), never blind-sign.
   Gas: BlockID Chain gas price is 0; the existing `studio/gas.py` drip covers BLKD; Hoodi/HSK are mirrors (paused) —
   investors never need gas there.

**Coexistence with SIWE / MetaMask and roles.**
- One code path: every session is still created by `/v1/auth/siwe`; `wallet.ts` gains `signInWithDeviceWallet()` next to
  `signInWithEthereum()`; `auth.tsx` gains `connectEmail()`.
- `studio.accounts` lets one email link several addresses (device wallet + MetaMask); `GET /v1/me/holdings` aggregates.
  Linking a MetaMask wallet = SIWE with it while signed in (`POST /v1/me/wallets/link`).
- **Admin role stays wallet-list based** (`ADMIN_WALLETS`) or admin password. New config `ADMIN_ALLOW_DEVICE_WALLET=false`
  (default): a device-wallet session is never elevated to `admin`, even if its address is listed — admins keep
  MetaMask/hardware (later Safe). Company roles (`company_admins`) may be device wallets (founders without MetaMask),
  but `owner` role changes require a second factor (fresh OTP).
- Agents: unchanged; the device wallet lives only in the browser.

**Data model.**
```sql
CREATE TABLE IF NOT EXISTS studio.accounts (id serial PRIMARY KEY, email citext UNIQUE NOT NULL, email_verified_at timestamptz,
  display_name text, locale text NOT NULL DEFAULT 'en', created_at timestamptz NOT NULL DEFAULT now(), disabled_at timestamptz);
CREATE TABLE IF NOT EXISTS studio.account_wallets (account_id int REFERENCES studio.accounts(id) ON DELETE CASCADE,
  address text NOT NULL UNIQUE, kind text NOT NULL CHECK (kind IN ('device','injected','safe')), label text,
  linked_at timestamptz NOT NULL DEFAULT now(), revoked_at timestamptz, PRIMARY KEY (account_id, address));
CREATE TABLE IF NOT EXISTS studio.email_otps (id serial PRIMARY KEY, email citext NOT NULL, code_hash text NOT NULL,
  link_token_hash text, purpose text NOT NULL, attempts int NOT NULL DEFAULT 0, ip inet, created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL, used_at timestamptz);
CREATE TABLE IF NOT EXISTS studio.wallet_backups (address text PRIMARY KEY, account_id int REFERENCES studio.accounts(id),
  ciphertext bytea NOT NULL, kdf jsonb NOT NULL, version int NOT NULL DEFAULT 1, updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS studio.recovery_requests (id serial PRIMARY KEY, company_id int REFERENCES studio.companies(id),
  account_id int REFERENCES studio.accounts(id), old_wallet text NOT NULL, new_wallet text NOT NULL, kyc_ref text,
  status text NOT NULL, decided_by text, decided_at timestamptz, tx_hash text, created_at timestamptz NOT NULL DEFAULT now());
ALTER TABLE studio.sessions ADD COLUMN IF NOT EXISTS account_id int, ADD COLUMN IF NOT EXISTS auth_method text;
CREATE TABLE IF NOT EXISTS studio.notification_prefs (account_id int PRIMARY KEY REFERENCES studio.accounts(id),
  email_updates boolean DEFAULT true, email_dividends boolean DEFAULT true, digest text DEFAULT 'instant');
```
(`citext` extension: `CREATE EXTENSION IF NOT EXISTS citext;` — or use `lower(email)` unique index.)

**API.** `POST /v1/auth/email/start` · `POST /v1/auth/email/verify` · `GET /v1/auth/email/link?token=` (magic link →
same as verify) · existing `POST /v1/auth/siwe` (accepts optional `email_proof` cookie) · `GET/PUT /v1/me/backup`
(ciphertext) · `POST /v1/me/wallets/link` · `DELETE /v1/me/wallets/{address}` · `POST /v1/me/recovery` ·
admin `GET /v1/admin/recoveries`, `POST /v1/admin/recoveries/{id}/approve|reject` (new queue `recoveries`, gate).
Issuer: `POST /recover {recovery_id}` → freeze old, KYC new, `forcedTransfer`, re-anchor (reuses transfer code in
`issuer/transfers.py`).

**Email delivery.** New `studio/mailer.py` with a provider interface (`send(to, template, vars)`), SMTP fallback,
templates in EN/VI. Provider choice in §6; recommend **AWS SES in `ap-southeast-2` (Sydney)** for AU data residency and
cost, or **Postmark/Resend** for fastest setup. Configure SPF, DKIM, DMARC on `blockid.au`; send from
`no-reply@eth.blockid.au`. Env: `MAIL_PROVIDER, MAIL_FROM, SMTP_URL | SES_REGION | POSTMARK_TOKEN`. Store only hashed OTPs.

**Threat model.**

| Threat | Mitigation |
|---|---|
| XSS steals key | Key encrypted at rest; plaintext only in memory while unlocked; strict CSP already in place (no inline except hashed) — keep it; wallet code in its own lazy chunk; no third-party scripts on `/signin` and signing dialogs; Trusted Types where feasible. |
| Email account takeover | Email alone gives nothing: a session always needs a SIWE signature from the key, which requires this device (IndexedDB + passkey/passphrase) or the recovery code. Restoring the cloud backup also needs the recovery code. |
| OTP brute force / enumeration | 6 digits, 5 attempts, 10 min TTL, per-IP + per-email limits (reuse lockout helper keyed by `CF-Connecting-IP`), identical responses for known/unknown emails. |
| Server compromise | Server stores only ciphertext backups + email↔address links; cannot move holders' shares without the issuer (and issuer acts only on approved rows). Register recovery requires KYC + admin approval + is logged/anchored. |
| Malicious recovery (social engineering admin) | Recovery queue shows KYC match, 72 h delay with email notice to the old address's account, second admin approval for > 5% holders (four-eyes). |
| Lost device + lost code | Shares recoverable via register recovery; state clearly that token balances other than shares (mAUD) are not. |
| Phishing sites asking to sign | SIWE domain binding (server checks domain/URI/chain); device wallet refuses to sign messages for other domains; transaction preview. |
| Weak passphrase | Prefer passkey PRF; enforce zxcvbn ≥ 3 for passphrase; Argon2id. |

**Human gate.** None for login; admin gate for register recovery. **Anchoring.** Recovery forced transfer emits
`ForcedTransfer(..., reason)` on BlockID; next `CapTableAnchor.anchor` on Hoodi/HSK. **Dependencies.** Mail provider,
DNS records. **Effort.** M (≈ 8–10 dev-days incl. tests).

### 3c. Periodic AI business updates — effort L (split M + M)

**User story.** As a founder I connect or upload my numbers once; every period an AI analyst drafts an update and a
revaluation proposal; I review and approve; my shareholders get it in their inbox and portal, and anyone can verify
it was not changed afterwards. As an investor I get a consistent, cited update on a fixed cadence.

**Cadences and gates.**

| Cadence | Content | Revaluation | Approver |
|---|---|---|---|
| Weekly pulse (opt-in) | KPI deltas only, computed by code, 3-line AI summary | none | company owner (1 click); auto-publish allowed if company enables "computed-only pulses" |
| Monthly | KPIs + narrative + risks + asks | none (mark shown unchanged) | company owner |
| Quarterly | Monthly + SVI re-score with new self-reported metrics + proposed new mark | **proposed** | company owner **and** platform admin (mark change) |
| Annual | Full re-run of `site_valuation` + financial statements upload + year review | **proposed** | company owner **and** platform admin |

**KPI inputs (in order of delivery).**
1. Manual form + CSV upload (`/c/:tk/kpis`): revenue, gross margin, cash, burn, runway, customers, headcount, ARR/MRR,
   churn, custom KPIs. Same field names as today's `metrics` in `POST /v1/studio/valuations` so SVI can reuse them.
2. Stripe (read-only restricted key): MRR/charges/refunds/customers, pulled by the worker.
3. Xero and QuickBooks Online (OAuth 2.0, read-only accounting scopes): P&L, balance sheet, bank summary.
   Tokens stored encrypted (`pgcrypto` or app-level Fernet key in `app.env`); scoped read-only; revocable.
Every KPI value has `source` = `manual | csv | stripe | xero | qbo` and a `source_ref` (file hash / API object id),
so the update can cite it.

**Agent changes (worker; no keys).** New graph `company_update` in `graph.py` with nodes:
`load_kpis → compute_deltas (code) → optional web_refresh (safefetch, ≤ 3 searches, same budget rules) →
draft_update (LLM, Pydantic schema, every numeric claim must reference a kpi id or evidence url; uncited claims dropped
as in research.py) → propose_revaluation (quarterly/annual: tools/svi.py with new self_reported metrics; code computes the
number) → consistency_check (code: numbers in narrative must equal KPI values ±0.5%) → waiting_approval`.
Register the agent in `policy.py` with read-only tools. LLM routing unchanged (`LLM-ROUTING.md`). PII: KPI data is
company-confidential → route to the `local` tier if the company flags "confidential" (existing tiering).

**Data model.**
```sql
CREATE TABLE IF NOT EXISTS studio.kpi_sources (id serial PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('manual','csv','stripe','xero','qbo')), status text NOT NULL, secret_enc bytea, meta jsonb NOT NULL DEFAULT '{}',
  connected_by text, connected_at timestamptz NOT NULL DEFAULT now(), last_sync_at timestamptz, error text);
CREATE TABLE IF NOT EXISTS studio.kpi_values (id bigserial PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id) ON DELETE CASCADE,
  metric text NOT NULL, period_start date NOT NULL, period_end date NOT NULL, value numeric NOT NULL, unit text NOT NULL DEFAULT 'AUD',
  source_id int REFERENCES studio.kpi_sources(id), source_ref text, entered_by text, created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (company_id, metric, period_end, source_id));
CREATE TABLE IF NOT EXISTS studio.update_schedules (company_id int PRIMARY KEY REFERENCES studio.companies(id) ON DELETE CASCADE,
  weekly boolean DEFAULT false, monthly boolean DEFAULT true, quarterly boolean DEFAULT true, annual boolean DEFAULT true,
  auto_publish_pulse boolean DEFAULT false, timezone text DEFAULT 'Australia/Sydney', next_run_at timestamptz);
CREATE TABLE IF NOT EXISTS studio.updates (id text PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id) ON DELETE CASCADE,
  cadence text NOT NULL CHECK (cadence IN ('weekly','monthly','quarterly','annual','adhoc')), period_start date NOT NULL, period_end date NOT NULL,
  status text NOT NULL,  -- queued|running|waiting_owner|waiting_admin|approved|publishing|published|rejected|failed
  steps jsonb NOT NULL DEFAULT '[]', draft jsonb, final jsonb, kpi_snapshot jsonb, evidence jsonb, warnings jsonb,
  proposed_valuation_aud numeric, proposed_mark_aud numeric, valuation_id text REFERENCES studio.valuations(id),
  content_hash text, anchor jsonb,   -- {blockid:{tx,block}, hoodi:{...}, hsk:{...}, provenance_id}
  owner_approved_by text, owner_approved_at timestamptz, admin_approved_by text, admin_approved_at timestamptz,
  published_at timestamptz, error text, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE (company_id, cadence, period_end));
CREATE TABLE IF NOT EXISTS studio.update_questions (id serial PRIMARY KEY, update_id text REFERENCES studio.updates(id) ON DELETE CASCADE,
  asked_by text NOT NULL, question text NOT NULL, answer text, answered_by text, created_at timestamptz DEFAULT now(), answered_at timestamptz);
CREATE TABLE IF NOT EXISTS studio.notifications (id bigserial PRIMARY KEY, account_id int, address text, kind text NOT NULL,
  company_id int, ref text, title text NOT NULL, body text, read_at timestamptz, emailed_at timestamptz, created_at timestamptz DEFAULT now());
```
Scheduler: a small loop in `agents-worker` (or `jobs.py`) that every 10 min enqueues `company_update` jobs whose
`next_run_at` passed; idempotent by `UNIQUE(company_id, cadence, period_end)`.

**API.** Founder: `GET/PUT /v1/companies/{tk}/kpis` · `POST /v1/companies/{tk}/kpis/csv` · `POST /v1/companies/{tk}/kpi-sources/{kind}/connect` (OAuth start) ·
`GET /v1/oauth/{kind}/callback` · `GET/PUT /v1/companies/{tk}/update-schedule` · `POST /v1/companies/{tk}/updates {cadence, period_end}` (manual run) ·
`GET /v1/companies/{tk}/updates` · `GET /v1/updates/{id}` · `POST /v1/updates/{id}/owner-decision {approved, edits?}`.
Admin: `POST /v1/admin/updates/{id}/decision {approved, overrides?}` (queue `updates`, gate).
Investor: `GET /v1/me/updates` · `POST /v1/updates/{id}/questions` · `POST /v1/notifications/{id}/read`.
Public: `GET /v1/verify/update/{id}` (canonical JSON + hash + on-chain anchors), extends `studio/verify.py`.

Visibility: published updates are visible to **holders of that company** (balance > 0 at publish time or now) and
company admins; a public "headline" (title, period, KPIs the founder marks public) is shown on `/companies/:tk`.

**Contract changes.** New tiny contract `DisclosureRegistry.sol` (deploy on BlockID, Hoodi, HSK like CapTableAnchor):
```solidity
function publish(string ticker, uint8 cadence, uint64 periodEnd, bytes32 contentHash, bytes32 valuationHash, string uri)
  external onlyRole(PUBLISHER_ROLE);  // emits Disclosed(tickerHash, ticker, cadence, periodEnd, contentHash, valuationHash, uri, index)
function latest(string ticker) view; function count(string ticker) view;
```
PUBLISHER_ROLE = issuer. Plus: on HSK, record the agent's proposal in the existing `AgentProvenance`
(`propose(agentId, contentHash)` by the issuer on the agent's behalf → `approve` by the approving admin's role →
`markExecuted`), so the four-eyes trail is on-chain. If a revaluation is approved, reuse the existing
`anchorValuation(reportHash, cents)` path (`/revalue` in the issuer). Optional later: EAS off-chain attestation
(EIP-712) of each update, UID stored in `uri` (EAS is not on HSK; register the schema on an Ethereum testnet).

**Human gate / publish.** `waiting_owner` → owner approves (can edit narrative; edits are diffed and stored) →
if revaluation proposed: `waiting_admin` → admin approves/overrides → `approved` → API calls issuer `POST /disclose
{update_id}` → `publishing` (content hash computed over canonical JSON by `studio/report_hash.py`, same code as
valuations) → `published` → notifications fan-out (in-app rows + email per prefs).
**Effort.** M (manual KPIs + monthly/quarterly + anchor + notifications) then M (Stripe/Xero/QBO connectors).
**Dependencies.** 3b (emails), mail provider, 3d (for "your stake" block in the email).

### 3d. Investor position analytics — effort M

**User story.** As a holder I see my shares, %, value at the latest approved mark, cost basis, P&L, dilution events and
dividends — tied to what the business actually reported.

**Method.** Chain is the source of truth for balances; the DB keeps an indexed ledger for history.
- Indexer job (API-side, read-only RPC; no keys): scan `Transfer`, `SharesIssued`, `SharesCancelled`, `ForcedTransfer`
  on each BlockID token and `Claimed` on each distributor from `local_block`; store in `holdings_ledger`. Resume from
  `indexer_cursor`. Blockscout API can be used as a fallback.
- Cost basis: issuance = issue price (A$1.00 default or offering price); mint = `mints.price_aud` (new column, default
  current mark); free-mode transfer = holder-entered price (optional, "self-reported" badge); forced transfer/recovery =
  carry over. FIFO lots.
- Value(t) = shares(t) × mark(t) using `studio.marks` (step function). Unrealised P&L = value − cost; total return
  shown as "value change + dividends received" — label: "Based on approved marks, not a market price".
- Dilution event = any supply increase: `pct_before = shares/supply_before`, `pct_after = shares/supply_after`,
  value effect = shares × (mark_after − mark_before) (usually 0 at issue, >0 if priced above mark).

**Data model.**
```sql
CREATE TABLE IF NOT EXISTS studio.holdings_ledger (id bigserial PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id) ON DELETE CASCADE,
  wallet text NOT NULL, kind text NOT NULL,   -- issue|mint|transfer_in|transfer_out|forced_in|forced_out|cancel|dividend
  shares_delta bigint NOT NULL DEFAULT 0, amount_units bigint, price_aud numeric, supply_after bigint, block bigint NOT NULL, tx_hash text NOT NULL,
  log_index int NOT NULL, at timestamptz NOT NULL, ref text, UNIQUE (tx_hash, log_index));
CREATE INDEX IF NOT EXISTS holdings_ledger_wallet_idx ON studio.holdings_ledger (lower(wallet), company_id, block);
CREATE TABLE IF NOT EXISTS studio.indexer_cursor (company_id int PRIMARY KEY, last_block bigint NOT NULL);
ALTER TABLE studio.mints ADD COLUMN IF NOT EXISTS price_aud numeric;
```

**API.** `GET /v1/me/holdings` (upgrade to ledger) · `GET /v1/me/holdings/{tk}` →
`{shares,pct,mark,value,cost,unrealised,dividends_total,series:[{at,shares,pct,mark,value}],dilution:[...],dividends:[...]}` ·
`GET /v1/me/holdings.csv`. Company-side: `GET /v1/companies/{tk}/investors` (owner/admin: per-holder stats,
update read-rates).
**UI.** `/i/h/:tk/position` (area chart value, line %; reuse `components/charts.tsx` + `MarkPanel` step markers for
updates/revaluations/dividends), `/i/h/:tk/dilution` (waterfall of % over events), totals on `/i/holdings`.
**Contracts / gate / anchoring.** None; read-only. Add "Verify my balance" button → 3g proof.
**Dependencies.** None hard; better with 3f prices.

### 3e. Automatic dividends to wallets (near-realtime) — effort M

**Options considered.**

| Option | Realtime? | Fits our stack? | Verdict |
|---|---|---|---|
| **A. Merkle snapshot round + relayer push (today)** | Seconds after approval | Yes — built, tested, gas paid by relayer; handles KYC'd holders; auditable root | **Keep as core** |
| B. Pull-only Merkle claims | Holder must act | Yes | Keep as fallback for frozen/unreachable wallets |
| C. Streaming (Superfluid-style) | Per-second | Superfluid not on BlockID/HSK testnet; streams conflict with transfer restrictions and with a profit-based (lumpy) payout; tax records harder | Reject |
| D. Accumulator "dividend-per-share" (ERC-2222/FDT pattern) in the token | Instant on deposit, auto-handles transfers | Needs token `_update` hook changes + re-deploy of all share tokens | Later, only with the ERC-3643 migration |

**Design (Option A upgraded).**
1. **Dividend policy** per company (`dividend_policies`): payout ratio of approved net profit or fixed amount,
   frequency (monthly/quarterly/on-demand), max per round, treasury wallet. A company owner + platform admin approve the
   policy once (**standing approval** with caps; human-signed, stored + audited).
2. When a quarterly/annual update is published with profit KPIs, the **dividend agent** (existing
   `agents/dividend.py`, no keys) *proposes* a round within the policy caps → `dividends` row `pending` with Merkle plan
   (existing code). Within caps and policy → auto-approved by the policy (the human approval is the policy itself,
   recorded as `approved_by = policy:<id>`); outside caps → normal admin queue. Owner can veto for 24 h before
   execution (notice period shown to holders: "Dividend of A$x/share declared, record date …, paid on …").
3. Execution: issuer `createRound` then **batched** `claimForMany(roundId, accounts[], amounts[], proofs[][])` (new
   function, ~100 holders/tx) instead of one tx per holder; failures fall back to pull (`claim`) with a portal button.
4. Record date = snapshot block (already implicit); show it. Frozen wallets / pending recovery → skipped and held in the
   round until `closeRound`/re-issue.
5. Notifications + receipts (per-holder PDF/CSV line: gross, withholding, net, tx hash).
6. Currency: **mAUD (testnet DemoAUD)** now; production candidates **AUDD** (AUD stablecoin) or USDC — decision tied to
   the licensed-partner route (§5). Keep the `unit` column so the distributor token is configurable per company.
7. Tax fields (production, not testnet): TFN/ABN-quoted flag per holder (TFN withholding at 47% if not
   quoted, on the unfranked part), franking % per round, non-resident withholding (30% default / treaty rate on the unfranked part; franked part exempt); the platform records and reports —
   the company remains responsible. Shown as disabled "production only" fields on testnet.

**Data model.**
```sql
CREATE TABLE IF NOT EXISTS studio.dividend_policies (id serial PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('payout_ratio','fixed','manual')), ratio_pct numeric, fixed_units bigint, max_units_per_round bigint NOT NULL,
  frequency text NOT NULL, veto_hours int NOT NULL DEFAULT 24, token text NOT NULL DEFAULT 'mAUD', status text NOT NULL,
  owner_approved_by text, admin_approved_by text, created_at timestamptz DEFAULT now(), expires_at timestamptz);
ALTER TABLE studio.dividends ADD COLUMN IF NOT EXISTS policy_id int, ADD COLUMN IF NOT EXISTS update_id text,
  ADD COLUMN IF NOT EXISTS record_block bigint, ADD COLUMN IF NOT EXISTS pay_after timestamptz, ADD COLUMN IF NOT EXISTS franking_pct numeric,
  ADD COLUMN IF NOT EXISTS executed_at timestamptz;
CREATE TABLE IF NOT EXISTS studio.dividend_payments (dividend_id int REFERENCES studio.dividends(id) ON DELETE CASCADE, wallet text NOT NULL,
  gross_units bigint NOT NULL, withheld_units bigint NOT NULL DEFAULT 0, net_units bigint NOT NULL, status text NOT NULL, tx_hash text,
  paid_at timestamptz, PRIMARY KEY (dividend_id, wallet));
```
**API.** `GET/PUT /v1/companies/{tk}/dividend-policy` · `POST /v1/admin/dividend-policies/{id}/approve` ·
`POST /v1/companies/{tk}/dividends/{id}/veto` · `GET /v1/me/dividends` · `GET /v1/me/dividends.csv`.
**Contract.** `DividendDistributor.claimForMany` (+ Foundry tests: sum ≤ funded, double-claim reverts, gas per 100).
Redeploy distributor for new companies; existing ones keep per-holder loop.
**Gate.** Policy approval (owner + admin) or per-round admin approval outside policy; 24 h veto.
**Anchoring.** Round root on BlockID (already); add the round root + total into the next `DisclosureRegistry.publish`
URI for Hoodi/HSK visibility.
**Effort.** M. **Dependencies.** 3c (profit KPIs) for policy-driven rounds; works standalone as manual rounds today.

### 3f. Token offering / "listing" with disclosures (simulated primary subscription) — effort L

**User story.** As a founder I open a (testnet, simulated) share offering at a price tied to my approved valuation,
with a disclosure bundle; investors of any size subscribe from their wallet; if the minimum is reached, shares are
issued and funds released; otherwise everyone is refunded automatically.

**Flow (founder, in workspace `/c/:tk/offering`).** 1 Terms (price per share ≤ latest approved mark × (1+x) with
warning, min/max raise, per-investor min/max, retail cap per investor, dates, max holders) → 2 Disclosure bundle
(auto-assembled: latest approved valuation report + hash, last 4 published updates, cap table before/after, use of
funds, risks, AI "key risks" summary, founder statement) → 3 Preview for investors → ◆ admin approval → open.
**Investor (`/i/offerings/:id`):** read bundle (must scroll/acknowledge risk warning) → KYC (existing
`POST /v1/companies/{tk}/kyc` → admin queue) → subscribe: approve mAUD + `deposit` into escrow (device wallet or
MetaMask) → **5-day cooling-off** withdrawal button (mirrors the CSF regime, RG 261) → close → allocation.
**Close:** if raised ≥ min → admin ◆ approves settlement → issuer `issue()` shares to each subscriber (KYC registered),
escrow releases funds to company treasury, re-anchor Hoodi/HSK, event `offering_settled`; else anyone can trigger
`refundAll` after deadline (permissionless, relayer does it automatically).

**Rules enforced in code/contract:** holder cap (`maxShareholders`; set **50 non-employee** for Pty-style companies),
per-investor cap (retail), min/max raise, KYC-only deposits (`IdentityRegistry.isVerified`), deadline, oversubscription →
pro-rata or first-come (choose per offering).

**Data model.**
```sql
CREATE TABLE IF NOT EXISTS studio.offerings (id serial PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id) ON DELETE CASCADE,
  status text NOT NULL,  -- draft|pending_approval|open|closed|settling|settled|refunding|refunded|rejected
  price_units_per_share bigint NOT NULL, min_raise_units bigint NOT NULL, max_raise_units bigint NOT NULL, inv_min_units bigint, inv_max_units bigint,
  retail_cap_units bigint, max_holders int, allocation text NOT NULL DEFAULT 'fcfs', opens_at timestamptz, closes_at timestamptz,
  cooling_off_days int NOT NULL DEFAULT 5, bundle jsonb, bundle_hash text, escrow text, anchor jsonb, created_by text, approved_by text,
  created_at timestamptz DEFAULT now());
CREATE TABLE IF NOT EXISTS studio.subscriptions (id serial PRIMARY KEY, offering_id int NOT NULL REFERENCES studio.offerings(id) ON DELETE CASCADE,
  wallet text NOT NULL, account_id int, amount_units bigint NOT NULL, shares bigint, status text NOT NULL,  -- deposited|withdrawn|allocated|refunded
  deposit_tx text, settle_tx text, refund_tx text, created_at timestamptz DEFAULT now(), UNIQUE (offering_id, wallet));
```
**API.** `POST/GET/PUT /v1/companies/{tk}/offerings` · `POST /v1/companies/{tk}/offerings/{id}/submit` ·
admin `POST /v1/admin/offerings/{id}/approve|reject|settle` (queue `offerings`, gate) · `GET /v1/offerings` (public list,
testnet banner) · `GET /v1/offerings/{id}` (bundle) · `POST /v1/offerings/{id}/subscriptions {deposit_tx}` (API checks
receipt, like free-mode transfers) · `POST /v1/offerings/{id}/subscriptions/withdraw`.
**Contract.** `OfferingEscrow.sol` (one per offering, deployed by issuer): `deposit(amount)` (KYC check, caps, deadline),
`withdraw()` within cooling-off, `settle(allocations[])` onlyIssuer (transfers funds to treasury; issuer issues shares
on the token in the same job), `refund(address)` / `refundAll()` after deadline if not settled; events for every step.
Bundle hash stored in escrow constructor and in `DisclosureRegistry` (cadence = `offering`). Foundry tests incl.
invariants (escrow balance = Σ deposits − withdrawals − refunds − released).
**Agents.** Disclosure-bundle agent (no keys) assembles and summarises; flags if price > mark or stale updates (> 90 d).
**Gates.** Open (admin), settle (admin), KYC (admin). **Effort.** L. **Dependencies.** 3b, 3c (bundle content), 3d.
**Legal.** Always labelled "Simulated offering on testnet. Not an offer of securities. No real money." Production
requires a licensed CSF intermediary/AFSL partner (§5).

### 3g. Custody & transparency page — effort S–M

**Route.** `/trust` (public) + `/trust/:tk` (per company). Nav item "Trust".
**Content.**
1. **Who holds keys** — diagram (reuse home "How it works" SVG): agents (no keys) · admins (listed addresses, how they
   sign in) · issuer (hot key, isolated container) · relayer (gas only, `claimFor`) · holders (their own wallet —
   device or MetaMask). Roadmap badge: "Moving admin roles to a 2-of-3 Safe".
2. **Per company, read live from chain:** role holders (`hasRole` for DEFAULT_ADMIN, ISSUER, TRANSFER_AGENT, PAUSER on
   token; KYC_AGENT on registry; ISSUER on distributor), paused state, total supply per chain, latest
   `CapTableAnchor.latest(ticker)` root/block/index on Hoodi and HSK, `valuationReportHash()` per chain, last
   `DisclosureRegistry` entry, distributor balance vs unclaimed total.
3. **Verify my holding:** `GET /v1/companies/{tk}/proof/{wallet}` → `{balance, leaf, proof[], root, anchors}`; the
   browser calls `CapTableAnchor.verify(ticker, wallet, balance, proof)` on Hoodi and HSK and shows ✓/✗ (the server
   is not trusted for the result).
4. **Audit trail:** latest hash-chained audit head (`audit.py`, `verify-audit`) + daily anchor of the head (currently
   "should be anchored") via `DisclosureRegistry.publish("PLATFORM", cadence=audit, ...)`.
5. **Custody model statement** (testnet vs production target): self-custody by default (device/MetaMask); register
   recovery via ERC-3643-style forced transfer; production: licensed custodian option for institutions, Safe multisig
   for issuer admin.
**API.** `GET /v1/trust` · `GET /v1/trust/{tk}` (cached 60 s, chain reads) · `GET /v1/companies/{tk}/proof/{wallet}`
(Merkle builder already in `issuer/merkle.py` / `tools/merkle.py`; expose read-only in API).
**Contracts.** None (reads). **Gate.** None. **Effort.** S (static + role reads) → M (proof + audit anchor).

---

## 4. Phased execution plan

Each task: ≤ 1 day unless stated. "AC" = acceptance criteria. Always run: `make test` (pytest + forge), `npm run build`
in `web/app`, then `scripts/screenshots/flow-smoke.mjs` (extend its `pub`/admin lists with every new route — it fails on
JS errors, NaN/undefined text, horizontal scroll).

### Phase 0 — quick wins (1–2 days): rebrand + read-only investor portal

| # | Task | AC / verification |
|---|---|---|
| 0.1 | Update `docs/FACTS.md` first: product name, H1, sub, pitch, pillars, rights table, revised "terms to avoid" | FACTS is the single source; reviewed by owner |
| 0.2 | Replace brand + hero strings: `index.html` (title, meta, noscript), `dict.proto.ts` (`hero.*` EN/VI), `dict.ts` (`hero.sub`), `wallet.ts:137` statement, `lib/hooks.ts` title suffix | `grep -rn "Startup Passport" web/ scripts/` → 0 hits; SIWE login still works (statement not validated server-side) |
| 0.3 | Home: new H1/sub/pitch, 5 pillar cards, rights strip (all/retail/professional), CTAs "See a live passport" (`/i/demo`) + "List your business" (`/start`) | EN+VI render; mobile 390 px no horizontal scroll; legal line visible above the fold |
| 0.4 | API `GET /v1/me/holdings` (chain `balanceOf` over issued companies, cached) + `GET /v1/demo/holdings` | pytest with fake chain; returns EBA for a known holder wallet; 401 without session for `/me` |
| 0.5 | `flow.ts`: `INV`, `INV_TOP`, `invPath`; `pages/Investor.tsx` with `/i/holdings` and `/i/h/:tk/{position,dilution,dividends,updates,rights}` (position/dilution from existing `marks` + `events` in `GET /v1/companies/{tk}`; dividends from `events` `dividend_*`; updates = "coming soon" + last revaluation events) | smoke: all `/i/*` routes rail>0, no errors; `/i/demo` works logged out |
| 0.6 | Nav: add "Investors" + "Trust"; rename rail heading Founder→Business | screenshots EN/VI |
| 0.7 | `/trust` v0: static key-holder diagram + per-company chain links (from existing company detail) | page loads, links resolve |
| 0.8 | Docs: README hero, FEATURES §1 caption, decks later | `grep` clean in README/FACTS |

### Phase 1 — accounts + positions (≈ 2 weeks)

| # | Task | AC / verification |
|---|---|---|
| 1.1 | `studio/mailer.py` (SMTP + SES/Postmark adapters, EN/VI templates); DNS SPF/DKIM/DMARC | test email lands in Gmail inbox (not spam); mail-tester ≥ 9/10 |
| 1.2 | Schema: `accounts`, `account_wallets`, `email_otps`, `wallet_backups`, `sessions` cols, `notification_prefs` | idempotent re-apply at API start; pytest migration test |
| 1.3 | `POST /v1/auth/email/start|verify`, magic link, rate limits | pytest: expiry, 5-attempt lock, enumeration-safe responses |
| 1.4 | Extend `/v1/auth/siwe` to bind `email_proof` → account; `ADMIN_ALLOW_DEVICE_WALLET=false` | pytest: device-wallet session with admin address → role `user` |
| 1.5 | `devicewallet.ts`: generate, PRF-passkey wrap, passphrase (Argon2id) fallback, IndexedDB, lock/unlock, sign SIWE, sign tx with preview | Vitest unit tests (encrypt/decrypt roundtrip, wrong pass fails); Playwright: create → logout → unlock → SIWE; key never in `localStorage`, never in network logs (assert with request interception) |
| 1.6 | Recovery kit UI (mnemonic/recovery code, confirm step), encrypted backup `GET/PUT /v1/me/backup`, restore on new browser context | Playwright: context A create, context B restore with code → same address |
| 1.7 | `/signin` page (Email default, Wallet tab), `/i/account` (linked wallets, link MetaMask) | smoke + manual MetaMask test unchanged |
| 1.8 | Indexer + `holdings_ledger` + `indexer_cursor`; `mints.price_aud` | backfill for 12 live companies; Σ ledger = on-chain `balanceOf` for every holder (script check) |
| 1.9 | `GET /v1/me/holdings/{tk}` series/dilution/dividends + CSV; wire `/i/h/:tk/*` | numbers match cap table and `marks`; P&L label shown |
| 1.10 | `/trust/:tk` live role reads + `GET /v1/companies/{tk}/proof/{wallet}` + browser-side `CapTableAnchor.verify` | ✓ on Hoodi and HSK for an EBA holder; ✗ for a tampered balance |
| 1.11 | Recovery request queue (`recovery_requests`, admin queue `recoveries`, issuer `/recover`) | end-to-end on testnet: shares moved, old frozen, mirrors re-anchored, audit rows |

### Phase 2 — AI updates + notifications (≈ 3 weeks)

| # | Task | AC / verification |
|---|---|---|
| 2.1 | Schema `kpi_sources`, `kpi_values`, `update_schedules`, `updates`, `update_questions`, `notifications` | migration test |
| 2.2 | `/c/:tk/kpis` manual form + CSV import (template download) | validation errors inline; values listed with source |
| 2.3 | `company_update` graph (load → deltas → draft → consistency check); Pydantic schemas; `policy.py` registration (read-only) | offline tests with `fakes.py`: uncited numbers dropped; narrative numbers equal KPIs; injection text in KPI notes ignored |
| 2.4 | Quarterly/annual revaluation proposal via `tools/svi.py` with KPI-derived `self_reported` | deterministic test: same KPIs → same mark |
| 2.5 | Approval UI: owner review (diff of edits) at `/c/:tk/updates/:id`; admin queue `updates` in `QUEUES` + `/admin/updates/:id` | gate links carry `?return=`; cannot publish without approvals (API 409) |
| 2.6 | `DisclosureRegistry.sol` + tests + deploy script (BlockID, Hoodi, HSK); issuer `POST /disclose`; AgentProvenance propose/approve/execute on HSK | forge tests; `/verify/update/:id` recomputes hash in browser = on-chain on 3 chains |
| 2.7 | Notifications: in-app bell + `/i/updates` feed; email fan-out per prefs; unsubscribe link | holder receives email within 1 min of publish; non-holders do not |
| 2.8 | Scheduler loop (monthly default, weekly opt-in) | job created once per period (idempotent); timezone Sydney |
| 2.9 | Q&A thread on updates | answers included in the next anchored version (v2 hash) |
| 2.10 | Stripe connector (restricted key) → `kpi_values` | sandbox account MRR matches Stripe dashboard |
| 2.11 | Xero + QBO OAuth read-only connectors (encrypted tokens, revoke) | demo company P&L imported; token revocation works |

### Phase 3 — dividends automation + offering (≈ 4–5 weeks)

| # | Task | AC / verification |
|---|---|---|
| 3.1 | `DividendDistributor.claimForMany` + tests; issuer batch execution with per-holder fallback | 150 holders paid in ≤ 2 txs on BlockID; invariants pass |
| 3.2 | `dividend_policies`, `dividend_payments`, policy UI + dual approval; veto window; agent proposal after published update | policy-driven round executes only within caps; outside caps lands in admin queue |
| 3.3 | Investor dividends ledger + receipts (CSV/PDF), notifications "Declared" and "Paid" | holder sees tx hash and amount within 1 min of execution |
| 3.4 | `OfferingEscrow.sol` + invariant tests; deploy per offering by issuer | forge: deposits, cooling-off withdraw, settle, refundAll, caps, KYC-only |
| 3.5 | Offering schema + founder wizard `/c/:tk/offering` + bundle agent | bundle hash anchored; stale-update warning |
| 3.6 | Investor subscription UI (`/i/offerings/:id`) with device wallet / MetaMask; risk acknowledgement | Playwright: KYC → deposit → withdraw within cooling-off → deposit → settle → shares visible in `/i/holdings` |
| 3.7 | Admin queues `offerings` (open/settle); refund automation | failed min-raise → all refunded automatically |
| 3.8 | `/trust` audit-head daily anchor | anchor visible on 3 chains daily |

### Phase 4 — production hardening (tracked in `ROADMAP-RESEARCH.md`)
Safe 2-of-3 admin; official ERC-3643 + ONCHAINID (accumulator dividends option D then); real KYC (FrankieOne/greenID);
AUDD/USDC; licensed partner; audit; EIP-7702 passkey upgrades on Ethereum; ≥ 4 validators.

---

## 5. Risks and mitigations

| Risk | Mitigation |
|---|---|
| **Legal: offering = regulated activity** (securities offer, financial product advice, custody, dealing) | Keep "Testnet. Not an offer. No real money." on every investor page, email footer and offering screen; mAUD has no value; no real-money on-ramp. Before production: partner with a licensed CSF intermediary / AFSL holder (or obtain licences under the Digital Assets Framework, commencing ~8–9 Apr 2027 *[verify exact day]*); respect CSF rules (A$5M per 12 months per issuer, A$10k per retail investor per company per 12 months, 5-day cooling-off, turnover/assets < A$25M, AFSL intermediary) and the Pty 50 non-employee shareholder limit. Legal memo = Phase 4 gate. |
| **Legal: "Know … before you invest" reads as a promotion** | Pair with legal line; no performance claims; AI output labelled "general information, not advice" (RG 244/RG 255 style); investor pages show method + ranges. |
| **AI accuracy / hallucinated KPIs** | Numbers computed by code; LLM only narrates with KPI-id/URL citations; consistency check blocks publish; owner + admin approvals; published hash immutable, corrections as v2 with "correction" flag. Golden-set eval (ROADMAP item 3). |
| **Revaluation manipulation by founders** (self-reported KPIs inflate mark) | Mark changes need platform admin; show basis `self_reported` vs `xero/stripe verified`; cap single-step mark change (e.g. ±50%) without extra review; annual statements upload. |
| **Prompt injection via KPI notes/uploads** | Existing `<data>` wrapping + Pydantic; uploads parsed by code (CSV), not by LLM; red-team tests in 2.3. |
| **Device-key loss / theft** | Passkey PRF + recovery code + encrypted backup; register recovery with KYC + 72 h delay + four-eyes; clear UI warnings. |
| **XSS → key theft** | CSP, no third-party scripts, lazy isolated wallet chunk, auto-lock, tx preview; security review before Phase 1 ships. |
| **Email deliverability / phishing lookalikes** | SPF/DKIM/DMARC `p=quarantine`; never send links that sign anything; branded sender; users told "we never ask for your recovery code". |
| **Standing dividend approvals abused** | Policy caps, 24 h veto, owner + admin dual approval, auto-expiry (12 months), anomaly alerts. |
| **Issuer hot key** (single signer for issue/forced transfer/disclose) | Unchanged risk; Phase 4 Safe migration; OZ Monitor alerts on `ForcedTransfer`, role changes. |
| **Privacy** (holders' emails, KPI data offshore to LLM) | Emails never on-chain; confidential KPIs on `local` tier; Privacy Act APP 8 disclosure; data export/delete endpoints. |
| **Scope creep** | Phase gates: ship Phase 0 → owner demo → Phase 1; do not start 3f before 3b/3c are live. |

---

## 6. Research notes and sources

### 6.1 Positioning — who does what, and the gap we own

| Product | What it does | What it misses (our opening) |
|---|---|---|
| Carta | Cap table, 409A, LP/investor portal ([carta vs pulley](https://carta.com/carta-vs-pulley/), [investors plugin](https://carta.com/product-updates/investors-plugin/)) | Off-chain register; no verified, anchored KPI updates; no dividend rails |
| Pulley | Cap table, 409A, scenario modelling ([Qapita](https://www.qapita.com/blog/carta-vs-pulley)) | No investor updates anchoring, dividends or on-chain register |
| Cake Equity (AU) | Cap table + investor comms module, free ≤ 5 stakeholders ([Cake IR](https://www.cakeequity.com/features/investor-relations)) | Free-text updates, no verified KPIs, no dividend payment, no on-chain proof |
| Visible.vc | Investor updates, AI-drafted updates, engagement analytics ([updates](https://visible.vc/investor-updates/), [AI](https://visible.vc/ai-updates/)) | Self-reported data, no attestation; no cap table/register, no dividends |
| Vestd (UK) | EMI options, Companies House filings ([Exafol](https://www.exafol.com/comparison/carta-vs-vestd)) | UK-only; no on-chain, no AU |
| Republic | Crowdfunding marketplace | Post-raise update tooling not confirmed *[verify]* |
| Securitize | SEC transfer agent, on-chain ledger; Computershare partnership ([Crypto Briefing](https://cryptobriefing.com/securitize-onchain-shareholder-records/), [insights4.vc](https://insights4.vc/blog/the-state-of-onchain-real-world-assets-in-mid-2026/)) | US institutional; not SME/AU; no AI analysis or periodic updates |
| Ondo | Tokenised listed US stocks/ETFs, Broadridge comms ([CoinDesk](https://www.coindesk.com/business/2026/07/01/ondo-finance-debuts-sec-aligned-tokenized-stock-model-with-blackrock-etf-micron-shares)) | Listed securities only — private businesses out of scope |
| Figure | Issued its own shares on-chain ([insights4.vc](https://insights4.vc/blog/the-state-of-onchain-real-world-assets-in-mid-2026/)) | Not a SaaS for SMEs |
| Tokeny / ERC-3643 | Enterprise tokenisation, > US$32bn tokenised, Apex majority ([Tokeny](https://tokeny.com/apex-group-acquires-majority-stake-in-tokeny-to-catalyze-widespread-industry-tokenization-adoption/)) | Enterprise pricing; no AI valuation or investor-update layer |
| Propine | MAS-licensed custodian, asset servicing, investor reporting ([Propine](https://propine.com/about-us/)) | Singapore; AU presence not confirmed *[verify]* |
| Birchal (AU CSF) | > 300 CSF offers, ~A$218M, issuer dashboard ([Birchal](https://www.birchal.com/raise-capital), [post-raise](https://www.birchal.com/content/resources/obligations-after-your-capital-raise)) | Post-raise comms informal; no verified KPIs, no dividends, no on-chain register → **natural partner** (licensed intermediary + our post-raise layer) |
| Equitise (AU CSF) | Entered administration Oct 2024; AFSL suspended ([ASIC 24-286MR](https://www.asic.gov.au/about-asic/news-centre/find-a-media-release/2024-releases/24-286mr-asic-suspends-afs-licence-of-equitise-pty-ltd)) | Out of market |

**What we can own:** the *after-the-raise* layer for private SMEs — AI-analysed, human-approved, hash-anchored periodic
updates + revaluation, tied to an on-chain register that is the proof of ownership, with dividends pushed to every
wallet. Nobody above combines all four for small private companies, and CSF platforms (Birchal) leave exactly this gap.

### 6.2 Keys and login
- Embedded wallets: Privy (TEE + Shamir, Stripe-owned), Dynamic (TSS-MPC, Fireblocks-owned), Web3Auth (ConsenSys),
  Turnkey (TEE with attestation), Magic (HSM) — [Openfort](https://www.openfort.io/blog/privy-alternatives),
  [Fireblocks comparison](https://www.fireblocks.com/report/compare-embedded-wallet-infrastructure),
  [BlockEden](https://blockeden.xyz/blog/2025/11/02/the-waas-infrastructure-revolution/). Vendor consolidation is a
  lock-in signal → prefer self-hosted for the MVP.
- WebCrypto has no secp256k1 ([w3c/webcrypto#82](https://github.com/w3c/webcrypto/issues/82)) → wrap the secp256k1 key
  with a non-extractable AES-GCM key ([MDN](https://developer.mozilla.org/en-US/docs/Web/API/EcKeyGenParams)).
- WebAuthn PRF: Safari 18+/iCloud Keychain, Chrome/Edge with Google Password Manager, Firefox 148+, Windows Hello
  (Win 11 24H2+); not with external keys on iOS ([Corbado](https://www.corbado.com/blog/passkeys-prf-webauthn),
  [Yubico](https://developers.yubico.com/WebAuthn/Concepts/PRF_Extension/Developers_Guide_to_PRF.html)) → passphrase
  fallback is required.
- P-256 precompile EIP-7951 (Fusaka) supersedes RIP-7212 ([EIP-7951](https://eips.ethereum.org/EIPS/eip-7951),
  [Sigma Prime](https://blog.sigmaprime.io/fusaka-contract-security.html)); EIP-7702 live on Ethereum/OP Stack
  ([ethereum.org](https://ethereum.org/roadmap/pectra/7702/), [Optimism](https://www.optimism.io/blog/optimism-brings-ethereum-s-pectra-upgrade-to-the-superchain)).
- HashKey testnet (133), checked 27 Sep 2026: EntryPoint v0.6/v0.7 deployed, v0.8 not; P-256 precompile at `0x100`
  works; Pimlico bundler unsupported; EIP-7702 untested *[verify]* ([HSK network info](https://docs.hskchain.net/docs/Build-on-HashKey-Chain/network-info)).
- SIWE: [EIP-4361](https://eips.ethereum.org/EIPS/eip-4361).
- Email: Resend 3,000/mo free; Brevo 300/day free; SES US$0.10/1,000 (Sydney region available); SendGrid free plan
  dropped; Postmark free tier *[verify]* ([Brevo](https://www.brevo.com/blog/best-email-api/),
  [Dreamlit](https://dreamlit.ai/blog/best-sendgrid-alternatives), [Tinysend](https://tinysend.co/blog/email-api-pricing-comparison)).
  Pick **Resend** for the testnet MVP (fastest, free tier), **SES ap-southeast-2** for production (AU residency, cost).

### 6.3 Updates, anchoring
- Xero Accounting API Reports (ProfitAndLoss, BalanceSheet); tiered developer pricing from Mar 2026, Starter free with
  5 connections, 1,000 calls/day/org ([reports](https://developer.xero.com/documentation/api/accounting/reports),
  [pricing](https://developer.xero.com/pricing)) — Starter is enough for the pilot.
- QuickBooks ProfitAndLoss ([Intuit](https://developer.intuit.com/app/developer/qbo/docs/api/accounting/report-entities/profitandloss)),
  Stripe balance transactions ([Stripe](https://docs.stripe.com/api/balance_transactions)) *[verify limits]*.
- EAS: on-/off-chain attestations, schema registry, resolvers ([docs](https://docs.attest.org/),
  [contracts](https://github.com/ethereum-attestation-service/eas-contracts)); not on HSK → our own `DisclosureRegistry`
  is the primary anchor; EAS optional.

### 6.4 Dividends and tax
- Superfluid GDA pools ([overview](https://docs.superfluid.org/docs/protocol/distributions/overview)) — rejected for
  now (not on our chains; conflicts with transfer restrictions).
- Merkle distributor pull model ([Uniswap](https://github.com/Uniswap/merkle-distributor)); we push with relayer-paid
  `claimFor` (gas price 0 on BlockID Chain makes push free).
- AUDD issuer AUDC Pty Ltd holds an AFSL (Feb 2026) ([Market Bull](https://themarketbull.com.au/2026/06/26/novatti-on-the-rise-after-cashing-in-1-2m-through-sale-of-partial-stake-in-audc/));
  ASIC class relief for distributors of eligible stablecoins ([ASIC](https://www.asic.gov.au/about-asic/news-centre/news-items/asic-finalises-new-exemptions-to-support-digital-asset-innovation/)).
- Tax: non-resident withholding 30% default/treaty rate on unfranked, franked exempt
  ([ATO](https://www.ato.gov.au/businesses-and-organisations/international-tax-for-business/in-detail/income/withholding-from-dividends-paid-to-foreign-residents));
  TFN not quoted → 47% ([ATO](https://www.ato.gov.au/businesses-and-organisations/hiring-and-paying-your-workers/payg-withholding/payments-you-need-to-withhold-from/withholding-from-investment-income)).

### 6.5 AU legal
- CSF (Part 6D.3A, RG 261): A$5M/12 mo per issuer, A$10k retail per company per 12 mo, 5-day cooling-off, turnover and
  assets < A$25M, AFSL intermediary ([RG 261](https://download.asic.gov.au/media/5702668/rg261-published-19-june-2020-20200727.pdf)).
- s113: Pty ≤ 50 non-employee shareholders (CSF holders excluded) ([AustLII](https://www.austlii.edu.au/cgi-bin/viewdoc/au/legis/cth/consol_act/ca2001172/s113.html)).
- Digital Assets Framework Act 2026: Royal Assent 8 Apr 2026, commences 12 months later (8 or 9 Apr 2027 *[verify]*);
  DAP and TCP licence categories; low-value exemption ([Hall & Wilcox](https://hallandwilcox.com.au/news/digital-assets-reform-passes-18-month-licensing-window-opens-for-platform-operators/),
  [G+T](https://www.gtlaw.com.au/insights/key-topics/regulation-in-motion/australia-passes-highly-anticipated-digital-asset-regulation),
  [APH](https://www.aph.gov.au/Parliamentary_Business/Bills_Legislation/Bills_Search_Results/Result?bId=r7411)).
  `docs/SECURITY.md` says "9 April 2027" — align after verifying.
- ASIC INFO 225 (Oct 2025) + no-action to 30 Jun 2026 (expired); tokenised shares remain securities
  ([25-250MR](https://www.asic.gov.au/about-asic/news-centre/find-a-media-release/2025-releases/25-250mr-updated-asic-guidance-supports-digital-asset-innovation-and-boosts-investor-protection)).

### 6.6 Custody and recovery
- ERC-3643 `recoveryAddress(lost, new, onchainID)` moves balance + frozen amount to a wallet of the same identity;
  `forcedTransfer` skips compliance but the receiver must be verified ([EIP-3643](https://eips.ethereum.org/EIPS/eip-3643),
  [QuillAudits](https://www.quillaudits.com/research/erc-3643-audit-checklist)). Our `BlockIDShareToken.forcedTransfer`
  + `setFrozen` is the testnet equivalent; add a `recover()` wrapper at the ERC-3643 migration.
- A Safe multisig is key management for issuer/agent roles, not a licensed custodian of client assets; custody for
  clients needs an AFSL (TCP/custody authorisation) ([AFSL House](https://afslhouse.com.au/insights/digital-asset-afsl-tokenised-custody/),
  [Hamilton Locke](https://hamiltonlocke.com.au/what-are-australias-digital-asset-custody-requirements/)). Hence our
  default is **self-custody** (holder's device/MetaMask key) + **register recovery**, with a licensed custodian as an
  optional production integration for institutions.
