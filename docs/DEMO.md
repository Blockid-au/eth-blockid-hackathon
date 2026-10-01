# BlockID Business Passport — demo script (3 minutes) + Q&A prep (2 minutes)

> **Testnet demo. Not an offer of securities.**

The live talk follows the 3-minute deck ([PDF](https://eth.blockid.au/deck/BlockID-Business-Passport-3min.pdf) ·
[PPTX](https://eth.blockid.au/deck/BlockID-Business-Passport-3min.pptx)) · video:
https://eth.blockid.au/deck/blockid-business-passport-3min-captions.mp4 (recorded live-app demos: https://eth.blockid.au/deck/blockid-business-passport-demo-3min-captions.mp4, 3 min, and https://eth.blockid.au/deck/blockid-business-passport-full-demo-captions.mp4, 5:15; source in `docs/video/full`). The timed script below follows the earlier
7-slide deck; the flow on stage is the same.

## Before going on stage

- **Prepare one company in *Awaiting issue approval*** (status `pending_issue`) before the demo: pick an approved
  valuation (valuations take a few minutes, so run it in advance), create the company (name, ticker, 2–4
  shareholders with wallets and %), and **Submit**. Leave it in the admin **Issuance** queue. All 14 existing
  companies are already issued on three chains (see [DEPLOYMENTS.md](DEPLOYMENTS.md)).
- Check the issuer has gas on Hoodi and HashKey (Admin → Issuer wallets; about 0.004 Hoodi ETH per company).
- Sign in at https://eth.blockid.au with the founder wallet, and in a second browser profile with an admin wallet
  (SIWE) or the admin account.
- Open tabs: `/admin` (inbox), a pre-run valuation report `/v/:id/report` (e.g. Airwallex), `/verify/EBA`,
  https://scan.blockid.au, https://eth.blockid.au/hsk and the HashKey testnet explorer.
- Backup if nothing is pending: approve a share **mint** instead (company page → **Model a new round**, or
  `POST /v1/companies/{tk}/mints`) — it re-syncs Hoodi and HashKey after the BlockID mint.

## Timed beats (7 slides)

| Time | Slide / screen | Say |
|---|---|---|
| 0:00–0:20 | 1 · Hook | "Investors in a business can't easily see what it's worth, follow it after they invest, or prove what they own. BlockID Business Passport fixes that. Agents propose, humans approve, chains prove." |
| 0:20–0:45 | 2 · Problem → solution | "Cap tables live in spreadsheets, valuations are slow and unsourced, shareholders can't verify anything. The founder pastes a website, gets a cited valuation in minutes, and after one approval has KYC-gated shares on-chain that anyone can verify." |
| 0:45–1:15 | 3 · How it works (whole system) | "AI agents read up to six pages and run at most three searches; a fixed formula computes the value; the agents hold no keys. A human admin signs one approval. Only then does the isolated issuer — the only component with a key — create the register on our zero-gas chain and mirror it to Ethereum Hoodi and HashKey." |
| 1:15–1:40 | 4 · Valuation → pre-run report `/v/:id/report` | "The AI only suggests scores, labelled `ai_suggested`. A fixed public formula turns seven weighted dimensions into a grade and a range; any claim without a fetched source is dropped." Point at the evidence list and dimension bases. |
| 1:40–2:05 | 5 · One approval → 3 chains → **live**: `/admin/issuance` → the prepared company → **Sign & issue**; open `/c/:ticker/issue` (the page moves on to *Sync chains* and *Wallet* by itself) | "One approval. The issuer deploys the registry and token, KYCs each holder and issues on BlockID Chain, then mirrors the cap table with a Merkle root to Hoodi and HashKey." Let the tracker run (BlockID → Hoodi → HashKey, about 1–2 min); show the contract cards with QR + Add to MetaMask. |
| 2:05–2:25 | 6 · Verify → **live**: `/verify/EBA` → green (BlockID ✓ Hoodi ✓ HashKey ✓) → **Tamper test** → red | "You don't have to trust us. The page recomputes keccak256 of the canonical report in your browser and compares it with the hash on all three chains. Change one score and it turns red." |
| 2:25–3:00 | 7 · Live results / ask | "This runs end to end today on testnet: fourteen sample listings built from public information, forty-two token contracts on three chains, fourteen out of fourteen verified, 378 automated tests. We're looking for pilot businesses, investor communities and licensed partners — try it at eth.blockid.au." Come back to the tracker: the new company should now be live on all three chains. |

Fallback if the live site or a chain RPC is slow: run `make demo` (offline end-to-end with fake LLM) in a
terminal and show the pre-deployed contracts on the explorers.

## Q&A prep

**Why not just give the agent a wallet with limits?**
Equity issuance is irreversible and regulated; one prompt injection could mint shares. We keep agents keyless
today and put limits on-chain later (Safe + Zodiac Roles on HashKey, session keys on Ethereum — roadmap) — the
provenance contract is the audit trail either way.

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
Testnet demo. Not an offer of securities. Production requires audited ERC-3643 (T-REX), a Safe multisig
issuer, an independent audit and an AFSL / licensed partner in Australia (details in SECURITY.md).

**Why three chains?**
BlockID EVM (chain 262626) gives zero-gas day-to-day operations for small holders; Ethereum Hoodi (560048, the
current Ethereum testnet) is a neutral public anchor; HashKey Chain testnet (133) is the compliance-focused home for
the RWA stack. One approval syncs all three.

**Where is personal data?**
Never on-chain — the registry stores only a hash of the KYC record. PII-handling agents are restricted to the
local model tier in code.

**How do you make money?**
Issuance fee, cap-table SaaS, a transfer-agent fee per transfer, 0.5–1% of dividend rounds, and custody via a
licensed partner.

**What did you build during the hackathon?**
`AgentProvenance`; the HashKey Chain deployment and `/hsk` page; one-approval sync BlockID → Hoodi → HashKey with a
live issuance tracker; the canonical report hash and the `/verify` page (recomputed in the browser, compared on
three chains); the 3-search research budget with the Claude web-search bridge; the SambaNova → Claude bridge →
DeepInfra LLM chain; English docs, diagrams and the pitch deck. The core platform existed before the event
(details in [HACKATHON.md](HACKATHON.md) §8).
