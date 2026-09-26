# BlockID Startup Passport — technical documentation (EAG Global Buildathon, Sydney)

*Agents propose. Humans approve. Chains prove.* (Built on the BlockID Issuance Studio platform.)

> **Testnet demo. Not an offer of securities.**

**Pitch.** AI agents value startups and tokenise their equity as a real-world asset, but agents never hold keys:
every agent proposal is hashed on-chain, a human approves with their own wallet, and only then does the isolated
issuer execute.

- Live app: https://eth.blockid.au · HashKey Chain page: https://eth.blockid.au/hsk · Explorer: https://scan.blockid.au
- Repo guide: [README.md](../README.md) · Demo script: [DEMO.md](DEMO.md) · Security: [SECURITY.md](SECURITY.md)

---

## 1. Tracks and why

### Sydney Hackathon — AI x Ethereum & Agent Economy

The track asks for agent identity, agent reputation, permissioned agent wallets, safe spending policies,
AI-driven on-chain execution and AI-generated content provenance. BlockID is an *AI-driven on-chain execution*
product where the hard problem is exactly the one the track names: **how do you let agents act on real assets
(company equity, dividend money) without giving them the keys?** Our answer is a concrete, working pattern:

| Track keyword | How BlockID implements it |
|---|---|
| Agent identity | `AgentProvenance.registerAgent(agentId, name, policyHash)` — each agent has an on-chain id bound to the hash of its permission policy (`policy.py`) |
| Permissioned agent execution / wallets | Agents have **no wallet at all**. Only the isolated issuer service signs, and only for rows a human approved. On-chain, `markExecuted` reverts unless the proposal was approved |
| Safe spending / execution policies | `policy.py` whitelists tools and model tiers per agent, enforced in code before every call; `FORBIDDEN_TOOLS` = `sign_tx, send_tx, read_private_key, deploy_contract, shell`. Rate limits on valuations. Four-eyes rule on-chain: approver ≠ recorder |
| AI-driven on-chain execution | Approved valuations become share tokens, cap-table anchors, mints and dividend rounds — executed automatically by the issuer after approval |
| AI-generated content provenance | Every AI output (valuation report, cap-table plan, dividend plan) is registered by `contentHash` + `modelId` + `uri`; `verify(id, contentHash)` proves a published report is the one a human approved. The SVI report hash is also anchored on the share token (`anchorValuation`) |
| Agent reputation (roadmap) | The provenance log (proposals, approvals, rejections, overrides) is the raw data for an on-chain reputation score per agent/model |

### HashKey Chain track — RWA / AI Agents

Tokenised private-company equity is an RWA with a real, under-served market, and HashKey Chain's compliance
positioning fits permissioned securities. For the hackathon we deployed the **complete stack on HashKey Chain
testnet (chain id 133, RPC `https://testnet.hsk.xyz`)**: `IdentityRegistry`, `BlockIDShareToken`,
`DividendDistributor`, `DemoAUD`, `CapTableAnchor` and `AgentProvenance`, via `scripts/hsk-demo.sh`, with a
public page at https://eth.blockid.au/hsk.

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

Roles: operator/issuer `0x2567Bb502ac840cF93957C60A410160a8cCb5ddf` · human approver `0xC40052702B48631C26AD7c88b499bF230faCa21F` · relayer `0x1B43f0d3297F79cE6c8BbA12F4FadFBE9112DA4a`.
SVI report hash: `0x3c273fe671ed6024caede1240085a14a67c89a2f94ee08e0f82918af24efebf4` (keccak256 of [`contracts/deployments/params/hsk-svi-report.json`](../contracts/deployments/params/hsk-svi-report.json)). Live page: https://eth.blockid.au/hsk

Against the HSK judging criteria:

- **Feasibility & real-world potential** — the platform is live, not a mock: real website crawling, real
  valuations, real contracts on three chains, working approval queue, gasless dividend claims.
- **Meaningful user/market problem** — SMEs cannot afford valuations, registries or dividend administration.
- **Technical & product innovation** — on-chain provenance + four-eyes approval of AI output as a reusable
  primitive for "AI agents × RWA", instead of trusting an agent with a key.

### Cross-track themes

- **Open-source, reusable components**: `AgentProvenance.sol`, `policy.py` (least-privilege agent policy),
  `audit.py` (hash-chained log), `safefetch.py` (SSRF-safe crawler), Python↔Solidity-compatible Merkle builder.
- **Privacy, security, user agency by design**: no PII on-chain (KYC is a hash), users sign in with their own
  wallet, humans approve with their own wallet, agents hold no keys.
- **Emerging regions**: built for Australian and Vietnamese SMEs; EN/VI UI; zero-gas operational chain so
  shareholders never need to buy gas; relayer-paid dividend claims.
- **Sustainability**: low-cost batch AI (jobs queued, GPU only on demand), per-issuance and per-dividend fees
  are a natural business model once licensed.

## 2. Problem and users

- **Founders / SME owners**: want a credible valuation and a clean, shareable cap table without paying a law firm
  and a valuer thousands of dollars.
- **Small shareholders (employees, angels, family)**: want to see their holding and receive dividends without
  bank-transfer admin or gas fees.
- **Platform operator / transfer agent**: must stay accountable — every AI suggestion and every execution needs an
  audit trail a regulator (ASIC) or auditor can check.

Today these cap tables live in spreadsheets; valuations are opinions without evidence; dividends are manual.

## 3. Architecture

```
┌───────────────────────────────────────────────────────────────────────────┐
│ 1. UI  (React + viem, MetaMask, SIWE EIP-4361, EN/VI)                     │
│    /new wizard · /v/:id valuation · /c/:ticker company · /admin · /hsk    │
└──────────────────────────────┬────────────────────────────────────────────┘
                               │ HTTPS, session cookie, CSRF origin check
┌──────────────────────────────▼────────────────────────────────────────────┐
│ 2. AGENT LAYER — no keys, no wallets                                      │
│    LangGraph `site_valuation`: read_site → profile → competitors →        │
│    market → svi → narrative → [gate_valuation: interrupt()]               │
│    policy.py guard(): per-agent tools + model tiers; FORBIDDEN_TOOLS      │
│    safefetch.py (public IPs only, per-hop redirect checks, size/time caps)│
│    Outputs: Pydantic-validated objects; every claim cites a fetched URL   │
└──────────────────────────────┬────────────────────────────────────────────┘
                               │ rows in Postgres (status = pending)
┌──────────────────────────────▼────────────────────────────────────────────┐
│ 3. CONTROL PLANE                                                          │
│    agents-api: approval queue; admin approves with own wallet (SIWE)      │
│    issuer service: only key holder, isolated docker networks, internal    │
│    token; atomically claims *approved* rows; checks on-chain results      │
│    before retry; records tx hashes as events                              │
│    audit: hash-chained JSONL log + studio.audit table                     │
└──────────────────────────────┬────────────────────────────────────────────┘
                               │ signed transactions
┌──────────────────────────────▼────────────────────────────────────────────┐
│ 4. CHAINS                                                                 │
│    BlockID EVM 262626 (zero gas): operational register + dividends        │
│    Ethereum Hoodi 560048: CapTableAnchor Merkle roots, paused mirrors     │
│    HashKey Chain testnet 133: full RWA stack + AgentProvenance            │
└───────────────────────────────────────────────────────────────────────────┘
```

### Lifecycle of one company

1. Founder signs in with MetaMask and submits a website (+ optional self-reported metrics).
2. Worker runs the valuation graph; SVI index, band and low/mid/high valuation are computed by code; LLM-suggested
   qualitative scores are labelled `ai_suggested`. The graph stops at `gate_valuation`.
3. Admin reviews evidence, approves or overrides scores (overrides become `human`).
4. Founder creates the company: name, ticker (suggested), holders and percentages (validated to sum to 100%,
   EIP-55 addresses). Total shares = valuation mid / A$1.00.
5. Admin approves issuance → issuer deploys `IdentityRegistry`, `BlockIDShareToken`, `DividendDistributor`,
   registers KYC for each holder, issues shares and anchors the valuation hash on BlockID EVM.
6. Admin approves anchoring → issuer mirrors balances on Hoodi (paused token) and anchors the cap-table Merkle root
   in `CapTableAnchor`.
7. Later: mint requests and dividend plans follow the same propose → approve → execute path; dividends are paid
   via `claimFor` by a relayer so holders pay nothing.

With `AgentProvenance`, each "propose" step also creates an on-chain proposal, the human approval is an on-chain
transaction from the approver's wallet, and the execution tx is linked back with `markExecuted`.

## 4. Agent safety model

| Layer | Control | Where |
|---|---|---|
| Capability | No private key, wallet or signing tool exists in the agent runtime | `policy.py` `FORBIDDEN_TOOLS`, container isolation |
| Least privilege | Per-agent allow-list of tools and model tiers; PII-handling agents are local-tier only | `policy.POLICIES`, `guard()` |
| Deterministic maths | SVI index and valuation computed by code; LLM only suggests qualitative scores | `tools/svi.py`, `agents/valuation.py` |
| Prompt injection | Web content treated as untrusted data; schema-validated outputs; uncited claims dropped | agents, `schemas.py` |
| Network | SSRF-safe crawler; worker cannot reach the issuer network | `tools/safefetch.py`, docker networks |
| Human-in-the-loop | LangGraph `interrupt()` gates + admin approval for issue / anchor / mint / dividend | `graph.py`, studio routes |
| Four-eyes on-chain | Approver wallet ≠ recorder (issuer) wallet; `markExecuted` requires approval | `AgentProvenance.sol` |
| Execution integrity | Issuer atomically claims only approved rows; retries check chain state first | `issuer/service.py` |
| Auditability | Hash-chained audit log, on-chain events, report hashes anchored on the token | `audit.py`, contracts |
| Abuse limits | 3 valuations / wallet / day, 60 / day globally, max 5 active | studio config |

## 5. Smart contracts

| Contract | Purpose |
|---|---|
| `IdentityRegistry` | wallet → KYC status, country, expiry; stores only a hash of the KYC record; ERC-3643-style `isVerified()` |
| `BlockIDShareToken` | 1 token = 1 share (`decimals = 0`); transfers only between verified wallets; lock-up, freeze, pause, holder cap, `forcedTransfer`, `anchorValuation(reportHash, perShareCents)`; roles `ISSUER_ROLE`, `TRANSFER_AGENT_ROLE`, `PAUSER_ROLE` |
| `DividendDistributor` | per-round Merkle root, stablecoin payout, `claim` / gasless `claimFor` via relayer, `closeRound` reclaims unclaimed funds after the deadline |
| `CapTableAnchor` | `anchor(ticker, localToken, localChainId, localBlock, merkleRoot, totalSupply, uri)`; `verify(ticker, holder, balance, proof)` lets anyone prove a holding |
| `DemoAUD` | testnet stablecoin (6 decimals, owner-mintable) for dividends |
| `AgentProvenance` *(hackathon)* | AccessControl with `REGISTRAR_ROLE`, `RECORDER_ROLE` (issuer service), `APPROVER_ROLE` (human admin wallet). `registerAgent(agentId, name, policyHash)`; `propose(agentId, kind, contentHash, modelId, uri) → proposalId` (recorder); `approve(id)` / `reject(id, reason)` by an approver who must differ from the recorder; `markExecuted(id, executionRef)` only after approval; `verify(id, contentHash)` view |

Tooling: Foundry, Solidity 0.8.28, OpenZeppelin v5.4.0, unit + fuzz tests, Slither in CI.

## 6. HashKey Chain integration

- **Network**: HashKey Chain testnet, chain id **133**, RPC `https://testnet.hsk.xyz`.
- **Deployment**: `scripts/hsk-demo.sh` deploys the RWA stack and `AgentProvenance`, runs the demo flow and writes
  `contracts/deployments/out/hsk-demo.json`, which the web page https://eth.blockid.au/hsk reads.
- **Keys**: deployer and relayer are encrypted Foundry keystores; no private key is in the repo or the script.
- **Same bytecode, three chains**: contracts are chain-agnostic; the chain is selected by RPC/chain id.
- **Why HSK for production RWA**: a compliance-oriented L2 with an institutional ecosystem is a natural home for
  a permissioned share token whose holders must be KYC-verified.

## 7. Key features (summary)

AI valuation with evidence (SVI) · human approval gates · permissioned share tokens · Merkle dividends with gasless
claims · cross-chain cap-table anchoring and holder proofs · on-chain agent provenance and four-eyes approval ·
hash-chained audit · SIWE wallet login · EN/VI UI · zero-gas operational chain.

## 8. What was built during the hackathon vs before

Honest scope statement:

- **Before the hackathon** (existing BlockID platform): the agent pipeline (LangGraph, SVI, policy, audit), the
  Issuance Studio web app and API, the issuer service, the share-token / identity / dividend / anchor contracts,
  the BlockID EVM chain and Blockscout explorer, and the Ethereum Hoodi deployment.
- **During the hackathon**:
  - `AgentProvenance.sol` — on-chain agent identity, AI-output provenance and four-eyes human approval;
  - deployment of the full RWA stack + `AgentProvenance` on **HashKey Chain testnet** (`scripts/hsk-demo.sh`);
  - the HashKey Chain web page (https://eth.blockid.au/hsk);
  - English documentation for judges (README, this document, DEMO, security clean-up).

## 9. Roadmap

1. **ERC-4337 agent smart accounts** with session keys and on-chain spending limits, so an agent can perform
   narrow, pre-approved actions (e.g. relaying dividend claims) within a budget.
2. **Agent reputation** computed from `AgentProvenance` history: approval rate, human override rate, accuracy of
   valuations against later rounds.
3. **Real stablecoin dividends on HashKey Chain** and **HSK mainnet** deployment.
4. **ZK selective disclosure of shareholder KYC** (prove "verified, eligible jurisdiction" without revealing identity).
5. **Production hardening**: issuance through a Safe multisig, audited ERC-3643 (T-REX) + ONCHAINID, independent
   audit, multi-validator BlockID chain, AFSL / legal advice (see [SECURITY.md](SECURITY.md)).
6. **Open-source SDK** of the provenance + approval-gate pattern (Solidity contract + Python/TypeScript client)
   for any team that wants agents to act on-chain without keys.

> **Testnet demo. Not an offer of securities.** Not legal or financial advice.


## Visual summary

![How it works](images/architecture.png)

![Challenges](images/challenges.png)
