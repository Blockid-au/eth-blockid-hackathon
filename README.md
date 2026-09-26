# BlockID Startup Passport

![BlockID Startup Passport](docs/images/banner.png)

### Agents propose. Humans approve. Chains prove.

## Know what your startup is worth, and who owns it.

**Give your startup a passport: valued by AI, approved by people, proven on-chain.**

BlockID turns your company website into an evidence-cited valuation in minutes, then turns your shareholder list
into a verified, KYC-gated cap table you can grow and pay dividends from — on-chain, with AI that never holds the
keys.

| | |
|---|---|
| Live app | https://eth.blockid.au |
| Verify any company (browser-side hash check) | https://eth.blockid.au/verify/EBA |
| BlockID EVM explorer (Blockscout) | https://scan.blockid.au |
| HashKey Chain page | https://eth.blockid.au/hsk |
| Pitch deck (3 min) | [PDF](https://eth.blockid.au/deck/BlockID-Startup-Passport-3min.pdf) · [PPTX](https://eth.blockid.au/deck/BlockID-Startup-Passport-3min.pptx) |
| Demo video (59 s) | [docs/video/blockid-startup-passport-demo.mp4](docs/video/blockid-startup-passport-demo.mp4) · https://eth.blockid.au/demo.mp4 |
| Hackathon write-up · demo script | [docs/HACKATHON.md](docs/HACKATHON.md) · [docs/DEMO.md](docs/DEMO.md) |

> **Testnet demo. Not an offer of securities.**

## Results (live, 26 Sep 2026)

| Metric | Value |
|---|---|
| Companies tokenised, all anchored on 3 chains | **12** — CNV, ARW, GAA, SFT, MOM, ART, BVN, EHE, DPT, SVI, VBC, EBA |
| Share-token contracts | **36** (12 companies × BlockID EVM + Ethereum Hoodi + HashKey Chain) |
| Marked valuation | **A$87.0B** (median A$71.1M) |
| [`/verify`](https://eth.blockid.au/verify/EBA) | **12 / 12** companies match on all three chains |
| Automated tests | **180** — 143 backend (pytest, incl. Postgres flows) + 37 contracts (Foundry) |
| Docs | 12 architecture diagrams · 39-screen feature gallery · 3-minute pitch deck |

Live numbers: `GET https://eth.blockid.au/api/v1/platform/stats`. Every token and contract, with supply checked
on-chain: [docs/DEPLOYMENTS.md](docs/DEPLOYMENTS.md). Platform contracts: `CapTableAnchor` on
[Hoodi](https://hoodi.etherscan.io/address/0xF3dC95D5d207dE9f2aC98184Fd32b45B72334263) and
[HashKey](https://testnet-explorer.hskchain.net/address/0x728c834DE493DC3e9Ae2f7C0e79d86701B6F9F04),
`AgentProvenance` on [HashKey](https://testnet-explorer.hskchain.net/address/0x6B96bcE8937e1416Ec1DAC4ADAdD71FE879F8e84).

## Hackathon tracks (EAG Global Buildathon, Sydney)

1. **Sydney Hackathon — AI x Ethereum & Agent Economy.** Agent identity, permissioned agent execution, safe
   execution policies and AI-generated content provenance: agents hold no keys, their permissions are enforced in
   code (`policy.py`), each AI output is registered on-chain by content hash in `AgentProvenance`, a *different*
   human wallet approves it (four-eyes), and only approved proposals can be marked executed.
2. **Real-World Ethereum Applications.** A live product for a real problem: startup valuations and share
   registers, with the cap table anchored on Ethereum Hoodi and a public `/verify` page anyone can use.
3. **HashKey Chain (RWA / AI Agents).** Every issued company is synced to **HashKey Chain testnet (chain id 133)**
   (paused mirror token + cap-table Merkle root), and the full RWA stack — permissioned share token (ERC-3643
   style), identity registry, Merkle dividend distributor with gasless claims, cap-table anchor and
   `AgentProvenance` — is deployed there by `scripts/hsk-demo.sh`.

See [docs/HACKATHON.md](docs/HACKATHON.md) for how the build maps to each judging criterion.

![The problem it solves](docs/images/problem.png)

## The problem

Small companies and startups — in Australia, Vietnam and other emerging markets — cannot cheaply:

- get an **independent, evidence-backed valuation**;
- run a **compliant share register** (cap tables live in spreadsheets and email threads);
- **pay dividends** to many small shareholders without heavy admin and bank fees.

Tokenisation fixes the register and the payouts, and AI can do the valuation research — but handing an AI agent
the keys to a company's equity is unacceptable. BlockID's answer: **AI proposes, code computes, humans approve,
an isolated issuer signs, and every step is verifiable on-chain.**

## How it works

1. **Founder** pastes a website (optional self-reported revenue figures), later enters shareholders (name, wallet,
   %). Default issue price **A$1.00 per share**: shares = approved valuation ÷ 1.
2. **AI agents (no keys)** read the public site (≤ 6 pages, SSRF-safe), discover competitors (≤ 3 web searches per
   valuation: Brave → Claude web-search bridge; model-suggested competitors verified by fetching their homepage),
   analyse the market from fetched, cited sources only and score the **SVI**. LLM chain: SambaNova → Claude CLI
   bridge → DeepInfra.
3. **Human gate:** an admin (MetaMask SIWE on the admin list, or the admin account) approves the valuation, then
   gives **one issuance approval**.
4. **Issuer** (only key holder, isolated network) creates the register on **BlockID EVM**, then automatically
   syncs **Ethereum Hoodi** and **HashKey Chain testnet** (paused mirror token with the same balances + cap-table
   Merkle root in `CapTableAnchor`). Per-chain status; an admin can re-sync a failed chain.
5. **Proof:** live issuance tracker, contract cards with QR + Add-to-MetaMask on all three chains, and
   `/verify/:ticker`, which recomputes keccak256 of the canonical report JSON in your browser and compares it with
   `valuationReportHash()` on all three chains.
6. **After issuance:** mints (dilution preview), Merkle dividends in mAUD with relayer `claimFor` (holders pay no
   gas), revaluations — each behind an admin approval.

![How it works — architecture](docs/images/architecture.png)

## Features

- **AI valuation (SVI — Startup Value Index).** Paste a website; a LangGraph pipeline crawls the public site
  (SSRF-safe fetcher), extracts a profile, discovers competitors (3-search budget), builds a cited market view and
  scores 7 dimensions (Founder 20%, Product 15%, Market 20%, Revenue 20%, Growth 10%, Investment Readiness 10%, Trust 5%).
  Revenue/growth maths is deterministic code; the LLM only *suggests* qualitative scores, each labelled
  `computed | ai_suggested | self_reported | human`. Every claim cites a fetched source URL. Range = revenue ×
  cited multiple × SVI factor (a single cited multiple gives a 0.7×–1.4× spread), or a stage range; grades A–E.
- **Human approval.** The valuation pauses at a LangGraph `interrupt()`; an admin approves or overrides scores.
  Then **one issuance approval** issues on BlockID EVM and syncs Hoodi and HashKey automatically; extra mints and
  dividends each need their own admin approval.
- **Share tokenisation (RWA).** One token = one share (`decimals = 0`, ASX-style 3-letter ticker, default
  A$1.00/share). Only KYC-verified wallets (via `IdentityRegistry`) can hold; lock-up, freeze, pause,
  max-holder cap, forced transfer (lost wallet / court order), and keccak256 of the canonical valuation report
  JSON is anchored on the token on all three chains (`anchorValuation`), checkable at `/verify/:ticker`.
- **Dividends.** Pro-rata plan from on-chain balances (rounded down), OpenZeppelin-compatible Merkle tree,
  `DividendDistributor` round funded in a stablecoin (`DemoAUD` on testnet); a relayer calls `claimFor` so
  shareholders pay no gas.
- **Cross-chain cap-table anchoring.** The operational register lives on the zero-gas BlockID EVM chain; a paused
  mirror token and the Merkle root of the cap table are anchored on Ethereum Hoodi and HashKey Chain testnet
  (`CapTableAnchor.verify` lets anyone prove a holder's balance against it).
- **Agent provenance on-chain (HashKey).** `AgentProvenance` records agent identity + policy hash, the content hash
  of each AI proposal, the model id, the human approval/rejection and the execution reference.
- **Tamper-evident audit.** Hash-chained JSON-Lines audit log (`audit.py`) plus a Postgres audit table of every
  admin action.
- **Wallet-native UX.** MetaMask Sign-In with Ethereum (EIP-4361), add-network / add-token buttons with QR codes,
  EN default with a Vietnamese toggle. Admins sign in with an admin wallet (SIWE) or the admin account.

## End-to-end demo run (automated)

`agents/.venv/bin/python scripts/demo_e2e.py --url https://www.canva.com --name Canva` runs the whole lifecycle on the
live stack with a full log: AI valuation → admin approval → ticker + shareholders → one issuance approval → BlockID EVM
+ Hoodi + HashKey → `/verify` → new round (mint) → dividend paid by the relayer → new investor KYC → transfer signed
by the holder's own wallet → three revaluations. Latest run: **CNV (Canva)** in ~11 minutes — log
[docs/demo-run/CNV-2026-09-26.md](docs/demo-run/CNV-2026-09-26.md) · live at https://eth.blockid.au/demo-run/latest.md ·
company https://eth.blockid.au/c/CNV · proof https://eth.blockid.au/verify/CNV.

## Documentation

| Doc | What is inside |
|---|---|
| **Pitch deck (3 min)** — [PDF](https://eth.blockid.au/deck/BlockID-Startup-Passport-3min.pdf) · [PPTX](https://eth.blockid.au/deck/BlockID-Startup-Passport-3min.pptx) · full deck [PDF](https://eth.blockid.au/deck/BlockID-Startup-Passport-pitch.pdf) ([source](docs/pitch/)) | 7 slides, one key point each: hook, problem → solution, how it works, valuation, one approval → 3 chains, verify, live results / ask; timed speaker notes |
| [User guide](docs/USER-GUIDE.md) | Task-by-task guide with screenshots: value a startup, tokenise, approve, MetaMask, new rounds, dividends, transfers/KYC, verify, operations |
| [Feature gallery](docs/FEATURES.md) | Every feature with screenshots from the live app (desktop, mobile, EN/VI) |
| [Deployments and tokens](docs/DEPLOYMENTS.md) | Every company token and contract on BlockID Chain, Hoodi and HashKey testnet, supply checked on-chain (generated) |
| [LLM routing](docs/LLM-ROUTING.md) | Free-first model chain (SambaNova → Claude subscription → DeepInfra) with the benchmark behind it |
| [Architecture diagrams](docs/ARCHITECTURE-DIAGRAMS.md) | 12 diagrams: system context, deployment topology, valuation pipeline, SVI scoring, LLM/search routing, issuance sequence, `/verify`, security boundaries, contracts, data model, state machines |
| [Upgrade roadmap](docs/ROADMAP-RESEARCH.md) | Sourced research: Safe multisig, invariant CI, monitoring, eval harness, EAS, valuation calibration, AU legal path, KYC, ERC-8004 |
| [Architecture](docs/ARCHITECTURE.md) · [Agents](docs/AGENTS.md) · [Implementation spec](docs/IMPLEMENTATION.md) | Live single-host architecture, agent graphs + policy table, API and issuer spec |
| [Security](docs/SECURITY.md) · [Runbook](docs/RUNBOOK-STUDIO.md) · [Demo script](docs/DEMO.md) · [Hackathon write-up](docs/HACKATHON.md) · [Facts](docs/FACTS.md) | Operations, judging material and the canonical facts sheet |

<p align="center">
  <a href="docs/FEATURES.md"><img src="docs/screenshots/01-home-hero.png" width="49%" alt="Home"></a>
  <a href="docs/FEATURES.md"><img src="docs/screenshots/19-company-eba-contracts-qr.png" width="49%" alt="Contract address cards on three chains"></a>
</p>

## Architecture

Detailed diagrams (rendered from Mermaid, sources in [`docs/diagrams/`](docs/diagrams/)):

![Deployment topology](docs/diagrams/02-deployment-topology.png)

![Issuance sequence: one approval, three chains](docs/diagrams/06-issuance-sequence.png)


```
 Founder / investor (MetaMask, SIWE)            Admin / approver (own wallet)
            │                                               │
            ▼                                               ▼
 ┌─────────────────────────── Web (React + viem) ───────────────────────────┐
 └───────────────┬───────────────────────────────────────────┬──────────────┘
                 │ HTTPS /api                                │ approve / reject
                 ▼                                           ▼
 ┌──────────────────── agents-api (FastAPI) ───────────────────────────────┐
 │  auth (SIWE / password) · CSRF · rate limits · approval queue · audit    │
 └───────┬───────────────────────────────────────────────┬─────────────────┘
         │ job queue                                     │ internal token, only for
         ▼                                               │ admin-approved DB rows
 ┌──── AGENT LAYER (no keys) ─────┐                      ▼
 │ agents-worker: LangGraph       │          ┌──── CONTROL PLANE ─────────────┐
 │ read_site → profile →          │          │ issuer service (isolated net,  │
 │ competitors → market → svi →   │          │ only key holder, read-only     │
 │ narrative → [gate: approval]   │          │ keystores) · atomic state       │
 │ policy.py: per-agent tools &   │          │ claims · on-chain result checks │
 │ model tiers, FORBIDDEN_TOOLS   │          └───────────────┬────────────────┘
 │ = sign/send/deploy/keys/shell  │                          │ signed txs
 └────────────────────────────────┘                          ▼
                    ┌──────────────────────── CHAINS ─────────────────────────────┐
                    │ BlockID EVM 262626   IdentityRegistry · ShareToken ·         │
                    │ (zero gas)           DividendDistributor · DemoAUD           │
                    │ Ethereum Hoodi       CapTableAnchor + paused mirror tokens   │
                    │ HashKey testnet 133  full RWA stack + AgentProvenance        │
                    └─────────────────────────────────────────────────────────────┘
```

More detail: [docs/HACKATHON.md](docs/HACKATHON.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md),
[docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md) (API + issuer spec).

## Chains

| Chain | Chain id | Role | Explorer |
|---|---|---|---|
| BlockID EVM (Cosmos EVM, gas price 0) | 262626 | Operational share register: issue, mint, dividends, KYC | https://scan.blockid.au |
| Ethereum Hoodi testnet | 560048 | Public anchor: `CapTableAnchor` Merkle roots + paused mirror tokens | https://hoodi.etherscan.io |
| HashKey Chain testnet | 133 | Paused mirror tokens + `CapTableAnchor` roots; full RWA stack + `AgentProvenance` | https://testnet-explorer.hskchain.net |

Existing deployments:

- Hoodi `CapTableAnchor`: `0xF3dC95D5d207dE9f2aC98184Fd32b45B72334263`
- HashKey `CapTableAnchor`: `0x728c834DE493DC3e9Ae2f7C0e79d86701B6F9F04` · HashKey `AgentProvenance`: `0x6B96bcE8937e1416Ec1DAC4ADAdD71FE879F8e84`
- BlockID EVM `DemoAUD` (mAUD): `0x286C1eD22A741F4939A3C7637011B0fAE2C7FFBc`
- Hoodi end-to-end demo (`scripts/hoodi-demo.sh`): share token `0xf3156Ad6eA559096D4aF350b39984408c764698E`,
  identity registry `0x6B96bcE8937e1416Ec1DAC4ADAdD71FE879F8e84`, dividend distributor
  `0x112C26D5f5d602293f1a00029f5E375763e70282`, mAUD `0xB8F96Eb528C563bFf04661F4062A5799A97D0FcA`

HashKey Chain testnet (chain id 133, RPC `https://testnet.hsk.xyz`) — hackathon RWA stack deployed by `scripts/hsk-demo.sh`:

| Contract | Address | Purpose |
|---|---|---|
| AgentProvenance | [`0x6B96bcE8937e1416Ec1DAC4ADAdD71FE879F8e84`](https://testnet-explorer.hskchain.net/address/0x6B96bcE8937e1416Ec1DAC4ADAdD71FE879F8e84) | AI proposal hash → human approval → execution (four-eyes) |
| BlockIDShareToken (DEM-ORD) | [`0x0107a9aF204113baD3a47a5BF23d84a3302A8cc1`](https://testnet-explorer.hskchain.net/address/0x0107a9aF204113baD3a47a5BF23d84a3302A8cc1) | Permissioned share token, 10,000 shares issued |
| IdentityRegistry | [`0x985cd14495320b1adb2Eb170B62db19b12e901Eb`](https://testnet-explorer.hskchain.net/address/0x985cd14495320b1adb2Eb170B62db19b12e901Eb) | KYC / investor eligibility |
| DividendDistributor | [`0xc0Ad2C03f04ce656Ba5820531a6E45d85C37511e`](https://testnet-explorer.hskchain.net/address/0xc0Ad2C03f04ce656Ba5820531a6E45d85C37511e) | Merkle dividend round, gasless `claimFor` |
| CapTableAnchor | [`0x728c834DE493DC3e9Ae2f7C0e79d86701B6F9F04`](https://testnet-explorer.hskchain.net/address/0x728c834DE493DC3e9Ae2f7C0e79d86701B6F9F04) | Cap-table Merkle root anchored for ticker `DEM` |
| DemoAUD (mAUD) | [`0xD40D9cb55b56b508A9Ee09E3967dAe14a6a0E058`](https://testnet-explorer.hskchain.net/address/0xD40D9cb55b56b508A9Ee09E3967dAe14a6a0E058) | Mock AUD stablecoin used for dividends |

Key transactions (the full *AI proposes → human approves → issuer executes* loop):

| Step | Tx |
|---|---|
| 1. Valuation agent's SVI report hash recorded (`propose`) | [`0x27b9f58a…`](https://testnet-explorer.hskchain.net/tx/0x27b9f58aa16754102e521de4fe1ff787ec327433eaf1df6815e60687f1c36b9f) |
| 2. Human approver wallet signs (`approve`) | [`0xc0e1821d…`](https://testnet-explorer.hskchain.net/tx/0xc0e1821d6a439536f2fc85132a53c893d07da4cacefe12eb2722b4b9a3bce9fa) |
| 3. Shares issued (guarded by `verify`) | [`0xf4d5a5e0…`](https://testnet-explorer.hskchain.net/tx/0xf4d5a5e0d623df3e28201a4eeddcbd361451e967fc6891bcbdb7644c636a9562) |
| 4. Valuation anchored on the share token | [`0x26b1484a…`](https://testnet-explorer.hskchain.net/tx/0x26b1484ade80f8a28ee452e3292d3338b58b9af08bbd2c65485187f93b5e86d4) |
| 5. Cap-table Merkle root anchored | [`0x8f984f02…`](https://testnet-explorer.hskchain.net/tx/0x8f984f02400da39e8dd105be7546dc55a3bd7c734ac4dfa025052b0c56159577) |
| 6. Dividend round funded | [`0x09932f10…`](https://testnet-explorer.hskchain.net/tx/0x09932f105dc1b879c0d82764e5c5e7eb2e4f46a629367803b081d2c530f3b7ef) |
| 7. Proposal marked executed | [`0x8896743f…`](https://testnet-explorer.hskchain.net/tx/0x8896743fc9d7f62857206ccae0ccea407fe9c03d2a71e8b5792680ffccad79e0) |
| 8. Gasless dividend claim (relayer) | [`0x89b1edc1…`](https://testnet-explorer.hskchain.net/tx/0x89b1edc1d65ed7288bc2a3d35ae6d5334b62cebddb26f6597995e070cfab349a) |

### One approval → three chains (live flow)

After a single admin approval the isolated issuer creates the register on BlockID EVM first, then syncs it to
Ethereum Hoodi and HashKey Chain (paused mirror token + cap-table Merkle root + the valuation report hash), with a
live tracker at `/c/:ticker`. Anyone can recompute the report hash in the browser at `/verify/:ticker`.
Example — **EBA (ETH BlockID Australia)**, 3,650,000 shares:

| Chain | Share token | Proof |
|---|---|---|
| BlockID EVM (262626) | [`0x95A5a4b82897087B2c044b653B8e6bd617a58718`](https://scan.blockid.au/token/0x95A5a4b82897087B2c044b653B8e6bd617a58718) | register of record |
| Ethereum Hoodi (560048) | [`0x1a305fdD461002BD6136476A69F3a268F79aAb3b`](https://hoodi.etherscan.io/token/0x1a305fdD461002BD6136476A69F3a268F79aAb3b) | paused mirror + `CapTableAnchor` root |
| HashKey Chain testnet (133) | [`0x041Eb1B727c4cdDfc8D46f1fBCb812E1c94fbc90`](https://testnet-explorer.hskchain.net/address/0x041Eb1B727c4cdDfc8D46f1fBCb812E1c94fbc90) | paused mirror; root anchored in [`0xda0d9934…`](https://testnet-explorer.hskchain.net/tx/0xda0d99340d6a892a6fc1e53d38cf7db8802936d623c55f4d1af06eafaef2e10f) |

Valuation report hash on all three tokens: `0xa1466362b035ecc804caf101986edc4de73697cacf54547226317616c3a73e33`
— check it at https://eth.blockid.au/verify/EBA.

Roles: operator/issuer `0x2567Bb502ac840cF93957C60A410160a8cCb5ddf` · relayer `0x1B43f0d3297F79cE6c8BbA12F4FadFBE9112DA4a` ·
admin wallets `0xc309691C60957A55bB619383A06d3F69A94f4585`, `0xC40052702B48631C26AD7c88b499bF230faCa21F` (human
approver on the HashKey `AgentProvenance` demo), `0x02B148f774Bd35B8753Ea6A17895931eD9201E2F`.
SVI report hash: `0x3c273fe671ed6024caede1240085a14a67c89a2f94ee08e0f82918af24efebf4` (keccak256 of [`contracts/deployments/params/hsk-svi-report.json`](contracts/deployments/params/hsk-svi-report.json)). Live page: https://eth.blockid.au/hsk

## Repository layout

```
blockid-eth-platform/
├── contracts/            Foundry (Solidity 0.8.28, OpenZeppelin v5.4.0)
│   ├── src/              IdentityRegistry · BlockIDShareToken · DividendDistributor · CapTableAnchor ·
│   │                     DemoAUD · AgentProvenance
│   ├── script/           DeployCompany · DeployPlatform · HoodiDemo (+ HSK demo)
│   ├── test/             unit + fuzz tests, Merkle fixtures
│   └── deployments/out/  deployed addresses per chain (JSON)
├── agents/               Python 3.11+: LangGraph agents, FastAPI API, worker, issuer service
│   └── src/blockid_agents/
│       ├── agents/       live: site_intake · competitors · research · valuation; legacy: intake · contract_builder · registry · dividend
│       ├── tools/        safefetch (SSRF-safe) · search · brave · svi · merkle · captable · ticker · chain · foundry
│       ├── studio/       auth (SIWE) · routes · runner · report_hash · verify · metrics · schema.sql
│       ├── issuer/       the only component with keys: chain · keys · merkle · service · app
│       ├── graph.py      site_valuation (live) + legacy onboarding/dividend graphs, human gates (interrupt)
│       ├── policy.py     least-privilege policy per agent, enforced in code
│       └── audit.py      hash-chained audit log
├── web/app/              Vite + React + TypeScript + viem (EN default, VI toggle)
├── deploy/               vm-app (docker compose, live) · blockscout · search-bridge (host Claude bridge) · vm-ai (earlier GPU VM design)
├── infra/terraform/      GCP infrastructure (earlier two-VM design)
├── scripts/              build-web.sh · hoodi-demo.sh · hsk-demo.sh · seed-companies.sh · export-deployments.py · screenshots/
└── docs/                 FACTS · HACKATHON · DEMO · FEATURES · USER-GUIDE · ARCHITECTURE(-DIAGRAMS) · AGENTS · SECURITY · RUNBOOK* · pitch/
```

## Quick start (offline, no API spend, no GPU)

Prerequisites: [Foundry](https://book.getfoundry.sh), Python 3.11+, `jq`.

```bash
make contracts-deps              # OpenZeppelin v5.4.0 + forge-std into contracts/lib
pip install -e "agents[dev]"     # Python agents, API, issuer (a virtualenv is recommended)
make test                        # forge test (37 Solidity tests incl. fuzz) + pytest (110 passed; 7 Postgres
                                 # tests skip without TEST_DATABASE_URL)
make demo                        # offline legacy data-room flow: profile → research → SVI → approval gates →
                                 # contract params → cap table → unsigned Safe batch → dividend Merkle round
```

`make demo` uses fake LLM/search backends, so it needs no keys. Other targets: `make slither` (static analysis),
`make lint` (ruff), `make svi PROFILE=examples/agritrace.json` (live valuation; needs API keys in `.env`, see
`.env.example`).

### Deploy the demo on HashKey Chain testnet

```bash
# needs testnet HSK on the deployer and relayer keystores (encrypted Foundry keystores, never plaintext keys)
scripts/hsk-demo.sh          # deploys the RWA stack + AgentProvenance on chain 133,
                             # writes contracts/deployments/out/hsk-demo.json
```

The equivalent Ethereum Hoodi flow is `scripts/hoodi-demo.sh` (deploy → KYC → issue → anchor valuation → fund a
dividend round → relayer `claimFor` for each shareholder → publish `web/hoodi-demo.json`).

### Run the full stack

The live site is one host (step-by-step: [docs/RUNBOOK-STUDIO.md](docs/RUNBOOK-STUDIO.md)): host nginx →
`web/dist`, and a docker compose project `blockid-app` (`deploy/vm-app/`) with `agents-api` (FastAPI),
`agents-worker` (LangGraph jobs), `issuer` (internal only, the only key holder), Postgres and `evmd` (BlockID
EVM node), plus Blockscout (`deploy/blockscout/`) and the host Claude bridge (`claude-search-bridge` systemd unit).

Env files (root-only, never committed): `/opt/blockid/app.env` (api, worker, issuer), `/opt/blockid/issuer.env`
(`ISSUER_INTERNAL_TOKEN`, api + issuer only), `/opt/blockid/search-bridge.env` (Claude bridge),
`/opt/blockid/blockscout.env`.

```bash
scripts/build-web.sh                                            # build the SPA into web/dist (safe for open tabs)
cd deploy/vm-app
sudo docker compose --env-file /opt/blockid/app.env build agents-api agents-worker issuer
sudo docker compose --env-file /opt/blockid/app.env up -d --no-build agents-api agents-worker issuer
sudo docker compose --env-file /opt/blockid/app.env logs -f agents-worker issuer
cd ../blockscout && sudo docker compose --env-file /opt/blockid/blockscout.env up -d
sudo systemctl restart claude-search-bridge                     # LLM /complete + web /search fallback
```

For local development without docker:

```bash
cd agents && PYTHONPATH=src python -m blockid_agents api      # API (FastAPI)
cd agents && PYTHONPATH=src python -m blockid_agents issuer   # issuer service (needs keystores + env)
cd web/app && npm install && npm run dev                       # web app
```

The earlier two-VM GCP design (Terraform, GPU VM) is documented in [docs/RUNBOOK.md](docs/RUNBOOK.md).

## Technical integration approach

- **Agents → chain only through a human.** Agents output typed Pydantic objects (valuation report). The API stores
  them as rows in a pending state. An admin approves with a SIWE-authenticated wallet session (or the admin
  account); only then does the API call the issuer over an internal network with an internal token. The
  issuer atomically claims the approved row, signs with its own keystore, waits for receipts and records tx
  hashes as events.
- **Provenance.** The issuer records `propose(agentId, kind, contentHash, modelId, uri)` on `AgentProvenance`;
  the human approver calls `approve(id)` / `reject(id, reason)` from their own wallet (must differ from the
  recorder); the issuer calls `markExecuted(id, executionRef)` only after approval. Anyone can call
  `verify(id, contentHash)` to check that a published report is the one that was approved.
- **Standards.** ERC-20 share token with an ERC-3643-compatible `isVerified()` identity check; OpenZeppelin
  AccessControl roles; OpenZeppelin Merkle proofs (double-hashed leaves, sorted pairs) shared by the Python
  builder and Solidity verifier (cross-checked in tests); EIP-4361 SIWE; `wallet_addEthereumChain` /
  `wallet_watchAsset` for UX.
- **Multi-chain by config.** The same compiled contracts deploy to BlockID EVM, Hoodi and HashKey Chain; the issuer
  picks RPC/chain id from environment variables and syncs the external chains in order (Hoodi, then HashKey), so
  one failing chain never blocks the other.
- **Verifiable report hash.** `studio/report_hash.py` defines the canonical report JSON (sorted keys, compact
  separators); keccak256 of it is anchored on all three tokens and recomputed in the browser by `/verify`.

## Security model (summary)

- No private key exists in the agent runtime; `sign_tx`, `send_tx`, `read_private_key`, `deploy_contract` and
  `shell` are forbidden for every agent in `policy.py`, enforced in code before every model/tool call.
- Untrusted web content is wrapped as data, outputs are schema-validated, uncited claims are dropped.
- The issuer is the only key holder, on isolated docker networks; the worker that processes untrusted websites
  cannot reach it.
- Admin login: SIWE wallet in `ADMIN_WALLETS`, or the admin account (username/password, `ADMIN_PASSWORD_HASH`,
  bcrypt, lockout). CSRF origin checks, SSRF-safe fetcher, rate limits, CSP/HSTS.
- Full details and the pre-production checklist (audited ERC-3643/T-REX, Safe multisig, independent audit,
  ASIC/AFSL advice): [docs/SECURITY.md](docs/SECURITY.md).

## Roadmap

Top items from the sourced research in [docs/ROADMAP-RESEARCH.md](docs/ROADMAP-RESEARCH.md):

1. **Safe 2-of-3 as admin** on all three chains; the issuer keeps only narrow roles (`ISSUER_ROLE` /
   `RECORDER_ROLE`).
2. **Invariant + static-analysis CI** (Foundry invariants, Aderyn, Halmos).
3. **On-chain alerting and end-to-end tracing** (OZ Monitor, OpenTelemetry, Langfuse).
4. **Valuation eval + red-team harness** (golden set, prompt-injection pages) and **EAS valuation attestations**.
5. **Calibrated multiples + backtest** instead of LLM-cited multiples.
6. **Legal path**: licensed CSF intermediary / AFSL partner, or a TCP licence ahead of 9 Apr 2027.
7. **Scoped agent permissions**: Safe + Zodiac Roles on HashKey; EIP-7702 / ERC-7579 session keys (4337 stack) on
   Ethereum.
8. **Real KYC** (AU/VN providers + HashKey KYC SBT) and **ERC-8004 agent identity/reputation** from the
   `AgentProvenance` history.
9. Later: official ERC-3643 + ONCHAINID, independent audit, real stablecoin dividends, ZK selective disclosure,
   multi-validator chain and HashKey mainnet, open-source SDK of the provenance + approval pattern.

## License

[MIT](LICENSE) © 2026 BlockID. Open source so other teams can reuse the agent-provenance + human-approval pattern (`AgentProvenance.sol`) in their own AI x Ethereum apps. Third-party code (OpenZeppelin, forge-std) keeps its own license.

> **Testnet demo. Not an offer of securities.** Contracts are simplified ERC-3643-compatible versions and have not
> been audited. Nothing here is legal or financial advice.
