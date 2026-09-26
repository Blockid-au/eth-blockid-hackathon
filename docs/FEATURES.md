# BlockID Startup Passport: feature gallery

A walkthrough of every feature in the live testnet demo at **https://eth.blockid.au**, plus the BlockID Chain explorer at **https://scan.blockid.au**.

All screenshots come from the live site, taken read-only with Playwright at 1440×900 (desktop) and 390×844 (mobile), both at 2× pixel density. To retake them, run `scripts/screenshots/run.sh`. It needs only Docker. Set `ONLY='^2[2-4]'` to retake just a subset.

Screenshots were captured on 26 Sep 2026, when the platform had **10 companies tokenised and anchored on 3 chains
(30 share-token contracts, A$5.63B marked valuation, `/verify` 10 / 10)**. Some fixes landed after capture (for
example the valuation range spread); the captions note where the current app differs.

> Testnet demo. Marks are SVI-derived values, not market prices, and nothing here is an offer of securities.

---

## 1. Landing page

**What it does:** It explains the product in one screen. You paste a website, AI agents research and value the company, a person approves, and the shares are issued as tokens with proofs anchored on-chain. The mock card on the right plays through the Research → Value → Issue → Anchor flow.
**Why it matters:** A founder learns the whole promise ("valued by AI, approved by people, proven on-chain") before signing in.
**URL:** https://eth.blockid.au/

![Home hero (EN)](screenshots/01-home-hero.png)
*The hero, with the primary call to action and a sample passport card.*

### Bilingual UI (EN / VI)

The flag toggle in the header switches the whole interface between English and Vietnamese on the client side. Numbers and dates follow the selected locale, for example `A$2,4 tr`.

![Home hero (VI)](screenshots/02-home-hero-vi.png)
*The same hero after clicking the VI flag.*

### How it works

The diagram shows the trust boundary. The AI agents are read-only and hold no keys. The gold arrow is an admin signature, and the dashed box is the issuer service, the only component that can sign transactions.

![How it works diagram](screenshots/03-home-how-it-works.png)
*"Agents propose. Humans approve. Chains prove."*

![Eight-step walkthrough](screenshots/04-home-walkthrough.png)
*The eight steps from website to wallet. Gold steps need an admin approval.*

### Live platform stats

Stats are read live from the BlockID API: companies tokenized, total valuation, token contracts, and the most recently tokenized companies with their grade, 30-day move and sparkline.

![Live stats and recently tokenized](screenshots/05-home-live-stats.png)
*Live platform numbers and recently tokenized companies. Green ▲ is up, red ▼ is down.*

![HashKey strip](screenshots/06-home-hashkey-strip.png)
*A home-page teaser for the HashKey Chain deployment (section 9).*

---

## 2. New valuation wizard

**What it does:** This is step 1 of the 8-step flow. The founder pastes a website and can optionally expand **"Add your numbers"** to enter revenue, growth, margin, customers, raised to date, runway and headcount. The report labels these figures as *self-reported*.
**Why it matters:** A website alone rarely states revenue, so self-reported metrics make the revenue and growth scores meaningful. Each valuation belongs to the wallet that requested it, and there is a limit of 3 per wallet per day.
**URL:** https://eth.blockid.au/new

![New valuation wizard, step 1](screenshots/07-new-wizard-step1.png)
*Step 1 with the optional self-reported metrics section expanded.*

---

## 3. AI valuation report

**What it does:** AI agents read the site, extract a company profile, find competitors, analyse the market with cited sources, score the 7 SVI dimensions and draft a narrative. A fixed formula then produces the index, the grade (A–E) and an A$ valuation range. An admin can adjust AI scores before approving.
**Why it matters:** Every number traces back to a source or a formula, which makes the valuation investor-readable and auditable.
**URL:** `https://eth.blockid.au/v/<valuation-id>` (Airwallex: https://eth.blockid.au/v/275fa4d16186466d, visible to its owner or an admin)

![Agent steps log](screenshots/08-valuation-agent-log.png)
*Step 2, "AI agents at work": each agent reports its result and elapsed time, with running counters for pages, competitors and sources.*

![SVI radar and contribution table](screenshots/09-valuation-radar-contribution.png)
*Step 3: the grade and valuation headline, the SVI radar, and "How the index is built" (score × weight = contribution).*

![Valuation range and competitors](screenshots/10-valuation-range-competitors.png)
*The valuation range with its method line, and the competitors chart and list. None of Airwallex's competitors disclosed capital raised, so the bars are empty; the sample report below shows a filled chart. At capture time a single cited multiple (3.6× / 3.6× / 3.6×) collapsed the range to one point; the formula now widens a single cited multiple to a 0.7×–1.4× range and says so in the method line.*

![Narrative and evidence](screenshots/11-valuation-narrative-evidence.png)
*The analyst narrative and the evidence list: every page the agents fetched and cited, with retrieval time and source type.*

### Agent warnings

When a data source is degraded, for example search was unavailable or few competitors were found, the report shows a warning banner so the reviewer knows which figures are weaker.

![Valuation warnings](screenshots/12-valuation-warnings.png)
*A warning banner on a valuation whose competitors were mostly suggested by the model and then verified.*

### Sample report

A public, example-data passport (Harbourline) shows the full report without signing in.
**URL:** https://eth.blockid.au/v/sample

![Sample report](screenshots/13-sample-report.png)
*The complete sample report: grade B, A$3.36M, radar, contribution table, range, competitor funding chart, narrative and evidence.*

---

## 4. Tokenized companies market

**What it does:** It lists every company issued on BlockID Chain, with grade and SVI, valuation, mark per share, 7-day and 30-day change (▲ green / ▼ red), a 30-day sparkline, holder count and anchor status. The list is searchable and sortable.
**Why it matters:** It gives a single market view of all passports. Marks move only on issuance and on approved SVI revaluations.
**URL:** https://eth.blockid.au/companies

![Companies list](screenshots/14-companies-list.png)
*The companies table with grade chips, coloured 7D/30D changes, sparklines and the anchor column (✓ 3 chains: BlockID, Hoodi, HashKey) for all 10 companies.*

---

## 5. Company page: issuance tracker

**What it does:** It is a live, self-updating tracker for a company's issuance after **one admin approval**. The stages are Submitted → Waiting for admin approval → Issuing on BlockID Chain → Sync to Ethereum Hoodi → Sync to HashKey Chain → Live. Each sub-step links to its transaction.
**Why it matters:** Founders can see exactly where their issuance is and cannot skip the human gate.
**URL:** https://eth.blockid.au/c/ARW · https://eth.blockid.au/c/ART · https://eth.blockid.au/c/EBA (all live)

![ARW tracker and KPIs](screenshots/15-company-arw-tracker-kpis.png)
*Airwallex (ARW) after one admin approval: issued on BlockID Chain (registry, token, distributor, KYC 15/15, shares, report hash), then mirrored and Merkle-anchored on Ethereum Hoodi and HashKey Chain testnet.*

![ARW cap table](screenshots/15b-company-arw-cap-table.png)
*ARW cap table read from BlockID Chain: the three original holders plus twelve anonymised holders (co-founder, funds, strategic investor, angel, advisor, ESOP grantees) added through admin-approved mints.*

![ART cap table](screenshots/15c-company-art-cap-table.png)
*Airtasker (ART) after ten admin-approved mints to server-generated wallets; supply is identical on all three chains (see [DEPLOYMENTS.md](DEPLOYMENTS.md)).*

![EBA tracker and KPIs](screenshots/16-company-eba-tracker-kpis.png)
*EBA fully live: every stage done with transaction links, followed by KPI tiles for valuation, shares, holders and last anchor block.*

---

## 6. Company page: mark chart, cap table, wallets

### Share mark chart with simulated growth

The chart shows the SVI-derived mark per share over time, with events such as issuance and revaluation. The **Show simulated growth** toggle overlays a P10–P90 band from geometric Brownian motion, parameterised by grade. The overlay is clearly labelled SIMULATED and never used in totals.

![Mark chart with simulation](screenshots/17-company-eba-mark-chart-simulated.png)
*The EBA mark chart with "Show simulated growth" on (client-side only).*

### Cap table and ownership

Balances are read straight from BlockID Chain at a given block and shown with an ownership donut.

![Cap table and donut](screenshots/18-company-eba-cap-table.png)
*The on-chain cap table and ownership preview.*

### Contract addresses and MetaMask

The share token on BlockID Chain and its read-only mirrors on Ethereum Hoodi and HashKey Chain testnet each get a card with a QR code, copy and explorer links, and one-click **Add to MetaMask**. The cap-table Merkle root and its anchor transactions appear below the cards.

![Contract address cards](screenshots/19-company-eba-contracts-qr.png)
*Token contract cards with QR codes for BlockID Chain, Hoodi and HashKey.*

![Manual steps and network details](screenshots/20-company-eba-metamask-network.png)
*Manual import steps and network details (RPC, chain ID, currency, explorer) for all three chains.*

### After issuance: rounds, dividends, activity

Owners and admins can model a new round and see the dilution before and after, or plan a pro-rata dividend published as a Merkle root, which holders claim without paying gas. Both create *requests* that need approval. The activity feed lists every on-chain event with its transaction and block.

![Cap table tools](screenshots/21-company-eba-cap-tools.png)
*"Model a new round" with the dilution preview, and "Plan a dividend".*

![Company activity](screenshots/21b-company-eba-activity.png)
*The on-chain activity log: KYC registrations, issuance, anchors and mirror deployments.*

---

## 7. Verify a valuation yourself

**What it does:** The page recomputes the valuation report hash — keccak256 of the canonical report JSON — in your browser (via viem), compares it with the server hash (Python) and with the `valuationReportHash()` stored on each share token on BlockID Chain, Hoodi and HashKey. It also recomputes the SVI index, grade and valuation with the fixed public formula.
**Why it matters:** Anyone can prove the report was not changed after approval, and that no AI is involved in the arithmetic.
**URL:** https://eth.blockid.au/verify/EBA

![Verified](screenshots/22-verify-eba-verified.png)
*The green verified banner, with the browser, server and three on-chain hashes agreeing byte for byte.*

![Fixed formula](screenshots/23-verify-eba-formula.png)
*The fixed formula: Σ score × weight, recomputed against the report, the grade bands and the valuation method.*

### Tamper test

**Tamper test: change one score** edits the report JSON locally. The browser hash then changes, and the page shows a red mismatch against all on-chain records. **Reset** restores the report.

![Tamper mismatch](screenshots/24-verify-eba-tamper-mismatch.png)
*After the tamper test: a red mismatch banner, with the on-chain hashes marked ✗.*

---

## 8. Admin console

**What it does:** One live view of every tokenized company. You can sign in with an admin wallet (SIWE) or with the admin account.
**Why it matters:** This is the human gate. Nothing reaches a chain until an admin reviews and signs.
**URL:** https://eth.blockid.au/admin

![Admin login](screenshots/27-admin-login.png)
*The sign-in card, with MetaMask and Username tabs.*

### Overview

KPI tiles with sparklines, the platform value chart (marked), companies by grade, top movers over 30 days, the tokenized companies table, and a live activity feed.

![Admin overview](screenshots/28-admin-overview.png)
*Overview KPIs, the platform value chart (1M), grades and top movers.*

![Admin overview: companies and activity](screenshots/28b-admin-overview-companies-activity.png)
*The companies table and live activity feed.*

### Approvals

This tab is the queue of companies waiting for issuance approval. Approving runs every chain: BlockID Chain → Ethereum Hoodi → HashKey Chain.

![Approvals](screenshots/29-admin-approvals.png)
*The approvals queue at capture time: a pending dividend plan for SVI. Companies awaiting their one issuance approval, mint requests and valuations appear in the same queue.*

### Companies

This tab lists all companies with per-chain sync chips (✓ BlockID / ✓ Hoodi / ✓ HSK). Selecting a row opens a detail pane with the mark chart, KPIs, the revaluation form and activity.

![Admin company detail](screenshots/30-admin-company-detail.png)
*The companies tab with sync chips (all 10 companies live on BlockID, Hoodi and HashKey) and the EBA detail pane.*

### Issuer wallets

This tab shows the admin and service wallets (issuer and relayer) and lets an admin grant or revoke `ISSUER_ROLE` on-chain.

![Issuer wallets](screenshots/31-admin-issuer-wallets.png)
*The three admin wallets, the issuer and relayer service wallets with their native balances on each chain (BLKD on BlockID Chain, ETH on Hoodi, HSK on HashKey), and wallets approved to issue.*

### Audit log

This tab is an append-only log of every sign-in, valuation request, approval, rejection and re-anchor.

![Audit log](screenshots/32-admin-audit-log.png)
*The audit log.*

---

## 9. HashKey Chain deployment

**What it does:** Every company issued in the live flow is mirrored to HashKey Chain testnet automatically (see the company pages). This page shows the hackathon's full contract set on HashKey Chain testnet (chain 133): agent provenance, KYC identity registry, share token, dividend distributor, payout token and cap-table anchor. Each AI output is hashed and proposed on-chain, a human approver signs, and only then does the issuer execute. The page includes a dividend round with holder claims and every transaction.
**Why it matters:** It proves on a public chain the "AI proposes → human approves → issuer executes" separation of duties.
**URL:** https://eth.blockid.au/hsk

![HashKey contracts and provenance](screenshots/25-hsk-contracts-provenance.png)
*The provenance flow, deployed contracts, roles, and an executed agent proposal.*

![HashKey dividends and transactions](screenshots/26-hsk-dividends-transactions.png)
*The dividend round (Merkle root), holder claims and the transaction list.*

---

## 10. BlockID Chain explorer

**What it does:** A Blockscout explorer for BlockID Chain (chain ID 262626), showing blocks, transactions, tokens and holders.
**Why it matters:** Any issuance or transfer can be checked independently of the BlockID app.
**URL:** https://scan.blockid.au · EBA token: https://scan.blockid.au/token/0x95A5a4b82897087B2c044b653B8e6bd617a58718

![Explorer home](screenshots/33-scan-home.png)
*The explorer home: stats, daily transactions, and the latest blocks and transactions.*

![EBA token holders](screenshots/34-scan-eba-token-holders.png)
*The EBA share token Holders tab, which matches the cap table in the app.*

---

## 11. Mobile

The whole app is responsive. The navigation collapses, and cards and tables stack.

| Home | Company (EBA) | Verify (EBA) |
|---|---|---|
| ![Mobile home](screenshots/35-mobile-home.png) | ![Mobile company](screenshots/36-mobile-company-eba.png) | ![Mobile verify](screenshots/37-mobile-verify-eba.png) |
