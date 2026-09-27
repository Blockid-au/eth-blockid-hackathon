# BlockID — long-term revenue model (research + recommendation, 2026-09-28)

Status: **recommendation, owner-approved direction** (plan of 28 Sep 2026). Prices = price book v1 (`PLAN-GTM.md` §4).
VI summary: `PLAN-READY-TO-SELL.vi.md`. Not legal or tax advice — items marked ⚖ need a lawyer / accountant.

## 1. Options evaluated

| Option | Recurring? | Scales? | Regulatory load | Conflict of interest | Verdict |
|---|---|---|---|---|---|
| Per report (people / team / passport / valuation) | partly (packs, repeat) | yes | low (privacy, consent) | low | **Now** — fastest cash |
| Subscriptions (Founder / Growth / Angel / Recruiter) | yes | yes | low | low | **Now** — core recurring |
| Share-register administration (per holder per year, dividend admin, investor portal) | yes | yes | low while it is record-keeping | low | **Now** — "share management" |
| Transaction fees (issuance, transfers, dividends %, offering success fee) | per event | yes | **high** — arranging / custody of securities ⚖ | medium | **After** DAF (9 Apr 2027) + AFSL/TCP partner + audit |
| White label / platform licence | yes | medium | depends on partner | low | **2027** |
| Listing / fundraising advice | per mandate | low | **high** — advice / arranging needs AFSL ⚖ | high | Only through a licensed partner (referral fee) |
| 5 % equity from every company | no (illiquid) | no | medium ⚖ (tax, 50-holder cap) | **high** | **Not as default** — see §3 |
| Co-building the startup's blockchain platform (services) | project | limited by team | low | medium | Auschain services, optional equity via Venture Track |

Market anchor: tokenisation platforms charge issuers about **US$50–100k upfront, US$50–100 per investor and
US$5–25k a year** for digital transfer-agent services (Securitize, Tokeny — institutional minimums). SMEs are priced
out; BlockID can serve them at ~1/10 of that with software + a licensed partner for the regulated steps.

## 2. Recommended layered model

| Layer | Price (AUD) | Starts | Share of revenue at maturity (target) |
|---|---|---|---|
| 1 Reports | people A$49 (packs A$390/1,690), CV A$19, team A$199, passport check A$59, valuation A$299 / expert A$890 | after G0 | 25 % |
| 2 Subscriptions | Founder A$49/mo, Growth A$149/mo, Angel group A$199/mo (3 sponsored founder seats), Recruiter A$299/mo; 7-day trial, card required, cancel anytime | after G0 | 35 % |
| 3 Register administration | A$2 per holder per year above plan limit; dividend round admin A$150 flat (record-keeping, no money handling) | after G0 | 10 % |
| 4 Transaction fees (via licensed partner) | issuance A$490 per round; transfer A$15–25; dividends 0.5–1 % capped A$2,000; offering success fee 1–3 % shared with the intermediary | after 9 Apr 2027 + partner + audit | 15 % |
| 5 White label | setup A$5–15k; A$1.5–3k/mo; A$2–5 per holder per year; revenue share on layer 4 | 2027 | 15 % |
| 6 Venture Track (equity, opt-in) | 1–3 % warrant/SAFE for build work | selective | upside only, not budgeted |

Why this mix: layers 1–3 earn from day one without a licence and compound (every startup that joins brings
investors who are free users and future group-plan buyers — `PLAN-GTM.md`, investor-led loop). Layers 4–5 add
high-margin volume once the regulated path exists. Equity is upside, never the business model.

## 3. The "take 5 % of every company" idea — analysis

Problems if used as the default fee:
1. **Uncompetitive.** Accelerators take ~7 % for A$120k cash plus a network (Startmate). 5 % for software would
   cost a founder far more than A$588–1,788 a year.
2. **Tax without cash** ⚖. Shares received for services are generally assessable at market value when received —
   BlockID would pay tax on paper value it cannot sell.
3. **Conflict of interest.** BlockID sells independent valuations and checks; holding equity in the same companies
   undermines trust (and the four-eyes approval story).
4. **Licensing** ⚖. Helping a company list or raise and holding its shares can look like arranging / dealing in
   securities → AFSL (and, from 9 Apr 2027, DAF licences).
5. **Illiquid and capped.** Private shares may never pay out; a Pty company has at most 50 non-employee holders.

**Recommendation — "BlockID Venture Track" (opt-in, max 5 deals/year):** for startups where BlockID/Auschain builds
their blockchain platform or tokenisation stack as a project:
- reduced cash fee + **1–3 % via a warrant or SAFE** (not ordinary shares at signing);
- disclosed on the passport ("BlockID has an interest"), valuation reports for these companies carry the notice and
  need an independent approver;
- raising / listing work only through a licensed partner; BlockID takes a disclosed referral fee;
- accountant signs off the tax treatment before the first deal ⚖.

## 4. Pricing mechanics (how money is collected)
- Stripe (`STRIPE-SETUP.md`): Checkout for one-off reports (paid upfront), subscriptions with 7-day card-required
  trials, Customer Portal + in-app cancel, Stripe Tax for GST, invoices for B2B / white label (bank transfer).
- Register administration: metered per holder, billed annually on the subscription (Stripe quantity).
- Transaction fees (layer 4): invoiced by BlockID to the issuer after each event, or collected by the licensed
  partner and shared — **not** skimmed on-chain at first.
- Vietnam: PayOS (VietQR, no gateway fee) for VND when VN sales start.

## 5. Moving real shares to a low-gas mainnet ("same contracts, re-anchor the holders")

Preconditions: contract audit; Safe 2-of-3 as admin (today the issuer hot key holds every role —
`issuer/service.py:189-199`); AFSL / tokenised-custody partner; ERC-3643 decision (`SECURITY.md`). Earliest Q2–Q3 2027.

Target chain criteria: EVM-equivalent (the six contracts deploy unchanged), gas < US$0.01 per transfer, native USDC /
AUDD, Safe available, institutional acceptance. Shortlist: **Base** (OP Stack, same stack as HashKey) and **HashKey
Chain mainnet** (RWA focus, existing HSK work). Ethereum mainnet only for anchors.

Migration steps:
1. Add the chain to `contracts/foundry.toml` and `DeployPlatform.s.sol` (chain list is hard-coded at :50).
2. Generalise `issuer/service.py:32` and `issuer/syncstate.py:19-29` from fixed LOCAL/HOODI/HSK to a chain table.
3. Deploy per company with `DeployCompany.s.sol` (admin → Safe, deployer renounced).
4. Snapshot the register (`service.py:463-496`), re-register identities (registry is immutable per token),
   `issue` per holder with `resolutionRef` = snapshot block + Merkle root.
5. Pause the old token, write the final `CapTableAnchor` root on the old chains, check with `/verify/:tk`.
6. Gas: funded relayer or paymaster; `claimFor` keeps holders gas-free.

On-chain fees later (optional, needs legal review + a new audit): issuance fee in stablecoin at `issue`, basis points
on `DividendDistributor.createRound` to a treasury, or a separate FeeRouter. No fee-on-transfer (0-decimal shares).

## 6. Targets (from `PLAN-GTM.md` §5)
A$1k revenue Nov 2026 → A$10k/month Mar 2027 → A$50k/month Dec 2027; break-even ≈ A$3–5k/month.
