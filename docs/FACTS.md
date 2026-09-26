# BlockID Startup Passport — canonical facts and messaging

Single source of truth for names, messaging, numbers, chains and flows. README, docs, the web app copy (EN/VI),
the pitch decks and the diagrams must match this file. Live numbers: `GET https://eth.blockid.au/api/v1/platform/stats`.
Last verified: 26 Sep 2026 (after the Canva end-to-end demo run).

## Names

| Use | Value |
|---|---|
| Product | **BlockID Startup Passport** |
| Company | Auschain Pty Ltd (BlockID.au, StartupValueIndex.com) |
| Platform codename (internal, code/docs only) | BlockID Issuance Studio |
| Valuation framework | Startup Value Index (**SVI**) — 7 weighted dimensions, grades A–E |
| Live app · explorer | https://eth.blockid.au · https://scan.blockid.au |
| Repos | github.com/Blockid-au/eth-blockid-hackathon (hackathon) · github.com/Blockid-au/eth-blockid |

## Messaging

- **Tagline:** Agents propose. Humans approve. Chains prove.
- **Hero (H1):** Know what your startup is worth, and who owns it.
- **Sub-headline:** Give your startup a passport: valued by AI, approved by people, proven on-chain.
- **Elevator pitch (≤ 40 words):** BlockID turns your company website into an evidence-cited valuation in minutes, then
  turns your shareholder list into a verified, KYC-gated cap table you can grow and pay dividends from — on-chain,
  with AI that never holds the keys.
- **Why:** startup equity lives in spreadsheets; early valuations are slow, costly and unsourced; shareholders
  cannot verify ownership.
- **Who buys:** founders & SMEs (Australia, Vietnam); accelerators & VCs; licensed crowd-sourced-funding
  intermediaries and transfer agents; RWA ecosystems (HashKey Chain).
- **Revenue:** issuance fee · cap-table SaaS · transfer-agent fee per transfer · 0.5–1% of dividend rounds ·
  custody via licensed partner.
- **Legal line (always shown):** Testnet demo. Not an offer of securities.

## How it works (canonical flow)

1. **Founder** pastes a website (optional self-reported revenue figures) and later enters shareholders
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

## Live results (26 Sep 2026)

| Metric | Value |
|---|---|
| Companies tokenised (all anchored on 3 chains) | **12** — CNV, ARW, GAA, SFT, MOM, ART, BVN, EHE, DPT, SVI, VBC, EBA |
| Share-token contracts | **36** (12 companies × BlockID + Hoodi + HashKey) |
| Marked valuation | **A$87.0B** (median A$71.1M) |
| `/verify` | **12 / 12** companies match on all three chains |
| Automated tests | **180** — 143 backend (pytest, incl. Postgres flows) + 37 contracts (Foundry) |
| Docs | 12 architecture diagrams · 39-screen feature gallery · 3-minute pitch deck |

When numbers change, update this table first, then README "Results", the decks and FEATURES.md.

## Terms to avoid / replace

| Avoid | Use |
|---|---|
| "Sepolia" for our anchor | Ethereum **Hoodi** (current Ethereum testnet) |
| "two approval gates" (issue, then anchor) | **one issuance approval**; `approve-anchor` = re-sync only |
| `keccak(valuation id)` as the anchored hash | keccak256 of the **canonical report JSON** (`studio/report_hash.py`) |
| "Issuance Studio" in user-facing copy | **BlockID Startup Passport** |
| "investment", "returns", "offer" in marketing copy | valuation, cap table, share register; always the legal line |
