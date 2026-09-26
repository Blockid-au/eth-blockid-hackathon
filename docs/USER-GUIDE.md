# BlockID Startup Passport: user guide

> **Testnet only. Not an offer of securities.** Every token, balance and dividend in this guide lives on test
> networks and has no monetary value.

This guide walks through the platform task by task, with screenshots from the live app at
**https://eth.blockid.au**. For a screen-by-screen tour see [FEATURES.md](FEATURES.md); for every contract address
see [DEPLOYMENTS.md](DEPLOYMENTS.md).

**Contents**

1. [Before you start](#1-before-you-start)
2. [Value a startup](#2-value-a-startup)
3. [Tokenise the company](#3-tokenise-the-company)
4. [Admin: approve, issue, sync](#4-admin-approve-issue-sync)
5. [Shareholders: see and hold your shares](#5-shareholders-see-and-hold-your-shares)
6. [Issue new shares (a new round)](#6-issue-new-shares-a-new-round)
7. [Pay a dividend](#7-pay-a-dividend)
8. [Transfers and KYC](#8-transfers-and-kyc)
9. [Verify a valuation yourself](#9-verify-a-valuation-yourself)
10. [Explorers and HashKey Chain](#10-explorers-and-hashkey-chain)
11. [Operators: keeping everything in sync](#11-operators-keeping-everything-in-sync)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Before you start

### Roles

| Role | What they do | How they sign in |
|---|---|---|
| **Founder / requester** | Requests a valuation, proposes the ticker and cap table, requests mints and dividends | MetaMask (Sign-In with Ethereum) |
| **Admin** | Reviews AI scores, approves issuance, mints, dividends, transfers and KYC | Admin wallet (MetaMask) or the admin account |
| **Shareholder / investor** | Holds shares, imports the token, claims dividends, requests transfers | MetaMask |
| **Anyone** | Browses companies, verifies valuations, reads the explorers | No sign-in |

AI agents never hold keys. Only the isolated **issuer service** signs transactions, and only for rows an admin has
approved.

### Networks

| Network | Chain ID | RPC | Currency | Explorer | Role |
|---|---|---|---|---|---|
| BlockID Chain | 262626 (`0x401e2`) | `https://eth.blockid.au/rpc` | BLKD (18 decimals) | https://scan.blockid.au | register of record; zero gas price |
| Ethereum Hoodi | 560048 | `https://ethereum-hoodi-rpc.publicnode.com` | ETH | https://hoodi.etherscan.io | paused mirror + Merkle anchor |
| HashKey Chain testnet | 133 | `https://testnet.hsk.xyz` | HSK | https://testnet-explorer.hskchain.net | paused mirror + Merkle anchor, `AgentProvenance` |

The company page adds BlockID Chain to MetaMask for you (section 5). BlockID Chain transactions cost **0 gas**.

### Language

Use the **EN / VI** switch in the header. Everything, including the valuation report, is available in both.

![Home in English](screenshots/01-home-hero.png)
![Home in Vietnamese](screenshots/02-home-hero-vi.png)

---

## 2. Value a startup

**Where:** https://eth.blockid.au/new · **Who:** anyone with a wallet (3 valuations per wallet per day).

1. Click **Connect wallet** and sign the login message in MetaMask (no transaction, no gas).
2. Paste the company's public website, for example `https://www.airwallex.com/`, and optionally add
   self-reported metrics (revenue, growth, customers). Self-reported numbers are labelled *not verified*.
3. Start the valuation. The agents read the site, find competitors, search the market and score the company.
   It takes about 1–3 minutes; the page updates by itself.

![New valuation wizard](screenshots/07-new-wizard-step1.png)

While it runs you see the agent log: each step, how many searches it used and which sources it read.

![Agent log](screenshots/08-valuation-agent-log.png)

### Read the report

- **SVI index and grade (A–E)** with a contribution chart for the 7 dimensions (Founder, Product, Market, Revenue,
  Growth, Investment readiness, Trust). Revenue and growth are computed by code; the other five are
  **AI-suggested** and must be confirmed by an admin.
- **Valuation range** (low / mid / high, A$) and the competitors that were found.
- **Narrative and evidence**: every claim links to a fetched source. Uncited claims are dropped automatically.
- **Warnings**: what the agent could not verify (for example "no public revenue").

![Radar and contributions](screenshots/09-valuation-radar-contribution.png)
![Range and competitors](screenshots/10-valuation-range-competitors.png)
![Narrative and evidence](screenshots/11-valuation-narrative-evidence.png)
![Warnings](screenshots/12-valuation-warnings.png)

A public sample report is at https://eth.blockid.au/v/sample.

> The valuation is an indicative index, not financial advice. Companies that publish no revenue get a low score
> by design; the admin can adjust the five qualitative scores before approving.

---

## 3. Tokenise the company

**Where:** the valuation page, after an admin has approved the valuation · **Who:** the requester or an admin.

1. Click **Continue to ticker**. Pick a 3-letter ticker (suggestions are shown) and a share price. The default
   is *valuation mid ÷ A$1.00* shares.
2. Build the cap table: **Add holder** for each holder (name + wallet). Wallets must be valid EIP-55 addresses and
   percentages must add up to 100%.
3. Click **Create & submit for approval**. The company page opens with the **issuance tracker**.

The tracker shows six stages: Submitted → Waiting for admin approval → Issuing on BlockID Chain → Sync to
Ethereum Hoodi → Sync to HashKey Chain → Live. Each sub-step links to its transaction.

![Issuance tracker, all chains synced](screenshots/15-company-arw-tracker-kpis.png)

---

## 4. Admin: approve, issue, sync

**Where:** https://eth.blockid.au/admin · **Who:** wallets on the admin list, or the admin account.

![Admin login](screenshots/27-admin-login.png)

### Overview

KPIs, service-wallet balances on all three chains, tokenised companies and recent activity.

![Admin overview](screenshots/28-admin-overview.png)
![Companies and activity](screenshots/28b-admin-overview-companies-activity.png)

### Approvals

One queue for everything that needs a human: valuations, issuance, mints, dividends, transfers and KYC.

| Item | What approving does |
|---|---|
| **Valuation** | Opens the report's *Admin review*: adjust any AI score, preview the new index, then approve or **Reject valuation** |
| **Issuance** | One approval: the issuer deploys the identity registry, share token and dividend distributor on BlockID Chain, KYCs every holder, issues the shares, anchors the report hash, then mirrors to Hoodi and HashKey and anchors the cap-table Merkle root |
| **Mint** | KYC for the new holder, mint on BlockID Chain, re-sync both mirrors and re-anchor (~80 s) |
| **Dividend** | Funds a Merkle round in the distributor; holders claim, the relayer pays their gas |
| **Transfer** (approval mode) | The issuer executes `forcedTransfer` after checking KYC and limits |
| **KYC** | Registers the wallet in the company's identity registry |

![Approvals](screenshots/29-admin-approvals.png)

The issuer runs **one job at a time**. Bulk approvals are safe: they queue and run in order.

### Companies, issuer wallets and audit

- **Companies:** pick a row to see its mark chart and sync state per chain, **Revalue** it, or **Re-sync missing chains**.
- **Issuer wallets:** grant or revoke wallets that may submit companies.
- **Audit log:** every login, approval and issuer action, hash-chained.

![Company detail](screenshots/30-admin-company-detail.png)
![Issuer wallets](screenshots/31-admin-issuer-wallets.png)
![Audit log](screenshots/32-admin-audit-log.png)

---

## 5. Shareholders: see and hold your shares

**Where:** https://eth.blockid.au/companies and `https://eth.blockid.au/c/<TICKER>`.

![Companies](screenshots/14-companies-list.png)

On the company page:

- **KPIs**: valuation, shares outstanding, holders (all KYC-verified), last anchor block.
- **Cap table**: balances are read live from BlockID Chain, with an ownership chart.
- **Contract addresses** on all three chains, with QR codes and explorer links.

![KPIs](screenshots/16-company-eba-tracker-kpis.png)
![Cap table](screenshots/18-company-eba-cap-table.png)
![Contracts and QR codes](screenshots/19-company-eba-contracts-qr.png)

### Add the token to MetaMask

1. Click **Add to MetaMask** on the BlockID Chain card. MetaMask asks to add the network (chain 262626, BLKD) and
   then the token.
2. Or add it manually: network values from section 1, then **Tokens → Import tokens** with the contract address.

![Add network and token](screenshots/20-company-eba-metamask-network.png)

Mirrors on Hoodi and HashKey are **paused** read-only copies; the live, transferable token is on BlockID Chain.

---

## 6. Issue new shares (a new round)

**Where:** company page → **Model a new round** · **Who:** the company owner wallet or an admin.

1. Enter the **recipient wallet**, a **holder name** (anonymised labels such as `Seed investor 01` are fine) and the
   number of **new shares**. The preview shows the dilution for existing holders.
2. Send the request. It appears in the admin **Approvals** queue as a mint.
3. After approval, the new holder appears in the cap table and the supply updates on all three chains.

![Cap tools](screenshots/21-company-eba-cap-tools.png)

Example: Airtasker (ART) after ten approved mints to anonymised holders.

![ART cap table](screenshots/15c-company-art-cap-table.png)

And Airwallex (ARW): three original holders plus twelve anonymised holders.

![ARW cap table](screenshots/15b-company-arw-cap-table.png)

---

## 7. Pay a dividend

**Where:** company page → **Plan a dividend** · **Who:** owner or admin; an admin approves.

1. Enter the **Total (mAUD)**. The server snapshots balances at the record block, splits pro rata (rounded down;
   the remainder stays with the issuer) and computes a Merkle root. The claim deadline is 30 days.
2. After approval, holders claim their share; the relayer pays their gas (`claimFor`).
3. The activity feed shows every round and claim.

![Activity](screenshots/21b-company-eba-activity.png)

---

## 8. Transfers and KYC

Every receiver must be KYC-verified in the company's identity registry. Each company has a transfer mode, set by an
admin:

| Mode | Token state | How a holder transfers |
|---|---|---|
| **Admin approval required** (default) | paused | Sign in with the holding wallet, open **Transfer shares**, enter **Receiver wallet** and **Receiver name**, then **Submit for approval**; an admin approves and the issuer runs `forcedTransfer` |
| **Free transfer** | unpaused | Same panel, **Sign transfer in MetaMask**; the app records the tx hash and re-syncs the register and mirrors |

The panel checks the transfer first (KYC, lock-up, frozen wallet, shareholder cap, balance) and explains any problem,
for example *Receiver is not KYC-verified*. A new investor clicks **Request KYC** for their wallet on the company
page; an admin approves it in the queue. **Transfer history** lists every transfer.

---

## 9. Verify a valuation yourself

**Where:** `https://eth.blockid.au/verify/<TICKER>` · **Who:** anyone, no sign-in.

The page recomputes the SVI index and the report hash **in your browser** from the published formula, then compares
the hash with the value anchored on BlockID Chain, Hoodi and HashKey.

![Verified on three chains](screenshots/22-verify-eba-verified.png)
![The formula](screenshots/23-verify-eba-formula.png)

**Tamper test:** change one score and the hash no longer matches.

![Tamper test](screenshots/24-verify-eba-tamper-mismatch.png)

---

## 10. Explorers and HashKey Chain

- **BlockID explorer** (Blockscout): https://scan.blockid.au. Search a token address, then open **Holders**.
- **HashKey page**: https://eth.blockid.au/hsk shows the HashKey testnet contracts, `AgentProvenance` (four-eyes
  record of agent actions) and dividend transactions.

![Explorer](screenshots/33-scan-home.png)
![Token holders](screenshots/34-scan-eba-token-holders.png)
![HashKey contracts](screenshots/25-hsk-contracts-provenance.png)
![HashKey dividends](screenshots/26-hsk-dividends-transactions.png)

The app also works on phones:

<p>
  <img src="screenshots/35-mobile-home.png" width="30%" alt="Mobile home">
  <img src="screenshots/36-mobile-company-eba.png" width="30%" alt="Mobile company">
  <img src="screenshots/37-mobile-verify-eba.png" width="30%" alt="Mobile verify">
</p>

---

## 11. Operators: keeping everything in sync

Run these on the app VM from the repository root. Details: [RUNBOOK-STUDIO.md](RUNBOOK-STUDIO.md).

| Task | Command |
|---|---|
| Regenerate the token / contract list (reads Postgres + all three chains) | `agents/.venv/bin/python scripts/export-deployments.py` → [DEPLOYMENTS.md](DEPLOYMENTS.md) |
| Retake every screenshot (read-only tour, Docker) | `scripts/screenshots/run.sh` (subset: `ONLY='^1[5-8]' scripts/screenshots/run.sh`) |
| Change the LLM order | edit `LLM_PROVIDER_ORDER`, `SAMBANOVA_MODELS`, `DEEPINFRA_MODELS` in `/opt/blockid/app.env`, then recreate `agents-worker` ([LLM-ROUTING.md](LLM-ROUTING.md)) |
| Restart the Claude search / completion bridge | `sudo systemctl restart claude-search-bridge` (health: `curl http://172.18.0.1:8765/healthz`) |
| Check BlockID Chain gas | `cast gas-price --rpc-url http://127.0.0.1:8545` (0) and `curl 127.0.0.1:1317/cosmos/evm/feemarket/v1/params` |

Demo holder wallets created on the server live in `~/.blockid/holder-wallets/` as encrypted Foundry keystores
(`ART/`, `ARW/`, `password`, `index.tsv` with label → address). They are never in the repository.

---

## 12. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| "Daily limit reached" on /new | 3 valuations per wallet per day. Use another wallet or ask an admin. |
| Valuation shows "no market data" | Brave quota exhausted; search falls back to Claude web search automatically. If both fail the valuation still completes with a warning. |
| Low SVI for a well-known company | Revenue and growth come from published numbers only. Add self-reported metrics or let the admin adjust scores. |
| Issuance or mint seems stuck | The issuer runs one job at a time; check the tracker's "Now:" line and the admin overview. Failed chains can be retried with **Re-sync missing chains**. |
| MetaMask shows a token on Hoodi/HashKey you cannot send | Mirrors are paused by design; transfer on BlockID Chain. |
| MetaMask asks for gas on BlockID Chain | Set the gas price to 0; BLKD fees are zero. |
