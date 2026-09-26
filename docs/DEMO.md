# BlockID Startup Passport — demo script (3 minutes) + Q&A prep (2 minutes)

> **Testnet demo. Not an offer of securities.**

Before going on stage: sign in once at https://eth.blockid.au with MetaMask (founder wallet) and in a second
browser profile with the admin wallet; keep company **ARW (Airwallex)** in *Awaiting issue approval* for the live approval (valuations
take a few minutes, so they are pre-run); open tabs for https://eth.blockid.au/hsk, https://scan.blockid.au and the HashKey testnet
explorer on the `AgentProvenance` contract.

## Timed beats

| Time | Screen | Say |
|---|---|---|
| 0:00–0:20 | Home page | "Startups in Australia, Vietnam and emerging markets can't afford a valuation, a proper share register or dividend admin — cap tables live in spreadsheets. BlockID lets AI agents do the work and tokenises the equity as an RWA — but agents never hold keys." |
| 0:20–0:50 | `/new` wizard → paste a website, start valuation; switch to the pre-run valuation `/v/:id` | "The agent crawls the public site through an SSRF-safe fetcher, finds competitors, builds a market view and scores 7 SVI dimensions. The maths is code; the AI only suggests qualitative scores, labelled `ai_suggested`, and every claim links to a fetched source." |
| 0:50–1:15 | Evidence list, dimension bases, then `/admin` approvals queue | "The graph stops at a human gate. The admin — a different person, with their own wallet — approves or overrides. The agent's policy forbids signing, sending, deploying, reading keys or running a shell — enforced in code, not in the prompt." |
| 1:15–1:50 | `/admin` → Approvals → company **ARW (Airwallex)** pending → "Approve issuance (runs all chains)"; open `/c/ARW` tracker | "One human approval. The isolated issuer — the only component with a key — creates the share register on our zero-gas BlockID chain first: identity registry, permissioned token, dividend distributor, KYC for each holder, shares issued. Then it syncs automatically to Ethereum Hoodi and HashKey Chain." Point at the live tracker lines ("Now: KYC 2/3…", tx links to scan.blockid.au) |
| 1:50–2:10 | Company page of an anchored company (e.g. **EBA**): contract-address cards for BlockID / Hoodi / HashKey, "Add to MetaMask" | "Each chain gets a paused mirror of the cap table plus a Merkle root in `CapTableAnchor`; every shareholder can import the token and prove their balance." |
| 2:10–2:40 | `/verify/EBA` → green banner (BlockID ✓ Hoodi ✓ HashKey ✓) → **Tamper test** → red | "Auditable AI: the model only scores; a fixed public formula computes the value — recomputed here in your browser. The keccak of the report is on three chains. Change one score and the hash no longer matches." Then mention `/hsk` + `AgentProvenance` four-eyes approval for the HashKey track |
| 2:40–3:00 | Back to home | "AI proposes, code computes, humans approve with their own wallets, an isolated issuer signs, and every step is provable on-chain. Next: ERC-4337 agent accounts with spending limits, agent reputation from this provenance log, real stablecoin dividends and HSK mainnet." |

Fallback if the live site or a chain RPC is slow: run `make demo` (offline end-to-end with fake LLM) in a
terminal and show the pre-deployed contracts on the explorers.

## Q&A prep

**Why not just give the agent a wallet with limits?**
Equity issuance is irreversible and regulated; one prompt injection could mint shares. We keep agents keyless
today and put limits on-chain later (ERC-4337 session keys, roadmap) — the provenance contract is the audit trail
either way.

**What stops the issuer from executing something unapproved?**
Off-chain, the issuer only acts on rows in an admin-approved state, claimed atomically. On-chain, `markExecuted`
reverts unless the proposal was approved by an `APPROVER_ROLE` wallet different from the recorder.

**How do you handle prompt injection from crawled websites?**
Content is treated as untrusted data, outputs are schema-validated, uncited claims are dropped, and permissions
live in code (`policy.py`), so injected text cannot add tools. The crawler cannot reach private IPs.

**Is the valuation any good?**
It is evidence-backed and transparent: each dimension shows its basis and sources, and a human signs off. It is a
starting point for SMEs who otherwise have nothing; weights are documented and calibration is ongoing.

**Is this legal?**
It is a testnet demo, not an offer of securities. Production requires audited ERC-3643 (T-REX), a Safe multisig
issuer, an independent audit and an AFSL / licensed partner in Australia (details in SECURITY.md).

**Why three chains?**
BlockID EVM gives zero-gas day-to-day operations for small holders; Ethereum Hoodi is a neutral public anchor;
HashKey Chain is the compliance-focused home for the RWA stack going forward.

**Where is personal data?**
Never on-chain — the registry stores only a hash of the KYC record. PII-handling agents are restricted to the
local model tier in code.

**How do you make money?**
Fees per valuation, per issuance and per dividend round for SMEs; transfer-agent services once licensed.

**What did you build during the hackathon?**
`AgentProvenance`; the HashKey Chain deployment and page; one-approval sync BlockID → Hoodi → HashKey with a live issuance tracker; the `/verify` page (report hash recomputed in the browser and compared on three chains); a Claude-CLI web-search fallback with a 3-query research budget; English docs. The core platform existed before the event.
