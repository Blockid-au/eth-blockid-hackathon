# BlockID Startup Passport — upgrade roadmap (research, 2026-09-26)

Opinionated plan after the EAG Sydney build. Effort: **S** ≤ 3 days, **M** 1–3 weeks, **L** > 1 month.
Items tagged *[verify]* rest on sources we could not fully confirm. Not legal advice.

## 1. Where we stand

| Area | Strength today | Gap vs. the market / best practice |
|---|---|---|
| Agent safety | No keys in agent runtime, `policy.py` guard, four-eyes `AgentProvenance`, isolated issuer | Issuer is a **hot key**; no scoped/capped agent permissions; no standard agent identity (ERC-8004) |
| Contracts | 6 small contracts, 37 tests incl. fuzz, Slither in CI | Simplified ERC-3643 clone; **no invariant/symbolic tests**, no Aderyn; unaudited |
| Valuation | Deterministic SVI maths, cited sources, human override, model benchmark (LLM-ROUTING.md) | Revenue multiples come from **LLM-cited** market data; no golden set, no backtest, no red-team suite |
| Cap table | 1 token = 1 share, KYC-gated transfers, forced transfer, 50-holder cap | No option pools/vesting, SAFEs/notes, share classes, waterfalls, ASIC filings ([Carta](https://carta.com/equity-management/cap-table/), [Cake](https://www.cakeequity.com/au)) |
| Cross-chain | Merkle root anchoring on Hoodi + HSK, `verify` proofs, `/verify` page | Trust = issuer signer; nothing remote can *act* on the root |
| Identity/KYC | Hash-only KYC, country block list | No real KYC provider; no ONCHAINID/claims; no privacy-preserving proofs |
| Ops | Hash-chained audit, CSP/SSRF/CSRF controls | No tracing/metrics/on-chain alerting; single-validator chain |
| Legal | Clear "testnet, not an offer" | No AFSL/CSF path chosen; ASIC's no-action window closed **30 Jun 2026** ([25-250MR](https://www.asic.gov.au/about-asic/news-centre/find-a-media-release/2025-releases/25-250mr-updated-asic-guidance-supports-digital-asset-innovation-and-boosts-investor-protection)) |

Key research facts that shape the plan:
- **HashKey Chain** (OP Stack L2, chain 177/133): Safe is officially deployed ([mainnet](https://multisig.hashkeychain.net/welcome?chain=HSK), [testnet](https://testnet-safe.hsk.xyz/welcome?chain=HSKT)); Chainlink **CCIP** is live (testnet lanes to *Sepolia*, not Hoodi) ([directory](https://docs.chain.link/ccip/directory/testnet/chain/ethereum-testnet-sepolia-hashkey-1)); oracles are Supra/APRO/Chainlink Data Streams ([docs](https://docs.hskchain.net/docs/Build-on-HashKey-Chain/Tools/Oracle)); a native **KYC SBT** (`isHuman`, levels) exists ([docs](https://docs.hskchain.net/docs/Build-on-HashKey-Chain/Tools/KYC)). **No EAS, no confirmed ERC-4337 bundler/paymaster** (not in [Pimlico's list](https://docs.pimlico.io/guides/supported-chains)) *[verify]*. L2BEAT: permissioned proposer, no working fault proofs ([L2BEAT](https://l2beat.com/scaling/projects/hashkey)).
- **T-REX**: Tokeny's repo was archived Oct 2025; development continues at [ERC-3643/ERC-3643](https://github.com/ERC-3643/ERC-3643) + [ONCHAINID](https://github.com/ERC-3643/ONCHAINID).
- **AU law**: Digital Assets Framework Act passed (Royal Assent 8 Apr 2026, commences **9 Apr 2027**) creating DAP/TCP licences ([G+T](https://www.gtlaw.com.au/insights/key-topics/regulation-in-motion/australia-passes-highly-anticipated-digital-asset-regulation)); tokenised Pty shares remain securities. AUSTRAC tranche-2 obligations started 1 Jul 2026 ([AUSTRAC](https://www.austrac.gov.au/industry-and-business/about-amlctf-reforms/about-reforms)).
- **Tooling churn**: OpenZeppelin Defender shut down 1 Jul 2026, replaced by self-hosted [OZ Monitor](https://docs.openzeppelin.com/monitor). Certora Prover is open source ([Certora](https://www.certora.com/blog/certora-goes-open-source)).

## 2. Roadmap

### Now (next 2 weeks)

1. **Safe as admin; issuer keeps only narrow roles.** *Why:* the hot key is our biggest real risk, and Safe already runs on HSK. Move `DEFAULT_ADMIN_ROLE`/`PAUSER_ROLE` to a 2-of-3 Safe; the issuer keeps `ISSUER_ROLE`/`RECORDER_ROLE` only. *Effort:* S. *Dep:* none. *Metric:* 0 admin roles held by EOAs on all 3 chains. [Safe on HSK](https://docs.hskchain.net/docs/Build-on-HashKey-Chain/Tools/Safe)
2. **Invariant + static-analysis CI.** Add Foundry invariants (Σbalances = totalSupply; only verified holders; no execution without approval; dividend payouts ≤ funded), Aderyn, and a nightly Halmos run. *Effort:* S. *Metric:* ≥ 8 invariants, 0 High/Medium findings. [Aderyn](https://github.com/Cyfrin/aderyn), [Halmos](https://github.com/a16z/halmos)
3. **Valuation eval + red-team harness.** Build a 30-company golden set (stored reports) with promptfoo/Inspect in CI, plus injection pages aimed at OWASP Agentic ASI01 (goal hijack) and "human-agent trust exploitation" (persuasive narratives that sway the approver). *Effort:* S–M. *Metric:* MAE and drift tracked per release; 0 successful injections that change scores > 5 pts. [OWASP Agentic 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/), [Inspect](https://inspect.aisi.org.uk), [promptfoo](https://www.promptfoo.dev)
4. **Valuation attestation (EAS schema).** Emit an EIP-712 offchain attestation for each approved report (companyId, perShare, method, reportHash, approver) and anchor its UID in `AgentProvenance.uri`; register the schema on Sepolia/Ethereum, since HSK has no EAS. *Effort:* S. *Metric:* every approved valuation resolves on easscan. [EAS docs](https://docs.attest.org/docs/learn/on-vs-off-chain-attestations)
5. **On-chain alerting + tracing.** Run OZ Monitor on `AgentProvenance`/token (alert on role changes, forced transfers, `markExecuted` spikes). Add OTel FastAPI tracing plus self-hosted Langfuse, carrying one trace id from proposal to tx. *Effort:* S. *Metric:* alert < 1 min; 100% of issuer txs are traceable. [Langfuse](https://langfuse.com)

### Next (1–3 months)

6. **Calibrated valuation.** Replace LLM-cited multiples with versioned datasets ([Damodaran Jan-2026](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/psdata.html), [Equidam](https://www.equidam.com/revenue-multiples-by-industry-trbc/), [Carta Q1-2026](https://carta.com/data/state-of-private-markets-q1-2026/), [Cut Through AU](https://www.cutthrough.com/insights/state-of-australian-startup-funding-2025)), apply a private-company haircut, and cross-check with Scorecard/Berkus/VC method. Backtest on companies with consecutive priced rounds (round N → N+1, discounted). *Effort:* M. *Dep:* 3. *Metric:* median |log error| and ±30% hit rate published per stage.
7. **Scoped agent permissions (agent-economy core).** Use EIP-7702 + ERC-7579 session keys (ZeroDev policies or Rhinestone Smart Sessions) so the relayer agent can call only `claimFor` with a gas/day cap and expiry. Target Ethereum testnet first; on HSK use Safe + [Zodiac Roles v2](https://docs.roles.gnosisguild.org/) until a bundler exists. *Effort:* M. *Dep:* 1. *Metric:* relayer has no unrestricted key; out-of-policy calls revert. [ZeroDev permissions](https://docs.zerodev.app/sdk/permissions/intro), [Smart Sessions](https://docs.rhinestone.dev/smart-wallet/smart-sessions/overview)
8. **ERC-8004 agent identity/reputation.** Register agents in the 8004 Identity registry. Publish `AgentProvenance` outcomes (approval/override rate, later accuracy from item 6) as Reputation/Validation entries. *Effort:* M. *Metric:* reputation score shown per agent. [EIP-8004](https://eips.ethereum.org/EIPS/eip-8004)
9. **Real KYC.** Use FrankieOne or greenID for AU and VNPT/FPT eKYC for VN; Didit/Sumsub as a cheap global fallback. Accept the HashKey KYC SBT as an extra claim source on HSK. *Effort:* M. *Metric:* < 3 min median onboarding, no PII on-chain. [greenID](https://www.gbg.com/au/verify-identity/greenid-identity-verification/), [Didit pricing](https://didit.me/blog/top-10-kyc-providers-in-2026-features-pricing-comparison/)
10. **Legal path decision.** Pick one route: (a) partner with a licensed CSF intermediary or AFSL holder and act as their tech provider, or (b) a TCP licence ahead of 9 Apr 2027. RG 255 matters if SVI reads as advice. The ASIC sandbox ([INFO 248](https://www.asic.gov.au/for-business-and-companies/innovation-hub/enhanced-regulatory-sandbox-ers/info-248-enhanced-regulatory-sandbox/)) is narrow. *Effort:* M (external). *Metric:* signed legal memo plus a partner LOI.
11. **Cap-table depth.** Add ESOP pool + vesting (off-chain until exercise), SAFE/note conversion maths, share classes, and ASIC Form 484 export. *Effort:* M. *Metric:* feature parity checklist vs Cake for a seed-stage company.

### Later (3–9 months)

12. **Migrate to official ERC-3643 + ONCHAINID**, including modular compliance (country, max holders, lock-up) and DvD. Then run an independent audit ($15k–60k boutique, more at tier-1 *[verify]*) and write Certora specs for the transfer rule. *Effort:* L. *Dep:* 2, 9. [ERC-3643](https://github.com/ERC-3643/ERC-3643)
13. **Real stablecoin dividends** in AUDD (AFSL-issued; may fit ASIC's 2025 distributor class relief) or USDC/HKDAP on HSK *[verify native issuance]*. *Effort:* M. *Dep:* 10. [AUDD](https://www.audd.digital/)
14. **CCIP only where a remote contract must act on the root** (e.g., gating claims on Ethereum). Otherwise keep Merkle anchoring, which is cheaper and simpler; move the anchor signer to the Safe. *Effort:* M. [CCIP HSK](https://docs.chain.link/ccip/directory/mainnet/chain/ethereum-mainnet-hashkey-1)
15. **ZK selective disclosure.** Semaphore/Noir proofs of "verified AU/VN holder ≥ N shares" over a snapshot commitment, or Privado ID queries. The value is limited while balances are public. *Effort:* L. [Semaphore](https://docs.semaphore.pse.dev), [Privado/Billions](https://billions.network)
16. **Production chain**: ≥ 4 independent validators, then HSK mainnet. **Open-source SDK** of the provenance + approval-gate pattern. *Effort:* L.

## 2b. Business track (added 2026-09-27, plan only)

The technical items above run next to a business track with scored stage gates. Full plan:
[PLAN-BUSINESS.md](PLAN-BUSINESS.md), go-to-market + 26-week revenue plan [PLAN-GTM.md](PLAN-GTM.md) (targets A$1k Nov 26 → A$10k/mo Mar 27 → A$50k/mo Dec 27) (VI summary: [PLAN-BUSINESS.vi.md](PLAN-BUSINESS.vi.md)); gate results go in [GATES.md](GATES.md). Billing: [PLAN-BILLING.md](PLAN-BILLING.md) + [STRIPE-SETUP.md](STRIPE-SETUP.md) (live at G0 + 7 days, 7-day card trials); revenue model and mainnet move: [PLAN-REVENUE-MODEL.md](PLAN-REVENUE-MODEL.md); first real case: [SELF-VALUATION.md](SELF-VALUATION.md).

| Stage | Main work | Gate to leave it |
|---|---|---|
| S0 Hackathon (now) | stable demo, judging | **G0** judging result recorded, judging caps restored, traffic baseline exported |
| S1 Foundation (~4 wks) | unified users + login/event/presence tracking + `/admin/analytics`; usage ledger; remove admin/admin; backups; legal pages; demo/prod split; metered AI API | **G1** 11-point readiness score |
| S2 Paid pilot (wks 5–12, Nov–Dec 2026) | one-off reports paid via Stripe Checkout from early Nov (people A$49, passport A$59, valuation A$299); recruiters + 2 angel groups + 2 accelerator perks; Pulley migration campaign (to 8 Dec); privacy ADM disclosure by 10 Dec; plans shadow-priced | **G2** real revenue / shadow MRR ≥ A$1.5k, MAU, activation, retention |
| S3 Paid beta (Jan–Mar 2027) | subscriptions live (Founder, Growth, angel group, recruiter); accountant partner programme; RCSA / JobAdder; OnMarket / Birchal LOI; VN SaaS + HR via PayOS; AFSL/TCP partner shortlist | **G3** MRR ≥ A$5k, churn < 5 %, AFSL/CSF partner signed |
| S4 Scale / white label | tenants by host, partner billing, transaction fees via licensed partner, mainnet path (items 1, 9, 10, 12, 13, 16) | quarterly review |

## 3. Top 10 ranked by impact ÷ effort

| # | Item | Impact | Effort |
|---|---|---|---|
| 1 | Safe 2-of-3 as admin, issuer narrowed (1) | Very high | S |
| 2 | Invariant tests + Aderyn/Halmos CI (2) | High | S |
| 3 | On-chain alerting + end-to-end tracing (5) | High | S |
| 4 | Valuation eval + red-team harness (3) | High | S–M |
| 5 | EAS valuation attestations (4) | Medium-high | S |
| 6 | Calibrated multiples + backtest (6) | Very high | M |
| 7 | Legal path decision (10) | Very high | M |
| 8 | Scoped agent session keys via 7702/7579 or Zodiac Roles (7) | High | M |
| 9 | Real KYC providers + HSK KYC SBT (9) | High | M |
| 10 | ERC-8004 agent identity/reputation (8) | Medium | M |

## 4. Risks

- **Regulatory:** tokenised Pty shares are securities. Without an AFSL partner, issuing, custody, dividends and secondary transfers are unlicensed activity. Also watch the Pty 50 non-employee holder cap (s113) and AUSTRAC tranche-2 and travel-rule duties. VN investors hit FX/outbound controls; Resolution 05/2025 excludes securities-backed tokens ([DFDL](https://www.dfdl.com/insights/legal-and-tax-updates/vietnam-government-sets-legal-framework-and-launches-pilot-program-for-tokenized-assets/)).
- **Valuation liability:** uncalibrated AI valuations used to price shares could be read as advice (RG 255) or as misleading. Ship ranges, methodology, and the backtest error with every report.
- **Key/infra:** a hot issuer key plus a single-validator chain means one compromise could rewrite the register. HSK itself has permissioned sequencing and instant upgrades.
- **Ecosystem gaps on HSK:** no EAS and no confirmed 4337 infrastructure. Design for Safe/Zodiac first, keep 4337 on Ethereum, and verify HSK support before promising it.
- **Vendor churn:** Defender is gone and promptfoo/Langfuse were acquired. Prefer self-hostable, open-source tools.
- **Human-approval fatigue:** four-eyes only works if approvers actually review. Measure time-to-approve and override rate, and red-team persuasive agent output.
- **Doc drift:** fixed on 26 Sep 2026 — `ARCHITECTURE.md` now describes the live Hoodi/HashKey, hot-key setup (the earlier Sepolia/Safe design is an appendix). Keep [FACTS.md](FACTS.md) as the single source of truth so docs, app copy and decks do not drift again.
