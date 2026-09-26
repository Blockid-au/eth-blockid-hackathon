# BlockID Startup Passport — demo script (3 minutes) + Q&A prep (2 minutes)

> **Testnet demo. Not an offer of securities.**

Before going on stage: sign in once at https://eth.blockid.au with MetaMask (founder wallet) and in a second
browser profile with the admin wallet; have one valuation already finished and waiting for approval (valuations
take a few minutes); open tabs for https://eth.blockid.au/hsk, https://scan.blockid.au and the HashKey testnet
explorer on the `AgentProvenance` contract.

## Timed beats

| Time | Screen | Say |
|---|---|---|
| 0:00–0:20 | Home page | "Startups in Australia, Vietnam and emerging markets can't afford a valuation, a proper share register or dividend admin — cap tables live in spreadsheets. BlockID lets AI agents do the work and tokenises the equity as an RWA — but agents never hold keys." |
| 0:20–0:50 | `/new` wizard → paste a website, start valuation; switch to the pre-run valuation `/v/:id` | "The agent crawls the public site through an SSRF-safe fetcher, finds competitors, builds a market view and scores 7 SVI dimensions. The maths is code; the AI only suggests qualitative scores, labelled `ai_suggested`, and every claim links to a fetched source." |
| 0:50–1:15 | Evidence list, dimension bases, then `/admin` approvals queue | "The graph stops at a human gate. The admin — a different person, with their own wallet — approves or overrides. The agent's policy forbids signing, sending, deploying, reading keys or running a shell — enforced in code, not in the prompt." |
| 1:15–1:45 | Create company (ticker, holders), submit; admin approves issuance; company page `/c/:ticker` | "On approval, the isolated issuer — the only component with a key — deploys the identity registry, the permissioned share token and dividend distributor, KYCs the holders and issues shares. Zero gas on the BlockID chain." Click a tx → https://scan.blockid.au |
| 1:45–2:05 | Company page: anchor to Hoodi, add-token button | "The cap-table Merkle root is anchored on Ethereum Hoodi — any holder can prove their balance against it." |
| 2:05–2:40 | https://eth.blockid.au/hsk + HSK explorer | "For the HashKey track the full stack is live on HashKey Chain testnet, plus our new `AgentProvenance` contract: the agent's output hash and model id are recorded, a human approver wallet approves on-chain — it must differ from the recorder, four-eyes — and only then can execution be marked. Anyone can `verify` a report against what was approved." |
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
`AgentProvenance`, the HashKey Chain deployment and page, and the English docs. The rest of the platform existed.
