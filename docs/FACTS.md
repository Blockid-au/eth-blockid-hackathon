# BlockID Business Passport — canonical facts and messaging

Single source of truth for names, messaging, numbers, chains and flows. README, docs, the web app copy (EN/VI),
the pitch decks and the diagrams must match this file. Live numbers: `GET https://eth.blockid.au/api/v1/platform/stats`.
Last verified: 26 Sep 2026 (after the Canva end-to-end demo run).

## Names

| Use | Value |
|---|---|
| Product | **BlockID Business Passport** (formerly BlockID Startup Passport) |
| Company | Auschain Pty Ltd — ABN 79 659 615 111, ACN 659 615 111, GST-registered (BlockID.au, StartupValueIndex.com); BlockID™ is its unregistered trade mark (use ™, never ®, until registered). Details: [COMPANY.md](COMPANY.md) |
| Team | Do Van Long (co-founder & CEO, 80 %) · Truong Quoc Tuan (co-founder, 20 %) — shares of **BlockID Pty Ltd (to be registered)**; Auschain licenses BlockID™ + IP. Details: [TEAM.md](TEAM.md) |
| First real case | BlockID values itself (`origin = self`, badge "Real — self-assessment"); all other listings are `origin = sample`. See [SELF-VALUATION.md](SELF-VALUATION.md) |
| Platform codename (internal, code/docs only) | BlockID Issuance Studio |
| Valuation framework | Startup Value Index (**SVI**) — 7 weighted dimensions, grades A–E |
| Live app · explorer | https://eth.blockid.au · https://scan.blockid.au |
| Repos | github.com/Blockid-au/eth-blockid-hackathon (hackathon) · github.com/Blockid-au/eth-blockid |

## Messaging

Public copy (landing page, meta tags, decks for investors) follows these rules: simple everyday words, short
sentences, one clear message per line, and buttons that say exactly what happens.

- **Product:** BlockID Business Passport.
- **Hero (H1):** Know the business you invest in. · VI: Hiểu rõ doanh nghiệp bạn đầu tư.
- **Pitch (elevator, owner's words):** BlockID Business Passport gives every shareholder, large or small, a live view
  of the business they own: AI-analysed, human-approved updates and valuations, an on-chain share register as proof
  of ownership, and dividends paid straight to their wallet. · VI: BlockID Business Passport cho mọi cổ đông, dù lớn
  hay nhỏ, một góc nhìn trực tiếp vào doanh nghiệp họ sở hữu: bản cập nhật và định giá do AI phân tích, con người phê
  duyệt, sổ cổ đông trên blockchain làm bằng chứng sở hữu, và cổ tức trả thẳng vào ví.
- **Say "business"**, never "private business", in public copy.
- **Two audiences:** (1) **investors** of every size who check a business before they invest and follow it after;
  (2) **businesses** that want to list and turn their shares into tokens on blockchain. Every investor gets the same
  updates at the same time, in step with how the business grows.
- **The problem (investor pains):** (1) they don't really understand the business; (2) they can't follow it after
  they invest: growth, profit, how their stake grows or gets diluted; (3) they have no clear proof of what they own;
  (4) dividends are slow or never arrive.
- **Pillars (what you get):**
  - **Understand it** — a plain-language profile of the business, every number linked to where it came from.
  - **Follow it** — regular updates (weekly, monthly, quarterly or yearly) with a fair value checked and approved by people.
  - **Own it** — shares recorded in an online share register on blockchain; that record is your proof of ownership.
  - **Get paid** — dividends go straight into your wallet, automatically.
  - **Check it** — anyone can check the numbers and the share register for themselves.
- **For businesses:** list your business on blockchain, with all the information investors need.
- **Home paths (4 steps each):** *For investors* — pick a business or paste its website → read a plain report with a
  fair value approved by a person → hold your shares in your own wallet → get the same updates and dividends as
  every other investor. *For businesses* — paste your website (and, optionally, your numbers) → get a fair value
  approved by a person → set up your shares and shareholders → list on blockchain and update every investor at once.
- **How it works (public, 4 steps):** the business shares its numbers → independent analysis sets a fair value,
  approved by a person → shares are recorded on blockchain and held in your wallet → regular updates and dividends
  to your wallet.
- **CTAs:** primary **"Evaluate a business"** (`/start`) · secondary **"List on blockchain"** (`/start?goal=list`, same
  flow, copy tuned to listing shares). VI: "Đánh giá doanh nghiệp" · "Niêm yết trên blockchain". No "Try it now"
  button: the shared demo account opens by itself on the first visit, shown as a small "You're in the demo account" chip.
- **Founder flow in plain words:** phases **Evaluate** (1 Website · 2 Research · 3 Valuation) → **Set up shares**
  (4 Share code · 5 Shareholders) → **List on blockchain** (6 Create shares · 7 Copy to public chains · 8 Add to
  wallet). The report says "Business score" (not SVI). Technical names stay on `/verify`, `/hsk` and admin.
- **Status, not warnings:** one slim status bar (status · step n of 8 · elapsed · next action) at the top of the
  valuation, company and portfolio screens; research notes sit in a collapsed "Notes (n)" at the end of the report.
- **Who buys:** investors (retail and professional) in private businesses; founders & SMEs raising from them
  (Australia, Vietnam); accelerators & VCs; licensed crowd-sourced-funding intermediaries and transfer agents;
  RWA ecosystems (HashKey Chain).
- **Revenue:** issuance fee · cap-table SaaS · transfer-agent fee per transfer · 0.5–1% of dividend rounds ·
  custody via licensed partner.
- **Legal line (always shown):** Testnet demo. Not an offer of securities or financial advice.
- **Internal / technical tagline (engineering docs and hackathon judging only, not public landing copy):**
  Agents propose. Humans approve. Chains prove. The valuation framework is still called SVI internally.

## How it works (canonical flow)

1. **Founder** pastes a website (checked first: syntax, look-alike `xn--` hosts with a "Did you mean …?" hint,
   DNS and the homepage via `POST /v1/studio/check-url`; optional self-reported revenue figures) and later enters shareholders
   (name, wallet, %). Default issue price **A$1.00 per share** → shares = approved valuation ÷ 1.
2. **AI agents (no keys):** read the public site (≤ 6 pages, SSRF-safe) → competitor discovery (≤ **3 web searches**
   per valuation: competitors, market, company financials; Brave → Claude web-search bridge; model-suggested
   competitors verified by fetching their homepage) → market analysis (only fetched, cited sources; the company's
   own revenue/ARR, funding and last valuation kept only with a verbatim quote that states the number, converted
   to AUD at a fixed dated FX table) → **SVI** (LLM scores 5 qualitative dimensions; code computes revenue &
   growth; revenue precedence self-reported > website > cited source, a cited figure is flagged with a warning;
   fixed weights; range = revenue × multiple × SVI factor, multiple = implied from the cited last round
   (valuation ÷ revenue, 0.5×–40×, range 0.7×–1.4×) → else cited market multiple (single → 0.7×–1.4×) → else
   uncalibrated default table (2.0/3.5/6.0×; SaaS/fintech 3/6/10×, flagged for review); stage range only when
   revenue is 0).
   LLM chain: SambaNova → Claude CLI bridge → DeepInfra.
3. **Human gate:** an admin (MetaMask SIWE on the admin list, or admin account) approves the valuation, then gives
   **one issuance approval**.
4. **Issuer (only key holder, isolated network):** creates the register on **BlockID EVM** (IdentityRegistry, BlockIDShareToken,
   DividendDistributor; KYC each holder; gas drip; issue; `anchorValuation(reportHash)`), then automatically syncs
   **Ethereum Hoodi** and **HashKey Chain testnet** (paused mirror token with the same balances + cap-table Merkle root
   in `CapTableAnchor`). Per-chain status; admin can re-sync a failed chain.
5. **Proof:** live issuance tracker; contract-address cards with QR + Add-to-MetaMask on all three chains;
   `/verify/:ticker` recomputes keccak256 of the canonical report JSON in the browser and compares it with
   `valuationReportHash()` on all three chains; public explorer.
6. **After issuance:** mint (dilution preview), Merkle dividends in mAUD with relayer `claimFor` (holders pay no gas),
   revaluations (mark = valuation ÷ shares; simulated growth is labelled and never counted), admin dashboard.

## App screens (canonical navigation)

Every feature is its own screen with its own URL, a left rail and a previous / next pager. Source of truth in code:
`web/app/src/lib/flow.ts`.

| Area | Screens (URL) | Order |
|---|---|---|
| Founder flow | 1 Website `/start` (`?goal=list`, `?url=`) · 2 Research `/v/:id/research` · 3 Valuation `/v/:id/report` · ◆ gate 1 · 4 Share code `/v/:id/ticker` · 5 Shareholders `/v/:id/holders` · ◆ gate 2 · 6 Create shares `/c/:tk/issue` · 7 Copy to public chains `/c/:tk/sync` · 8 Add to wallet `/c/:tk/wallet` | Phases: **Evaluate** (1–3), **Set up shares** (4–5), **List on blockchain** (6–8) |
| Company workspace | `/c/:tk/overview` · `cap-table` · `transfers` · `mint` ◆ · `dividends` ◆ · `activity` · `team` · `/verify/:tk` | After step 8 |
| Admin console | `/admin` inbox · `/admin/dashboard` · queues in flow order: 1 `valuations` ◆ · 2 `issuance` ◆ · 3 `sync` · 4 `mints` ◆ · 5 `dividends` ◆ · 6 `transfers` · registry `companies`, `wallets` · `audit` | One item per screen: `/admin/<queue>/<item>` |

◆ = a person must approve. A gate link opens the exact admin item with `?return=<founder step>`; after approval the
admin lands back on the founder's next step. Old URLs (`/new`, `/v/:id`, `/c/:tk`, `/admin`) still work.

## Chains

| Chain | Chain id | Role | Explorer |
|---|---|---|---|
| BlockID EVM (Cosmos EVM, gas price 0) | 262626 | Register of record | https://scan.blockid.au |
| Ethereum Hoodi testnet | 560048 | Public anchor: paused mirror + `CapTableAnchor` root | https://hoodi.etherscan.io |
| HashKey Chain testnet | 133 | RWA stack + `AgentProvenance` + paused mirror + root | https://testnet-explorer.hskchain.net |

Platform contracts: `CapTableAnchor` Hoodi `0xF3dC95D5d207dE9f2aC98184Fd32b45B72334263` ·
`CapTableAnchor` HashKey `0x728c834DE493DC3e9Ae2f7C0e79d86701B6F9F04` · `AgentProvenance` HashKey
`0x6B96bcE8937e1416Ec1DAC4ADAdD71FE879F8e84` · `DemoAUD` (mAUD) BlockID `0x286C1eD22A741F4939A3C7637011B0fAE2C7FFBc`.

Wallets: issuer `0x2567Bb502ac840cF93957C60A410160a8cCb5ddf` · relayer `0x1B43f0d3297F79cE6c8BbA12F4FadFBE9112DA4a` ·
admins `0xc309691C60957A55bB619383A06d3F69A94f4585`, `0xC40052702B48631C26AD7c88b499bF230faCa21F`,
`0x02B148f774Bd35B8753Ea6A17895931eD9201E2F`.

Worked example — **EBA (ETH BlockID Australia)**: BlockID `0x95A5a4b82897087B2c044b653B8e6bd617a58718` ·
Hoodi `0x1a305fdD461002BD6136476A69F3a268F79aAb3b` · HashKey `0x041Eb1B727c4cdDfc8D46f1fBCb812E1c94fbc90` ·
report hash `0xa1466362b035ecc804caf101986edc4de73697cacf54547226317616c3a73e33`.

## Live results (27 Sep 2026)

> **About the data:** the listed companies are **sample listings** built from public information (e.g. Canva,
> Airwallex) to run the full flow on testnet. They are not customers or partners, and their holders, updates and
> offerings are sample data. There are no real users yet; real pilots will be added here as they sign up.


| Metric | Value |
|---|---|
| Sample listings tokenised (all anchored on 3 chains) | **14** — CNV, ARW, GAA, SFT, MOM, ART, BVN, EHE, AST, DPT, SVI, VBC, BLC, EBA |
| Share-token contracts | **42** (14 companies × BlockID + Hoodi + HashKey) |
| Marked valuation | **A$87.1B** (median A$66.0M) |
| `/verify` | **14 / 14** companies match on all three chains |
| Automated tests | **378** — 341 backend (pytest, incl. Postgres flows) + 37 contracts (Foundry) |
| Docs | 12 architecture diagrams · 39-screen feature gallery · 3-minute pitch deck |

When numbers change, update this table first, then README "Results", the decks and FEATURES.md.

## Terms to avoid / replace

| Avoid | Use |
|---|---|
| "Sepolia" for our anchor | Ethereum **Hoodi** (current Ethereum testnet) |
| "two approval gates" (issue, then anchor) | **one issuance approval**; `approve-anchor` = re-sync only |
| `keccak(valuation id)` as the anchored hash | keccak256 of the **canonical report JSON** (`studio/report_hash.py`) |
| "Issuance Studio" or "Startup Passport" in user-facing copy | **BlockID Business Passport** |
| "returns", "yield", "guaranteed", "earn", any promise of gains | plain facts: fair value, updates, dividends paid; always the legal line. "invest" / "investor" are allowed |
| "N businesses listed", "real companies", "users", "customers" for the demo data | "**N sample listings** (built from public information, not customers)"; say "no real users yet" until pilots sign up. Real pilots are counted separately once they exist |
| "offer" of shares to the public (except "not an offer" in the legal line) | "list your business", "businesses can offer shares with all the information investors need" (demo context) |
| "AI", "agent", "LLM", "model" in public marketing copy (exception: "AI-analysed" is allowed in the elevator pitch only) | independent analysis, checked, regular updates |
| Jargon on public pages: SVI, Merkle, issuer, mirror, anchor, relayer, "agents propose", four-eyes, ERC-3643, Hoodi, HashKey, SIWE, mAUD, gate, provenance | plain words: fair value, share register, recorded on blockchain, approved by a person, check the records. Technical names stay in docs, `/verify` and `/hsk` |
