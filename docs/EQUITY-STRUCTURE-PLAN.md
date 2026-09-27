# BlockID Business Passport — equity structure plan (share classes, rounds, grants & vesting, dividends)

Status: **design proposal, not implemented** · Date: 27 Sep 2026 · Owner decisions needed: §13 ·
Related: [UPGRADE-INVESTOR-PLAN.md](UPGRADE-INVESTOR-PLAN.md) (offerings 3f, dividends 3e), [ARCHITECTURE.md](ARCHITECTURE.md),
[SECURITY.md](SECURITY.md), [FACTS.md](FACTS.md) (wording rules).

> Testnet demo. Not an offer of securities or financial advice. Legal and tax points below are research notes for
> product design, not legal or tax advice.

## 1. Summary

- **Goal.** Let each business on eth.blockid.au set up and run its whole share structure: share classes, groups
  (founders & leaders, board, tech, marketing, operations, employee pool, advisors, investors by round, reserve),
  issuance rounds with a dilution preview, grants to people with vesting, lock-ups, buybacks and dividends per class —
  with the same rule as the rest of the product: *Agents propose. Humans approve. Chains prove.*
- **Three case studies** (chosen for the best primary data and because together they cover the three business types
  we serve):
  1. **Facebook 2004–2012** (final IPO prospectus on SEC EDGAR) + 2025–26 Carta / Index Ventures / Cooley benchmarks →
     the *VC-backed startup* path: seed → Series A/B → IPO, dual-class, RSUs, staggered lock-ups.
  2. **Arbitrum ARB** (official allocation + dated vesting; Uniswap UNI as second reference) → *published allocation
     and vesting rules*: 4 years, 1-year cliff then monthly, fixed supply with a capped, vote-gated mint; plus two
     clear lessons (cliff overhang, AIP-1 "ratify after spending").
  3. **John Lewis Partnership** (audited 2025/26 report) + **Exodus / Securitize** (tokenised common stock through a
     registered transfer agent) + **ERC-3643** → *employee ownership and regulated tokenised equity*.
- **Recommended design.** Plan off-chain, shares on-chain. A versioned, approved **share structure** (classes,
  groups, targets, plan limits) with three templates (Early startup · VC-backed growth · Employee-owned business).
  **Grants vest off-chain and are minted on vest** through the existing `studio.mints` → issuer path (no contract
  change for the MVP). **One token per share class** (the current `BlockIDShareToken` already carries `shareClass`;
  this is also how ERC-3643 models classes), each with its own `DividendDistributor`. **Rounds** reuse the mint
  dilution preview and link to the existing simulated offering. **Four-eyes** inside each company (today a manager can
  approve their own mint). Contract work (partial freeze / per-holder lock, optional `VestingVault`, ERC-3643
  migration) is phase 3.
- **Phases.** P0 hackathon MVP (structure + grants + vesting + My grants, 5–7 days) → P1 rounds and pre-emption
  (1.5–2 weeks) → P2 classes, dividends per class, buybacks, leavers (2–3 weeks) → P3 token v2 / vault / ERC-3643,
  SAFEs, production (4–6 weeks + audit).

---

## 2. Research

Method: four parallel research passes (VC cap tables, token allocations, employee ownership + security-token
standards + employee share schemes, SME dividends), primary sources first (SEC filings, official docs, ATO/ASIC,
annual reports). Where only secondary sources were available this is marked *(secondary)*. Full source list: §14.

### 2.1 Why these three case studies

| Candidate | Data available | Verdict |
|---|---|---|
| **Facebook** | Final 424B4 prospectus with filled-in share counts, votes, RSUs, options, plan reserves; full private round history in press | **Chosen** (VC path) |
| Airbnb | Preliminary S-1 leaves ownership/voting % blank; useful ideas (Class H host endowment, double-trigger RSUs, Series C anti-dilution top-up) | Comparison |
| Atlassian / Canva | Atlassian: votes vs shares only (founders ~87% votes with ~41% shares, 2023); Canva private, estimates only | Comparison |
| **Arbitrum ARB** | Official docs give % + token amount + dated vesting per group; documented governance failure | **Chosen** (token path) |
| Uniswap UNI | Official launch blog: exact splits, treasury vesting table, contract mint cap; cliff not stated | Second reference |
| Optimism OP / ENS | OP official table removed (trackers only); ENS has no investor class | Comparison |
| **John Lewis Partnership** | Audited 2025/26 report, constitution, 75-year trust history, bonus history | **Chosen** (employee-owned path) |
| Exodus (EXOD) via Securitize | Reg A+ filing, company FAQ; tokenised common stock, registered transfer agent, NYSE American listing | Token-layer companion to JLP |
| Mondragon, tZERO, INX | Not researched in depth (INX used only for its published dividend rule) | Not chosen |

### 2.2 Case study 1 — Facebook (VC-backed startup → IPO)

**Rounds and dilution**

| Date | Round | Amount | Lead | Valuation (post) | Stake sold |
|---|---|---|---|---|---|
| mid-2004 | Seed (angel) | US$0.5M | Peter Thiel | ~US$4.9M implied | ~10.2% |
| May 2005 | Series A | US$12.7M | Accel | US$87.5–98M (sources differ) | ~13–14% |
| Apr 2006 | Series B | US$27.5M | Greylock, Meritech, Accel | US$500M | ~5.5% |
| Oct 2007 | Strategic | US$240M | Microsoft | US$15B | 1.6% |
| May 2009 | Growth | US$200M | DST | US$10B (down round) | ~2% |
| Jan 2011 | Late private | US$500M | Goldman Sachs, DST | US$50B | ~1% |
| 18 May 2012 | IPO | US$16.0B gross at US$38 | Nasdaq | ~US$104B | 421M shares (180M new) |

**Ownership by group at IPO** (post-IPO 2,138M shares; Class A 1 vote, Class B 10 votes)

| Group | Stake | Notes |
|---|---|---|
| Founder/CEO (Zuckerberg) | ~22% economic after IPO (~28% before); ~55.9% of votes | Class B + voting agreements over 883M shares |
| Other co-founders | Moskovitz 7.6%, Saverin ~5%, Hughes ~1% | |
| Series A lead (Accel) | 11.4% | sold up to 28% of its stake at IPO |
| Late-stage (DST) | ~5.5% | |
| Employees: RSUs + options + reserve | ~25–28% (calc.) | 378M pre-2011 RSUs (~17.7%), 25M later RSUs, 117M options, 77.5M plan reserve |
| Board / C-level separately | not extracted | |

**Vesting, lock-ups, classes, dividends, governance**
- Employee equity moved from options to **double-trigger RSUs** (time served + liquidity event); settlement at IPO
  with ~45% tax withheld (~US$4.6B). Airbnb did the same (≈US$2.7B expense at IPO).
- **Staggered lock-up** instead of one date: ~271M shares (Aug 2012), ~234M (Oct), ~777–800M (Nov) — nearly 2B shares
  over ~9 months *(press)*.
- **Dual class** (A = 1 vote, B = 10 votes, convertible 1:1): Class B ≈ 96% of votes; "controlled company". Airbnb:
  B = 20 votes, C = 0, **H = 0 votes for a host endowment** — a model for a community/customer allocation.
- Dividends: none planned (growth company). Private VC deals in Q2 2026: 1x liquidation preference 95.8%,
  non-participating 96.4%, accruing dividends only 3%, pay-to-play 8.4% (Cooley).

**2025–26 benchmarks (Carta via secondary summaries; Index Ventures; YC; Cooley)**

| Metric | Value |
|---|---|
| Founding team ownership, median | ~56% after seed · ~36% after Series A (Carta 2026) |
| Dilution per round, median | seed 19.5% · A 18% · B 14% · C 10% |
| Employee option pool | seed ~12% → Series C ~17% (Carta); seed 10–20%, A 12–15% (EU), US late stage ~20% (Index) |
| Executive grants (fully diluted) | C-suite 0.8–1.5% (CTO/COO up to 2%); VP 0.3–0.8% at A (Index) |
| Staff grants by role (% of salary) | eng director 75%, senior eng 50%, eng IC 33%, marketing/finance director 33%, sales IC 5% (Index) → tech gets the largest share of the pool |
| Advisors | median 0.21% (2024): pre-seed 0.21%, seed 0.12%, A 0.05%; 2 years, 3-month cliff (Carta) |
| Vesting standard | 4 years, 1-year cliff, then monthly |
| SAFE | post-money SAFE (YC standard since 2018): cap-only, discount-only, MFN; pro-rata by side letter; ownership = investment ÷ post-money cap |
| Anti-dilution | broad-based weighted average is standard; full ratchet rare |

### 2.3 Case study 2 — Arbitrum ARB (published allocation and vesting), with Uniswap UNI

| Group | ARB (10B supply) | UNI (1B supply) | Vesting |
|---|---|---|---|
| DAO treasury / reserve | 35.28% | 43% (inside 60% "community") | UNI treasury 40/30/20/10% per year; ARB DAO by vote |
| Team + contributors (+ advisors) | 26.94% | team 21.27%, advisors 0.69% | ARB: 4 years, first unlock 1 year after launch (16 Mar 2023), then monthly for 3 years; UNI: 4 years |
| Investors | 17.53% | 18.04% | same as team |
| Users (airdrop) | 11.62% + 1.13% to DAOs building on it | 15% | liquid at claim |
| Foundation (operating budget) | 7.5% | — | linear 4 years from 17 Apr 2023 |
| Liquidity mining / ecosystem | — | 2% | — |

- **Minting:** fixed genesis supply; new tokens only by holder vote, **at most 2% per 365 days** (UNI, OP and ENS enforce
  it in the contract; ARB states it in docs). None has automatic inflation.
- **Governance:** UNI 2.5M UNI to propose, 40M quorum, 2-day timelock; ENS 100k to propose, 1% quorum; ARB 12-member
  Security Council acting 9-of-12, changes take ≥27–42 days end to end.
- **Distributions:** none pays dividends. UNI's fee switch waited 5 years and was turned on in Dec 2025 as a
  **burn** (plus a one-off 100M UNI burn); OP approved **buybacks** with 50% of network revenue (Jan 2026).
- **Lessons:** (1) ARB's first cliff released 1.11B tokens in one day, ~87% of what was circulating → prefer small
  monthly steps and stagger group cliffs. (2) **AIP-1:** the Foundation moved and sold part of 750M ARB before a vote it
  called "ratification"; >70% voted against; it was redone with a 4-year on-chain lock and spending reports →
  approve before moving shares, lock budgets, report against them. (3) OP's published supply did not reconcile
  with trackers (~125.5M gap) → one canonical register that matches the chain.

**What we take:** the 4y / 1y cliff / monthly rule, dated public schedules, reserve that needs approval to use, a
yearly cap on new issuance, and "approve first" — all already natural in our gate model.

### 2.4 Case study 3 — John Lewis Partnership (employee-owned), with Exodus/Securitize and ERC-3643

| Item | John Lewis Partnership |
|---|---|
| Ownership | 100% held by John Lewis Partnership Trust Ltd for ~63,800 employees ("Partners"); trust since 1929, full transfer 1950 |
| Share class | 612,000 "deferred ordinary" £1 shares, **1,000 votes each** on a poll, all in the trust |
| How employees benefit | no individual shares; a yearly **Partnership Bonus**, the same % of salary for every eligible Partner, instead of dividends |
| Bonus history | historically 5–20%; 3% (2019), 2% (2020), 0% (2021, first miss since 1953), 3% (2022), 0% (2023–25), **2% (FY2026, £35m on £134m profit before tax, bonus and exceptionals)** |
| Governance | Partnership Council (elected, ~855 representatives across 47 constituencies), Partnership Board (incl. elected directors), Chairman; constitution changes need both Council and Chairman; Council elects 3 Trustees |
| Transfers | none (no tradable shares); a legacy employee share plan (BonusSave, closed 2020) was redeemable at cost |

**Exodus (EXOD)** shows the regulated token layer: US$75M Reg A+ raise (2021), Class A common stock as tokens
(Algorand, later Solana), **every transfer and conversion through Securitize, an SEC-registered transfer agent**,
listed on NYSE American in Dec 2024. The token is a *digital representation* of registered shares — the same stance
as our "share register on blockchain".

**Security-token standards**

| Feature | ERC-3643 (T-REX) — Final since 15 Dec 2023 | ERC-1400/1410 (draft only) | ERC-1404 (draft) |
|---|---|---|---|
| Share classes | one token per class; classes can share one identity registry | partitions inside one token | one token per class |
| Vesting | mint up front + `freezePartialTokens`, or mint on vest | a locked partition moved on vest | custom restriction code |
| Lock-up (e.g. AU 3-year) | partial freeze or compliance module | lock-up partition | restriction code |
| KYC | native (ONCHAINID, claims, trusted issuers) | off-standard | custom |
| Forced transfer / clawback | `forcedTransfer` (agent) | controller transfer (ERC-1644) | — |
| Lost key | `recoveryAddress` | controller transfer | — |

Our `IdentityRegistry.isVerified`, `forcedTransfer`, `setFrozen` and `pause` already follow ERC-3643 names and
behaviour; the missing parts are partial freeze, recovery and pluggable compliance.

### 2.5 Employee share schemes (high level, not advice)

| | Australia | Vietnam |
|---|---|---|
| Tax concession | **Start-up concession** (Div 83A): unlisted, every group company < 10 years old, turnover ≤ A$50M, Australian resident employer; shares at ≤ 15% discount or options at/above market value; **held ≥ 3 years**; discount not taxed, gain taxed as a capital gain on sale (50% discount available); employee may hold ≤ 10% | Employees pay 0.1% of the sale price on transfer of ESOP shares *(secondary; 2025 PIT changes not checked)* |
| Taxing point (other schemes) | deferred up to 15 years; leaving a job is no longer a taxing point (from 1 Jul 2022) | — |
| Disclosure / offer rules | Corporations Act Div 1A of Part 7.12 (from 1 Oct 2022; replaced ASIC class orders): unlisted paid offers capped at **A$30,000 per participant per 12 months** (+70% of dividends and bonuses); guidance in ASIC RG 49 | Public companies: Securities Law 2019 + Decree 155/2020 — shareholder approval, **≤ 5% of outstanding shares per 12 months**, file with the SSC. Private JSCs: private placement under the Law on Enterprises 2020 (< 100 offerees, no mass media); lock-up set by the plan (a 1-year lock is widely quoted but **not verified**) |
| Holder limit | proprietary company: ≤ 50 non-employee shareholders (s113) | JSC private placement: < 100 offerees |

**Product consequences:** employee flag on every holder; 3-year lock option; A$30k/12-month check on paid offers;
10% per-employee warning; VN 5%/12-month issuance cap option; all as warnings and settings, not legal advice.

### 2.6 Dividends for SMEs

| Topic | Australia | Vietnam |
|---|---|---|
| When a dividend may be paid | s254T: assets exceed liabilities by enough to pay it; fair and reasonable to shareholders as a whole; no material prejudice to creditors. Test per company, at decision and at payment; keep a written solvency record. Directors usually **"determine"** (revocable until paid) rather than "declare" (creates a debt) | Law on Enterprises 2020 Art. 135: taxes and financial duties met, required funds set aside and past losses covered, still able to pay debts; pay in full **within 6 months of the AGM**, 15 days' notice; cash, shares or other assets |
| Tax on the dividend | **Franking**: base-rate entity (turnover < A$50M, ≤ 80% passive income) franks at 25%, others 30%; **benchmark rule** — same franking % for all dividends in a period; tell the ATO if it moves > 20% between periods; private company statements within 4 months of year end | **5% PIT withheld** for individuals; none for corporate shareholders |
| Share classes | preference rights in the constitution or by special resolution (s254A); in Australia preference dividends are more often non-cumulative; "alphabet" classes added to a company with retained profits to stream franked dividends are dividend stripping (ATO TD 2014/1) — a class set up from the start is outside that ruling | per charter |
| Employee equity | unvested RSUs/options get no dividends (no share yet); restricted shares usually do; RSUs often get "dividend equivalents" (US practice, ~90% pay on restricted stock) | — |
| Tokenised practice | snapshot at record date → Merkle claim in a stablecoin (Uniswap merkle-distributor pattern — what our `DividendDistributor` does). INX: 40% of cumulative adjusted operating cash flow, record date 31 Mar, paid by 30 Apr, company-held tokens excluded | same |

**Product consequences:** per-class dividend rule and rank; "determined → paid" wording; solvency attestation field
(AU) / Art. 135 checklist + 6-month timer (VN); franking % with a benchmark check and 5% VN withholding shown as
"production only"; unvested grants excluded from the record-date snapshot; reserve/unissued never counts.

---
## 3. What already exists (reuse, do not rebuild)

Everything below is live on https://eth.blockid.au and covered by tests. The equity-structure module sits on top of it.

| Area | What exists today | File / route | How the new module reuses it |
|---|---|---|---|
| Share token | `BlockIDShareToken`: ERC-20, **1 token = 1 share** (decimals 0), `issue(to, n, resolutionRef)` / `cancel(from, n, ref)` by `ISSUER_ROLE`, receiver must pass `IdentityRegistry.isVerified`, **one global** `lockupUntil` (immutable, deployed as 0), per-wallet `frozen` (whole balance), `pause`, `forcedTransfer` (bypasses lock-up/freeze, receiver still KYC'd), `maxShareholders` cap with live `shareholderCount`, `shareClass` string (deployed as `"ORD"`), `legalDocHash`, `anchorValuation` | `contracts/src/BlockIDShareToken.sol`, deploy in `issuer/service.py:_ensure_token` | One token **per share class** (the contract already carries `shareClass`); `issue` with `resolutionRef = keccak("studio-grant:<id>:<tranche>")` for vesting mints; `cancel` for buybacks/forfeits of issued-but-locked shares; `setLegalDocHash` for the approved structure document |
| Identity / KYC | `IdentityRegistry` (ERC-3643-style `isVerified`, country, expiry, KYC hash only) + KYC request queue | `IdentityRegistry.sol`, `studio/transfers.py` `POST /v1/companies/{tk}/kyc` | Every grantee must be KYC'd before any share is minted to them (same queue) |
| Dividends | `DividendDistributor` per token: Merkle rounds, stablecoin (mAUD), relayer `claimFor` (holder pays no gas), `closeRound` reclaims; pro-rata allocation `agents/dividend.py:allocate`; **standing dividend policy** (payout ratio or fixed, monthly/quarterly, cap per round, veto window 1–168 h, admin approves once) | `DividendDistributor.sol`, `studio/dividend_policy.py`, `routes.py` `POST /v1/companies/{tk}/dividends` | Per-class entitlement = run the existing allocation per class token and per class rule; policy table gets a `class_code` column |
| Mints | Mint request → approval → issuer `/mint` (KYC + gas drip first, idempotent `studio-mint:<id>` ref, re-anchors Hoodi/HashKey) with a **dilution preview** (before/after bars + table) | `routes.py` `POST /v1/companies/{tk}/mints`, `/v1/admin/mints/{id}/approve`, `Company.tsx` `MintForm` | Vesting tranches and round allocations become ordinary `studio.mints` rows (new FK columns), so the issuer path does not change |
| Offerings | Simulated offering: terms + frozen information pack (sha256) → admin approval → open → reservations (FCFS, per-investor cap, holder cap, 5-day cooling-off) → close → settlement approval → ONE issuer job mints all allocations | `studio/offerings.py`, `studio.offerings`, `studio.reservations`, `mints.offering_id`, `Offerings.tsx` | An investor round in a plan **links** to an offering (`rounds.offering_id`); pre-emption offers can reuse reservations with a wallet allow-list |
| Transfers | `free` mode (token unpaused) or `approval` mode (token paused, admin approves, issuer `forcedTransfer`) | `studio/transfers.py`, `issuer/transfers.py` | Lock-ups for grant shares are enforced by `approval` mode today; per-holder locks come with token v2 (§8) |
| Roles | Company admins: `owner` (manage admins + everything), `manager` (request **and approve** mints, dividends, transfers, KYC of that company); platform admins (SIWE wallets in `ADMIN_WALLETS`) | `studio/company_admins.py` `CompanyAuthz` | New roles `board` and `viewer`; **four-eyes** added for equity actions (see §7 — today a manager can approve their own mint) |
| Agent provenance | `AgentProvenance` (HashKey): AI output hash → a **different** wallet approves → `markExecuted` | `AgentProvenance.sol` | Suggested structures/grants from the assistant are recorded as proposals (kind `equity_plan`, `grant_batch`) |
| Updates, KPIs | Periodic business updates with net profit, approved and hash-anchored | `studio/updates.py` | Dividend policy per class keeps using published profit; milestone vesting can reference a KPI (e.g. ARR ≥ X in a published update) |
| People | HR team reports list people with `kind` founder / cofounder / executive / employee / advisor and role | `studio/hr.py`, `hr_store.py` | "Import people from team report" pre-fills grants in the right group |
| Audit | Hash-chained `studio.audit`, `studio.events` shown on Activity | `routes.py` `audit()` | Every plan/round/grant transition is audited; the plan hash is anchored |
| UI | Company workspace rail (`WS` in `lib/flow.ts`): overview · updates · offering · cap-table · transfers · mint ◆ · dividends ◆ · activity · team; admin queues `valuations, issuance, sync, mints, dividends, policies, updates, offerings`; investor portal `/i` (holdings, dividends, reservations); design tokens in `styles.css` (`.kpis/.kpi`, `.card.solid`, `.pill`, `.gatecard`, `.gaterow`, `Donut`, `Bars100`, `HBars`) | `web/app/src/pages/*.tsx`, `lib/flow.ts`, `styles.css` | New sections plug into `WS` and `QUEUES`; charts and tiles are reused as is |

**Gaps this module fills (all NEW):** no share classes beyond one `ORD` token; no concept of groups/pools or
"authorised vs issued"; no grants, vesting, cliffs or milestones; no per-holder lock-up (only a global one, set to 0);
no round plan with pre-money/price and pre-emption; no buyback flow; dividends are one rule for all holders;
no four-eyes inside a company; no employee/non-employee flag (the 50 non-employee shareholder limit of an
Australian proprietary company, s113 Corporations Act, cannot be checked).

---

## 4. Design principles

1. **Agents propose. Humans approve. Chains prove.** The assistant may draft a structure, a round or a batch of grants;
   a named person approves; only approved rows reach the issuer; the approved document hash goes on-chain.
2. **Off-chain plan, on-chain shares.** Groups, pools, targets and unvested grants are *plans and promises*
   (database + hashed document). Only **issued shares** are tokens. This matches the law: an unvested option or
   promise is not a share, and it keeps dividends and the holder count correct.
3. **Reuse the issuer path.** Every new share goes through `studio.mints` → issuer `/mint`. No new signing code in
   the MVP.
4. **One token per share class** (ERC-3643 practice: one token contract per class/instrument), not partitions inside
   one token. It keeps `DividendDistributor` (bound to one token) working unchanged per class.
5. **Approve before, never ratify after** (Arbitrum AIP-1 lesson): no share moves before the approval that covers
   it; standing approvals (vesting schedules, dividend policy) are bounded by caps written into the approved text.
6. **Small, dated, published steps** (Arbitrum cliff-overhang lesson): monthly vesting after the cliff, and cliffs of
   different groups on different dates; every schedule is visible to holders in advance.
7. **Plain words** in the UI (docs/FACTS.md): "shares you will receive", "vested", "locked until", "fair value";
   never "returns", "yield", "guaranteed", "earn". Legal line on every screen: *Testnet demo. Not an offer of
   securities or financial advice.*

---

## 5. Concepts and vocabulary (EN / VI)

| Concept | Meaning in the product | EN label | VI label |
|---|---|---|---|
| Share structure (plan) | Versioned, approved document: classes, groups, pool sizes, limits | Share structure | Cơ cấu cổ phần |
| Share class | Legal class with its own rights; one token each | Share class | Loại cổ phần |
| Group | Stakeholder bucket inside a class (Founders & leaders, Board, Tech, Marketing, Operations, Employee pool, Advisors, Seed investors, Series A investors, Reserve) | Group | Nhóm |
| Plan limit ("authorised") | Most shares the board approved for the company / a group. Australian companies have no legal authorised capital since 1998, so this is a **board-approved limit**, not a legal cap; for a Vietnamese JSC it maps to shares authorised for offering | Plan limit | Hạn mức theo kế hoạch |
| Issued | Shares that exist as tokens in a holder's wallet | Issued | Đã phát hành |
| Pool | Shares reserved for a group but not yet granted | Unallocated pool | Quỹ chưa phân bổ |
| Grant | Promise of N shares to a person, with a vesting schedule | Grant | Cấp cổ phần |
| Vesting | When granted shares become the person's | Vesting schedule | Lộ trình nhận cổ phần |
| Cliff | First date anything vests | Cliff | Thời gian chờ |
| Vested / unvested | Received vs still to come | Vested / Not yet vested | Đã nhận / Chưa nhận |
| Lock-up | Shares held but not transferable until a date | Locked until | Khóa chuyển nhượng đến |
| Round | One approved issuance event (founding, seed, Series A, pool top-up, rights issue, offering) | Round | Đợt phát hành |
| Pre-emption | Existing holders may buy their pro-rata share of a new round first | First right to buy | Quyền ưu tiên mua |
| Dilution | Change of each holder's % after a round | Dilution preview | Xem trước mức pha loãng |
| Buyback | Company buys shares back and cancels them | Buyback | Mua lại cổ phần |
| Forfeit | Unvested part ends when a person leaves | Forfeited | Bị hủy phần chưa nhận |

---

## 6. Functional design

### 6.1 Share structure (plan) and templates

A company has **one active structure version** at a time (`equity_plans`, versioned). A structure contains:

- **Classes** (1..n): code (`ORD`, `PREF-A`, `NV-EMP` non-voting employee), voting (yes/no), dividend rule
  (ordinary pro-rata · fixed rate % of issue price · participating), rank for dividends and on wind-up, transferable
  (yes / with approval / no), default lock-up days.
- **Groups** (1..n): name, kind (`people` · `pool` · `investors` · `reserve`), class, **target %** of fully diluted,
  plan limit (shares), default vesting schedule, employee flag (counts or not toward the 50 non-employee limit).
- **Company limits**: plan limit (total shares), max holders (on-chain `maxShareholders`), max non-employee holders
  (off-chain check, 50 for a Pty), pre-emption on/off by default, board approvals needed (1 or 2).

**Fully diluted shares** = issued + granted-not-yet-issued + unallocated pools. Every % in the UI says which base it
uses ("of issued" vs "fully diluted").

**Templates** (starting points; every number editable; derived from the case studies in §2):

| Group (class) | **A. Early startup** (after seed) | **B. VC-backed growth** (after Series A) | **C. Employee-owned business** |
|---|---|---|---|
| Based on | Carta seed medians + Index Ventures; Facebook seed/Series A history | Carta Series A medians; Facebook/Airbnb classes and RSUs | John Lewis Partnership trust + AU ESS start-up concession |
| Founders & leaders (ORD) | 60% (typical 56–65%) | 40% (typical 36–47%) | 40% (original owners) |
| Board (ORD) | 1% | 1% | 1% (incl. an employee-elected director) |
| Employee pool (ORD, or NV-EMP non-voting) | 12% (typical 10–15%) | 15% (typical 12–17%) | 15% individual grants (ESS) |
| · split by team (inside the pool) | Tech 60 · Marketing/Growth 20 · Operations 20 | Tech 55 · Marketing/Growth 20 · Operations 15 · Leaders reserve 10 | equal-per-person or % of salary (JLP uses one % for all) |
| Employee trust (one wallet held for all staff) | — | — | 30% (JLP: 100% in trust) |
| Advisors (ORD) | 1% (0.1–0.25% each) | 1% | — |
| Seed investors (ORD or PREF-S) | 20% (typical dilution 18–20%) | 16% | — |
| Series A investors (PREF-A, 1x non-participating) | — | 20% (typical dilution ~18%) | — |
| Outside investors (ORD) | — | — | 10% |
| Reserve (unissued, future rounds) | 6% | 7% | 4% |
| **Vesting defaults** | leaders and staff 4 y, 1 y cliff, then monthly; advisors 2 y monthly, 3-month cliff | same + double-trigger acceleration option for leaders | yearly grants, 3-year holding lock (AU start-up concession), no cliff |
| **Issuance guard-rail** | reserve use needs board + admin approval | max 5% new shares per 12 months without a shareholder vote (after UNI/OP 2%/yr mint caps and VN public ESOP 5%/yr) | same, and employee-elected board approval for any new class |
| **Dividend default** | none (growth) | none; PREF-A fixed-rate right only when declared | yearly payout ratio of profit to all shareholders (optional equal-% staff bonus outside the register, like JLP) |
| **Approvals** | owner + platform admin (four-eyes) | 2 board approvals + platform admin; Series A consent for a new class | 2 board approvals (one employee-elected) + platform admin |

Each field shows the typical range and its source as a hint (e.g. "Employee pool after Series A: typical 12–17%,
Carta"). The three templates are starting points, not advice.

### 6.2 Process (end to end)

```
 STRUCTURE                 ROUNDS                          GRANTS & VESTING                 DIVIDENDS
 ─────────                 ──────                          ────────────────                 ─────────
 pick template             plan round (kind, price,        add person to a group,           per-class rule
 edit classes/groups       new shares, split by group)     amount, schedule, start date     (policy per class)
 [suggested draft]         dilution preview per holder     KYC wallet (existing queue)      published update
 submit                    pre-emption window (opt.)       submit batch                     with net profit
 ◆ board approval(s)       ◆ board approval(s)             ◆ board approval (four-eyes)     → declared per class
 ◆ platform admin          ◆ platform admin                ◆ platform admin (batch)         → veto window
 active v1 (hash on-chain) → execute: mints rows /         → vesting events scheduled       → issuer pays via
                             offering link / deploy class  → due tranche → mint (issuer)       DividendDistributor
```

### 6.3 Rounds

Round kinds: `founding` (first issuance — today's shareholder step), `priced` (seed, Series A/B: price per share,
pre-money), `pool_topup` (increase employee pool, no new shares until granted), `rights_issue` (pre-emptive offer
to all holders), `offering` (links to the existing simulated offering), `bonus` (free shares pro-rata), `conversion`
(SAFE/note converts at cap/discount → shares; phase 3).

Round fields: kind, class, price per share (default = latest approved fair value per share), pre-money, new shares
per group, holder-level allocations (optional), pre-emption (off / pro-rata offer with closing date), resolution
document hash, linked offering id.

**Dilution preview** (before approval, reused chart components): table per holder and per group — shares before,
% before (issued and fully diluted), shares after, % after, Δ percentage points, value at round price (labelled
"at round price, not a promise of value"). Warnings: founders below 50% (control), non-employee holders > 50,
pool below template minimum, price below last approved fair value by > 20%.

**Pre-emption**: when on, each existing holder gets `floor(new_shares × holding / issued)` entitlement; they accept
in the investor portal (a reservation with an allow-list), unaccepted shares go to the round's new investors.

**Execution**: approved round → one `studio.mints` row per allocation (`round_id` set) → the existing issuer
settlement pattern (one job, idempotent refs) → re-anchor. Pool top-ups create no mints.

### 6.4 Grants and vesting

Schedule types: `immediate`; `cliff_linear` (cliff months, total months, interval monthly/quarterly);
`milestone` (list of {label, shares or %, evidence: "published update KPI ≥ X" or "board confirms"}); `hybrid`
(time + milestone). Options: acceleration on sale (single / double trigger), leaver rule (good leaver keeps vested,
bad leaver: company may buy back vested at lower of cost/fair value — flagged "needs legal advice").

**Mint mode** (per plan, default *mint on vest*):

| Mode | How | Pros | Cons | When |
|---|---|---|---|---|
| **Mint on vest** (MVP) | Unvested = DB promise. On each vest date the tranche becomes a `studio.mints` row covered by the grant's standing approval → issuer mints to the person's wallet | No contract change; unvested never gets dividends or votes; forfeits are just "cancel future tranches"; holder count correct | Chain shows only vested shares (the promise is proven by the plan hash + grant hash on-chain) | Default |
| Mint upfront, locked (v2) | All granted shares minted to a `VestingVault` (KYC'd as the vault) or to the person with a per-holder lock; released by schedule | Full grant visible on-chain | New contract + audit; unvested shares count in supply (dividend and vote rules needed); forfeit needs `cancel` | Later, for investors asking for on-chain vesting |

The grant approval is a **standing approval** (like the dividend policy): tranches that match the approved schedule
mint automatically; anything off-schedule (acceleration, change of amount) needs a new approval.

**Leaver**: owner marks "left on date" → future tranches `forfeited`, shares return to the pool; vested shares stay
(optional buyback, §6.6).

### 6.5 Dividends per class

- `dividend_policies` gains `class_code`; one policy per class (e.g. PREF-A fixed 8% of issue price per year when
  declared; ORD payout ratio of profit after preference). Wording: "A dividend is paid only when the board declares
  it" (never "guaranteed").
- Waterfall when a profit-based dividend is declared: preference classes first (fixed-rate amount, cumulative
  arrears tracked off-chain if the class says so), then ordinary pro-rata. Each class = its own token and its own
  `DividendDistributor` round (existing contract, unchanged).
- Unvested grants receive nothing (they are not shares). Optional "dividend equivalent" for unvested grants is
  out of scope.
- Every declared round records a **solvency check** by the approving director (AU s254T: "assets exceed liabilities
  by enough, fair to all shareholders, creditors not harmed"; VN Art. 135 checklist + 6-month-after-AGM deadline) and
  uses the wording "determined" until it is paid.
- Australia (production only, disabled fields on testnet): franking % per round, franking credit shown on the
  holder statement, TFN withholding; the company stays responsible for tax. Vietnam: 5% PIT withholding on
  dividends to individuals (display only).

### 6.6 Buyback and cancellation

Holder or company proposes → price, shares, reason → holder consent (holder signs in the portal) → ◆ board +
platform admin → issuer `cancel(from, n, keccak("studio-buyback:<id>"))` (existing function; the payment leg is
simulated on testnet) → re-anchor. Forfeited **unissued** tranches need no chain action. Australian rule of thumb:
bought-back shares are cancelled (companies generally cannot hold their own shares), so there is **no treasury
wallet holding shares**; "Reserve" is always unissued.

---

## 7. Approvals, roles and audit

| Action | Proposes | Approves (company) | Approves (platform) | On-chain effect |
|---|---|---|---|---|
| Structure (new version) | owner / manager / assistant draft | board: 1 or 2 approvals (setting), approver ≠ proposer | platform admin | `setLegalDocHash(planHash)` on each class token; `AgentProvenance` record if drafted by the assistant |
| New share class | owner | 2 board approvals | platform admin | issuer deploys token + distributor for the class, syncs mirrors |
| Round | owner / manager | board (≠ proposer) | platform admin | mints (via `studio.mints`), re-anchor |
| Grant batch | owner / manager / assistant (from team list) | board (≠ proposer) | platform admin (batch) | none until vest; each tranche mint carries `studio-grant:<id>:<n>` |
| Vest tranche (on schedule) | automation | covered by grant approval (standing) | covered | mint |
| Off-schedule change (acceleration, amount) | owner | board | platform admin | mint / none |
| Leaver / forfeit | owner / manager | board | — (notice to admin) | none (unissued) |
| Buyback | holder or owner | holder consent + board | platform admin | `cancel` |
| Dividend policy per class | owner / manager | board | platform admin (once) | rounds per class |

Roles: existing `owner`, `manager` + NEW `board` (can approve, cannot propose money moves alone) and `viewer`
(read-only, e.g. accountant). **Four-eyes rule (NEW, fixes a gap):** for every equity action the approving wallet
must differ from the proposing wallet (same rule as `AgentProvenance`); a company with only one admin needs the
platform admin as the second pair of eyes. Every transition writes `studio.audit` + `studio.events`; approvals are
stored in `equity_approvals` with the hash of what was approved, so a later edit cannot reuse an old approval.

---

## 8. Smart-contract impact

### 8.1 What the current contracts already support

| Need | Supported today? | How |
|---|---|---|
| Several share classes | Yes (one token each) | Deploy another `BlockIDShareToken` with `shareClass = "PREF-A"`; each has its own `DividendDistributor` |
| Mint on vest | Yes | `issue(to, n, ref)` with a grant/tranche ref |
| Cancel (buyback / forfeit of issued shares) | Yes | `cancel(from, n, ref)` |
| Plan document proof | Yes | `setLegalDocHash(planHash)` (+ `CapTableAnchor` roots after each mint) |
| KYC-only holders, holder cap | Yes | `IdentityRegistry.isVerified`, `maxShareholders` |
| Company-wide lock-up | Partly | `lockupUntil` is immutable and deployed as 0; use `approval` transfer mode (paused token) instead |
| Per-holder / per-grant lock-up | **No** | needs v2 (below) |
| Partial freeze | **No** | `frozen` is all-or-nothing |
| Upfront vesting on-chain | **No** | needs `VestingVault` |
| Class-aware dividends | Yes, by class token | one distributor per class token |

### 8.2 Recommendation (minimal change)

1. **MVP: no contract change.** Mint on vest, one token per class, lock-ups through `approval` transfer mode,
   plan hash via `setLegalDocHash`. Only new issuer job: *deploy an extra class token* (reuses `_ensure_token` with a
   different `shareClass` and symbol `TICKER-A`).
2. **v2 token (`BlockIDShareTokenV2`, new companies only):** add ERC-3643-shaped
   `freezePartialTokens(address, amount)` / `unfreezePartialTokens` (T-REX names) plus
   `setLock(address, amount, until)` so `_update` checks `balance - frozenTokens - locked(now) >= value`;
   `batchIssue(address[], uint256[], bytes32)` for rounds; keep `isVerified` surface. ~80 lines + fuzz tests.
3. **Optional `VestingVault`** (per company, only if on-chain vesting is demanded): holds minted unvested shares,
   KYC-registered as a vault, `release(grantId)` computes vested amount from immutable schedule params,
   `revoke(grantId)` by `ISSUER_ROLE` sends unvested to `cancel`. Vault shares are excluded from dividend Merkle
   plans and votes off-chain.
4. **Production:** migrate to the audited **ERC-3643 (T-REX) + ONCHAINID** suite (already in SECURITY.md), which
   natively has agent roles, `forcedTransfer`, `freezePartialTokens`, `recoveryAddress` and compliance modules
   (time-based transfer limits, max holders, country rules). Classes stay one token each. ERC-1400 partitions are
   **not** recommended (heavier, less tooling, not needed with one token per class).

### 8.3 Security review of the approach

| Risk | Mitigation |
|---|---|
| Issuer hot key mints outside the plan | Issuer checks, before every mint, that `issued_by_group + n ≤ group plan limit` and the tranche is due and approved; plan limit stored with the approved plan hash; nightly reconciliation (on-chain supply per class = Σ minted rows) raises an alert. Production: Safe multisig 2-of-3 as ISSUER (SECURITY.md) |
| Self-approval inside a company | Four-eyes rule (approver ≠ proposer) in `CompanyAuthz`, tested |
| Replay / double mint of a tranche | Deterministic `resolutionRef = keccak("studio-grant:<grant>:<tranche>")`; issuer's existing `_landed_issue` check scans for the ref before re-sending |
| Approval of a changed document | Approvals bind to `content_hash`; any edit returns the item to draft |
| Assistant (prompt-injected) proposes a bad structure | Assistant output is a draft only, schema-validated, numbers recomputed by code (sum of targets = 100%, limits), recorded in `AgentProvenance`; no key access (policy.py) |
| Forced transfer / cancel abuse | `cancel` only from an approved buyback/forfeit row with holder consent recorded; events surface on Activity and to the holder |
| Holder count breach (50 non-employee) | Off-chain check at grant/round approval; on-chain `maxShareholders` stays a hard backstop |
| Rounding | Integer shares only (decimals 0); remainders stay in the pool, shown |
| PII | Grantee names and emails stay in Postgres; on-chain only wallet + hashes (as today) |
| Contract changes (v2) | Fixed templates, Foundry fuzz + invariants (Σ locked ≤ balance, forced transfer respects KYC), Slither, external audit before real use |

---

## 9. Data model (append to `studio/schema.sql`, idempotent)

```sql
-- versioned share structure; exactly one 'active' per company
CREATE TABLE IF NOT EXISTS studio.equity_plans (
  id serial PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id) ON DELETE CASCADE,
  version int NOT NULL, template text,                       -- early_startup | vc_growth | employee_owned | custom
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','pending_board','pending_admin','active','superseded','rejected')),
  plan_limit bigint,                                          -- board-approved total shares (not legal authorised capital)
  max_non_employee_holders int, board_approvals_needed int NOT NULL DEFAULT 1, preemption_default boolean NOT NULL DEFAULT false,
  mint_mode text NOT NULL DEFAULT 'on_vest' CHECK (mint_mode IN ('on_vest','upfront_locked')),
  doc jsonb NOT NULL DEFAULT '{}', content_hash text, anchor jsonb, source text NOT NULL DEFAULT 'human', -- human | agent:<proposal id>
  created_by text, approved_by text, approved_at timestamptz, reason text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (company_id, version));
CREATE UNIQUE INDEX IF NOT EXISTS equity_plans_active_uidx ON studio.equity_plans (company_id) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS studio.share_classes (
  id serial PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id) ON DELETE CASCADE,
  code text NOT NULL, name text NOT NULL, voting boolean NOT NULL DEFAULT true,
  dividend_rule text NOT NULL DEFAULT 'pro_rata' CHECK (dividend_rule IN ('pro_rata','fixed_rate','participating','none')),
  fixed_rate_pct numeric, cumulative boolean NOT NULL DEFAULT false, rank int NOT NULL DEFAULT 0,
  transfer text NOT NULL DEFAULT 'approval' CHECK (transfer IN ('free','approval','none')),
  default_lockup_days int NOT NULL DEFAULT 0,
  local_token text, local_distributor text, hoodi_token text, hsk_token text, status text NOT NULL DEFAULT 'planned', -- planned|deploying|live|failed
  UNIQUE (company_id, code));
-- today's single token becomes class 'ORD' (backfill from studio.companies.local_token)

CREATE TABLE IF NOT EXISTS studio.equity_groups (
  id serial PRIMARY KEY, plan_id int NOT NULL REFERENCES studio.equity_plans(id) ON DELETE CASCADE,
  company_id int NOT NULL, key text NOT NULL, name text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('people','pool','investors','reserve')),
  class_code text NOT NULL, target_pct numeric NOT NULL CHECK (target_pct >= 0 AND target_pct <= 100),
  plan_limit bigint NOT NULL CHECK (plan_limit >= 0), is_employee boolean NOT NULL DEFAULT false,
  default_schedule_id int, sort int NOT NULL DEFAULT 0, UNIQUE (plan_id, key));

CREATE TABLE IF NOT EXISTS studio.vesting_schedules (
  id serial PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id) ON DELETE CASCADE, name text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('immediate','cliff_linear','milestone','hybrid')),
  cliff_months int NOT NULL DEFAULT 0, total_months int NOT NULL DEFAULT 0,
  interval text NOT NULL DEFAULT 'monthly' CHECK (interval IN ('monthly','quarterly','yearly')),
  milestones jsonb NOT NULL DEFAULT '[]', acceleration text NOT NULL DEFAULT 'none' CHECK (acceleration IN ('none','single','double')),
  lockup_months_after_vest int NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS studio.grants (
  id serial PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id) ON DELETE CASCADE,
  group_id int NOT NULL REFERENCES studio.equity_groups(id), schedule_id int NOT NULL REFERENCES studio.vesting_schedules(id),
  holder_name text NOT NULL, wallet text, account_id int, hr_person_id text,
  shares bigint NOT NULL CHECK (shares > 0), price_aud numeric NOT NULL DEFAULT 0, start_date date NOT NULL,
  is_employee boolean NOT NULL DEFAULT false,
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','pending_board','pending_admin','active','completed','left','cancelled','rejected')),
  left_on date, leaver text CHECK (leaver IN ('good','bad')), accepted_at timestamptz, content_hash text,
  source text NOT NULL DEFAULT 'human', created_by text, approved_by text, approved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS studio.vesting_tranches (
  id serial PRIMARY KEY, grant_id int NOT NULL REFERENCES studio.grants(id) ON DELETE CASCADE, n int NOT NULL,
  vest_date date, milestone text, shares bigint NOT NULL CHECK (shares > 0),
  status text NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled','due','awaiting_evidence','minting','minted','forfeited','failed')),
  mint_id int, lock_until date, UNIQUE (grant_id, n));
CREATE INDEX IF NOT EXISTS vesting_due_idx ON studio.vesting_tranches (status, vest_date);

CREATE TABLE IF NOT EXISTS studio.equity_rounds (
  id serial PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id) ON DELETE CASCADE, plan_id int,
  kind text NOT NULL CHECK (kind IN ('founding','priced','pool_topup','rights_issue','offering','bonus','conversion')),
  name text NOT NULL, class_code text NOT NULL DEFAULT 'ORD', price_aud numeric, pre_money_aud numeric, new_shares bigint NOT NULL,
  preemption boolean NOT NULL DEFAULT false, preemption_closes_at timestamptz, offering_id int,
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','pending_board','pending_admin','preemption_open','approved','executing','done','rejected','cancelled','failed')),
  dilution jsonb, content_hash text, resolution_hash text, source text NOT NULL DEFAULT 'human',
  created_by text, approved_by text, approved_at timestamptz, executed_at timestamptz, error text,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS studio.round_allocations (
  id serial PRIMARY KEY, round_id int NOT NULL REFERENCES studio.equity_rounds(id) ON DELETE CASCADE,
  group_id int, holder_name text, wallet text, shares bigint NOT NULL CHECK (shares > 0),
  source text NOT NULL DEFAULT 'new' CHECK (source IN ('new','preemption','pool')), accepted_at timestamptz, mint_id int);

CREATE TABLE IF NOT EXISTS studio.buybacks (
  id serial PRIMARY KEY, company_id int NOT NULL REFERENCES studio.companies(id) ON DELETE CASCADE, class_code text NOT NULL DEFAULT 'ORD',
  wallet text NOT NULL, shares bigint NOT NULL CHECK (shares > 0), price_aud numeric NOT NULL, reason text NOT NULL,
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','awaiting_holder','pending_board','pending_admin','approved','cancelling','done','rejected','failed')),
  holder_consent_at timestamptz, tx_hash text, created_by text, approved_by text, created_at timestamptz NOT NULL DEFAULT now());

-- approvals bound to the exact content that was approved (supports 2 board approvals + platform admin)
CREATE TABLE IF NOT EXISTS studio.equity_approvals (
  id serial PRIMARY KEY, item_kind text NOT NULL, item_id int NOT NULL, content_hash text NOT NULL,
  approver text NOT NULL, role text NOT NULL, decision text NOT NULL CHECK (decision IN ('approve','reject')), reason text,
  at timestamptz NOT NULL DEFAULT now(), UNIQUE (item_kind, item_id, approver));

ALTER TABLE studio.mints ADD COLUMN IF NOT EXISTS class_code text NOT NULL DEFAULT 'ORD';
ALTER TABLE studio.mints ADD COLUMN IF NOT EXISTS round_id int;
ALTER TABLE studio.mints ADD COLUMN IF NOT EXISTS tranche_id int;
CREATE UNIQUE INDEX IF NOT EXISTS mints_tranche_uidx ON studio.mints (tranche_id) WHERE tranche_id IS NOT NULL;
ALTER TABLE studio.dividend_policies ADD COLUMN IF NOT EXISTS class_code text NOT NULL DEFAULT 'ORD';
ALTER TABLE studio.dividends ADD COLUMN IF NOT EXISTS class_code text NOT NULL DEFAULT 'ORD';
ALTER TABLE studio.holders ADD COLUMN IF NOT EXISTS group_key text;
ALTER TABLE studio.holders ADD COLUMN IF NOT EXISTS is_employee boolean NOT NULL DEFAULT false;
ALTER TABLE studio.company_admins DROP CONSTRAINT IF EXISTS company_admins_role_check;
ALTER TABLE studio.company_admins ADD CONSTRAINT company_admins_role_check CHECK (role IN ('owner','manager','board','viewer'));
```
(`dividend_policies` has `UNIQUE(company_id)` today; change to `UNIQUE(company_id, class_code)`.)

### 9.1 State machines

```
PLAN     draft ──submit──▶ pending_board ──N board approvals (≠ proposer)──▶ pending_admin ──admin──▶ active
           ▲                    │ reject                                         │ reject          │ new version active
           └──── edit ◀─────────┴──────────── rejected ◀─────────────────────────┘                 ▼
                                                                                              superseded
ROUND    draft → pending_board → pending_admin → [preemption_open → (closes)] → approved → executing → done
                                                                                                  └─▶ failed → (re-approve) approved
GRANT    draft → pending_board → pending_admin → active ──all tranches minted──▶ completed
                                                   └── leaver ──▶ left (future tranches forfeited)
TRANCHE  scheduled ──date reached (time) / evidence approved (milestone)──▶ due ──automation──▶ minting ──▶ minted
             │                                          awaiting_evidence ◀┘                  └─▶ failed (retry)
             └── grant left/cancelled ──▶ forfeited
BUYBACK  draft → awaiting_holder → pending_board → pending_admin → approved → cancelling → done
```

---

## 10. API (NEW; same `CompanyAuthz`, CSRF and audit patterns as today)

| Method & path | Who | Does |
|---|---|---|
| `GET /v1/equity/templates` | anyone | the 3 templates with typical ranges and sources |
| `GET /v1/companies/{tk}/structure` | company admin/board/viewer | active plan + draft, classes, groups with issued / granted / unallocated per group, fully diluted totals |
| `PUT /v1/companies/{tk}/structure` | owner/manager | save draft (validated: Σ target = 100%, limits ≥ issued) |
| `POST /v1/companies/{tk}/structure/suggest` | owner/manager | assistant draft from template + HR team + current cap table (no keys; recorded as proposal) |
| `POST /v1/companies/{tk}/structure/submit` | owner/manager | → pending_board (content hash frozen) |
| `POST /v1/companies/{tk}/approvals/{kind}/{id}` `{decision, reason}` | board/owner/manager ≠ proposer | company approval for plan / round / grant batch / buyback |
| `POST /v1/admin/equity/{kind}/{id}/approve\|reject` | platform admin | final approval (new queues `structure`, `rounds`, `grants`, `buybacks`) |
| `GET/POST /v1/companies/{tk}/rounds`, `PUT /v1/rounds/{id}`, `POST /v1/rounds/{id}/submit` | owner/manager | plan a round |
| `POST /v1/rounds/{id}/preview` | company roles | dilution table per holder & group (pure calculation, no write) |
| `POST /v1/rounds/{id}/preemption/accept` `{shares}` | existing holder wallet | accept pro-rata entitlement |
| `GET/POST /v1/companies/{tk}/grants`, `PUT /v1/grants/{id}`, `POST /v1/companies/{tk}/grants/submit` `{ids[]}` | owner/manager | create/edit grants, submit a batch |
| `POST /v1/grants/{id}/accept` | grantee wallet | grantee accepts terms (hash) |
| `POST /v1/grants/{id}/leaver` `{left_on, leaver}` | owner/manager (board approves) | forfeit future tranches |
| `POST /v1/tranches/{id}/evidence` | owner/manager | milestone evidence (update id / note) → board confirms |
| `GET /v1/me/grants` | signed-in wallet/account | My grants: vested, not yet vested, next date, locks, dividends by class |
| `POST /v1/companies/{tk}/buybacks`, `POST /v1/buybacks/{id}/consent` | owner / holder | buyback flow |
| `POST /v1/admin/equity/run-automation` | platform admin | one vesting pass now (also a background loop like dividends/offerings) |

**Issuer jobs** (internal, `X-Internal-Token`, approved rows only): existing `/mint` for tranches, round allocations
and buyback is `/cancel` (NEW, thin wrapper over `token.cancel`); NEW `/deploy-class {class_id}` (deploy token +
distributor + mirrors for a new class); NEW `/anchor-plan {plan_id}` (`setLegalDocHash` on each class token);
v2 only: `/lock`.

**Automation** (`EquityAutomation.tick()`, API process, same shape as `DividendAutomation`): tranches whose
`vest_date ≤ today` and grant `active` → create `studio.mints` row `approved` with `approved_by = grant:<id>` →
issuer `/mint`; rounds whose pre-emption closed → allocate leftovers → `approved`.

---

## 11. UI / UX specification

### 11.1 Information architecture

Company workspace rail (`WS` in `lib/flow.ts`), NEW items marked ★, gates ◆:

```
Workspace · TICKER
  Overview
  Updates
  ★ Structure ◆        /c/:tk/structure     classes, groups, pools, plan limit, templates
  ★ Rounds ◆           /c/:tk/rounds        plan a round, dilution preview, first right to buy
  ★ Grants & vesting ◆ /c/:tk/grants        people, schedules, next vest dates, leavers
  Offering ◆           (existing; linked from a round of kind "offering")
  Cap table            (existing + group/class columns and "fully diluted" toggle)
  Transfers
  Mint ◆               (kept for one-off issues; shows "Tip: use Rounds or Grants")
  Dividends ◆          (existing + per-class policy tabs)
  Activity
  Team                 (existing + roles board / viewer)
  Check the records ↗
```

Investor portal: `/i` holdings gains a **"My grants"** card; NEW `/i/grants` and `/i/grants/:id`.
Admin console: NEW queues `structure`, `rounds`, `grants`, `buybacks` (gate = true) after `issuance` in `QUEUES`.

### 11.2 Screen: Structure (`/c/:tk/structure`)

Desktop (rail + main column; KPI tiles `.kpis`; donut + legend reused):

```
┌ rail ───────────┐┌ main ─────────────────────────────────────────────────────────────────────────┐
│ Workspace · CNV ││ StatusBar: Share structure v2 · Active · approved 12 Sep by 0xC400…a21F  [Edit] │
│  Overview       ││                                                                                │
│  Updates        ││ ┌kpi──────────┐┌kpi──────────┐┌kpi──────────────┐┌kpi──────────────┐          │
│ ★Structure ◆    ││ │Plan limit    ││Issued        ││Granted, not yet ││Unallocated pool │          │
│ ★Rounds ◆       ││ │12,000,000    ││8,400,000 70% ││issued 1.1M 9%   ││2.5M 21%         │          │
│ ★Grants ◆       ││ └─────────────┘└─────────────┘└─────────────────┘└─────────────────┘          │
│  ...            ││ ┌card: Groups (fully diluted) ───────────────────────┐┌card: donut ─────────┐  │
│                 ││ │Group            Class Target Issued Granted Pool  ││   ◯ 12.0M           │  │
│                 ││ │Founders&leaders ORD   40%   4.8M   –       –      ││  legend             │  │
│                 ││ │Board            ORD    1%   0.12M  –       –      ││                     │  │
│                 ││ │Employee pool    ORD   15%   0.3M   1.1M    0.4M   ││ [Issued|Fully dil.] │  │
│                 ││ │  · Tech 60%  · Marketing 20%  · Operations 20%    ││                     │  │
│                 ││ │Advisors         ORD    1%   –      0.08M   0.04M  ││                     │  │
│                 ││ │Seed investors   ORD   16%   1.92M  –       –      ││                     │  │
│                 ││ │Series A         PREF-A 20%  –      –       2.4M ⓘ ││                     │  │
│                 ││ │Reserve          –      7%   –      –       0.84M  ││                     │  │
│                 ││ └───────────────────────────────────────────────────┘└─────────────────────┘  │
│                 ││ ┌card: Share classes ──────────────────────────────────────────────────────┐   │
│                 ││ │ORD  Ordinary · votes · dividends pro-rata · transfers need approval · live│   │
│                 ││ │PREF-A Preference A · no vote · fixed 8%/yr when declared, paid first ·    │   │
│                 ││ │       planned (token created when the first round is approved)            │   │
│                 ││ └──────────────────────────────────────────────────────────────────────────┘   │
│                 ││ gatecard ◆ "Changes need 2 board approvals, then a BlockID admin."              │
│                 ││ Testnet demo. Not an offer of securities or financial advice.                   │
└─────────────────┘└────────────────────────────────────────────────────────────────────────────────┘
```

Edit mode = 3-step stepper (reuse `StepHead`): **1 Start from** (template cards: Early startup · VC-backed growth ·
Employee-owned business · Start blank; each shows a mini donut and "Based on: …" source line) → **2 Groups & classes**
(editable table; live Σ = 100% check; sliders for target %; "Split employee pool by team" sub-rows; warnings inline)
→ **3 Review & send** (diff vs active version, fully diluted donut before/after, who must approve, "Send for
approval"). "Suggest a draft" button fills step 2 from the template + team list; the result is labelled
"Suggested draft — check every number".

Empty state: "Your business has one share class and no groups yet. Pick a starting point — you can change every
number before anyone approves it." [Choose a template] · VI: "Doanh nghiệp của bạn mới có một loại cổ phần và chưa
có nhóm nào. Chọn một mẫu để bắt đầu — bạn có thể sửa mọi con số trước khi được phê duyệt." [Chọn mẫu]

### 11.3 Screen: Rounds (`/c/:tk/rounds`, `/c/:tk/rounds/:id`)

List: timeline of rounds (Founding → Seed → Pool top-up → Series A) as `.card.solid` rows with status pills.
Round editor (stepper): **1 Round type & price** (kind cards; price defaults to latest approved fair value per share,
warning if lower by > 20%) → **2 Who gets the new shares** (by group, optional named holders; first right to buy
toggle with closing date) → **3 Dilution preview** → **4 Send for approval**.

```
Dilution preview — Series A · 3,000,000 new PREF-A shares at A$2.40
┌ Bars100 before ───────────────────────────────────────────┐
│█████████ Founders 57% ███ Pool 13% ██ Seed 19% ...         │
└ Bars100 after ────────────────────────────────────────────┘
│███████ Founders 45.6% ██ Pool 10.4% ██ Seed 15.2% ███ Series A 20% │
 Holder / group      Before   After    Change    Value at round price*
 Founders & leaders  57.1%    45.7%    −11.4 pt  A$11.5M
 Employee pool       13.1%    10.5%    −2.6 pt   …
 Seed investors      19.0%    15.2%    −3.8 pt   …
 Series A (new)       –       20.0%    +20.0 pt  A$7.2M
 ⚠ Founders stay above 50% of votes? No — 45.7%.  ⚠ Non-employee holders after round: 38 / 50.
 * at the round price; not a promise of value.        [Base: fully diluted ▾]
```
VI column heads: Trước · Sau · Thay đổi · Giá trị theo giá đợt phát hành.

### 11.4 Screen: Grants & vesting (`/c/:tk/grants`)

```
KPI: Granted 1.18M · Vested 0.31M · Next vest 1 Oct (42,500 shares, 6 people) · Pool left 0.44M
Filters: [All groups ▾] [Status ▾] [Search person]            [+ Add grant] [Import from team]
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│Person        Group      Shares   Vested        Schedule          Next vest      Status        │
│Linh Tran     Tech       120,000  ████░░ 37%    4y · 1y cliff     1 Oct · 2,500  Active        │
│Sam Lee       Marketing   40,000  ░░░░░░ 0%     4y · 1y cliff     1 Mar 27 · 10k In cliff      │
│Ana Ruiz      Advisors    20,000  ███░░░ 50%    2y monthly        1 Oct · 833    Active        │
│Minh Do       Operations  30,000  ██░░░░ 25%    4y · 1y cliff     —              Left 30 Aug ▸ │
│3 drafts not sent                                                     [Send 3 for approval ◆]  │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```
Grant drawer (right side on desktop, full-screen sheet on phone): person, wallet (KYC status chip — "Verified",
"Waiting for check", "Not verified — ask them to verify"), group, shares (with "pool left after this grant"),
schedule picker with a **vesting chart** (step line: cliff, monthly steps; milestones as diamonds), start date, lock
after vest, employee yes/no, leaver rules text. Buttons: Save draft · Send for approval.

Empty state: "No grants yet. Give shares to your team over time: pick a person, an amount and a schedule. Shares
reach their wallet only when they vest." · VI: "Chưa có cấp cổ phần nào. Trao cổ phần cho đội ngũ theo thời gian:
chọn người, số lượng và lộ trình. Cổ phần chỉ vào ví khi đến hạn nhận."

### 11.5 Investor / employee view: My grants (`/i/grants`)

```
┌ My grants ─────────────────────────────────────────────────┐
│ CNV · Tech team · Ordinary shares                          │
│ ┌kpi Vested──┐┌kpi Not yet vested┐┌kpi Next vest─────────┐ │
│ │ 45,000     ││ 75,000           ││ 1 Oct 2026 · 2,500   │ │
│ └────────────┘└──────────────────┘└──────────────────────┘ │
│ Vesting chart (step line, "today" marker, cliff label)      │
│ In your wallet: 45,000 shares · locked until 1 Oct 2027     │
│ Dividends received on these shares: A$1,240 (mAUD)          │
│ [See the schedule]  [Check on the share register ↗]         │
│ Terms accepted 3 Jan 2026 · document hash 0x9f…            │
└────────────────────────────────────────────────────────────┘
```
Plain-words notes: "Shares you have not received yet do not get dividends and cannot be sold." · VI: "Cổ phần
chưa nhận thì chưa có cổ tức và chưa thể bán."
Pending action banner when a grant awaits acceptance: "Accept your grant" · "Chấp nhận cổ phần được cấp".
Pre-emption banner: "You can buy up to 12,400 new shares before others (until 15 Oct)" · "Bạn được quyền mua
trước tối đa 12.400 cổ phần mới (đến 15/10)".

### 11.6 Admin approval queue

Queues `structure ◆`, `rounds ◆`, `grants ◆`, `buybacks ◆` in `/admin/<queue>/<item>`, one item per screen as today.
Each item shows: what changes (diff), the dilution table, checks run by code (Σ = 100%, limits, holder counts,
KYC of every receiving wallet, four-eyes satisfied: "Proposed by 0xAB…, approved by board 0xCD…"), the content hash,
and the source ("Suggested draft by the assistant, proposal #41 on HashKey" when relevant). Buttons: Approve ◆ ·
Send back (reason required). Grants are approved as a **batch** with a per-row untick.

### 11.7 Components (reuse → new)

Reuse: `SideLayout`, `FlowRail/RailItem gate`, `StepHead`, `StatusBar`, `.kpis/.kpi`, `.card.solid`, `.pill`,
`.gatecard`, `Donut`, `Legend`, `Bars100`, `HBars`, `AddrCard`, `ErrorFix`, `DemoApproveGuide`.
New: `TemplatePicker` (cards with mini donut), `GroupTable` (editable, Σ check), `DilutionTable` (generalises
`MintForm` preview), `VestingChart` (SVG step line, theme tokens `--c1..c6`, `--gold-mark` for milestones),
`GrantDrawer`, `KycChip`, `ApprovalTrail` (who proposed / approved, with hashes).

### 11.8 Mobile behaviour

Rail collapses to the existing top section picker; KPI tiles 2 × 2; group and grant tables become stacked cards
(name + key number + status pill, tap to expand); the grant drawer becomes a full-screen sheet with a sticky
primary button; dilution preview shows the two `Bars100` and a 3-column table (Holder · After · Change); no
horizontal page scroll (tables scroll inside `.tbl`). Touch targets ≥ 44 px.

### 11.9 Copy rules

Buttons say what happens: "Send for approval", "Approve structure", "Mint vested shares" (admin only). No
"returns/yield/guaranteed/earn"; "value at round price" always carries "not a promise of value". The legal line is
in the footer of every new screen. Technical names (Merkle, issuer, ERC-3643) stay on `/verify`, `/hsk` and admin.

---

## 12. Phased plan

| Phase | Scope | Effort (1 dev + Claude) | Demo value |
|---|---|---|---|
| **P0 — Hackathon demo (MVP)** | Templates (read-only 3) · Structure screen with groups and targets (single class ORD) · Grants & vesting with `cliff_linear` + mint-on-vest automation (reuses `studio.mints` + issuer `/mint`) · four-eyes check · My grants card · admin `grants` queue · seeded demo (CNV: 6 grants, one tranche vests live during the demo via "vest now" admin button on testnet) | **5–7 days** | "Pick a template → grant shares to the team → approve → shares land in the wallet on the vest date" |
| **P1 — Rounds** | Rounds with dilution preview, pool top-up, link to existing offering, pre-emption (reservations with allow-list), board role, plan versioning + hash anchoring (`setLegalDocHash`) | 1.5–2 weeks | Seed → Series A story with dilution |
| **P2 — Classes & dividends per class** | `/deploy-class`, PREF class, per-class dividend policy and waterfall, buybacks (`/cancel`), leaver flow, milestone vesting tied to published updates, HR import | 2–3 weeks | Preference vs ordinary dividends |
| **P3 — On-chain vesting & production** | `BlockIDShareTokenV2` (partial freeze + per-holder lock + batchIssue), optional `VestingVault`, SAFE/convertible note conversion, ERC-3643/ONCHAINID migration path, Safe multisig issuer, audit, AU ESS paperwork export, franking fields live with a licensed partner | 4–6 weeks + audit | Production readiness |

### 12.1 Test plan

- **Unit (pytest):** vesting maths (cliff, monthly rounding, last tranche takes the remainder, leap years, month-end
  start dates), Σ target = 100%, plan-limit checks, dilution maths (issued vs fully diluted), pre-emption
  entitlement floors, waterfall per class, four-eyes (proposer cannot approve; single-admin company needs platform
  admin), content-hash binding (edit after approval → back to draft).
- **Postgres flows:** plan draft→active; grant batch → automation creates exactly one mint per tranche (unique index)
  even with two concurrent ticks; leaver forfeits only future tranches; round → mints → done; buyback → cancel.
- **Issuer (fake chain + evmd):** tranche mint idempotency via `resolutionRef` scan; deploy-class; re-anchor.
- **Contracts (Foundry, P3):** fuzz locked ≤ balance, partial freeze, forced transfer respects KYC, vault release
  monotonic and ≤ grant, revoke sends only unvested.
- **Web:** Playwright happy path (template → grants → approve → My grants shows vested), mobile 390 px snapshot,
  EN/VI dictionary completeness check, dark/light screenshots.

### 12.2 Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Legal: grants to Australian employees are an ESS (disclosure relief and tax rules) | Real use needs compliant documents | Testnet only; "needs legal advice" flags; P3 partner with ESS provider/lawyer |
| Scope creep (options, exercise price, SAFEs) | Misses demo | P0 = shares vesting only (RSU-like); options/exercise in P3 |
| Hot issuer key mints outside the plan | Wrong register | Code checks + reconciliation + Safe multisig in production |
| Users confuse "plan limit" with legal authorised capital | Wrong expectations | Label "board-approved limit" + tooltip per country |
| Chain noise: many small tranche mints | Mirror re-anchor churn | Batch the day's tranches into one job and one re-anchor |
| Dividend on unvested shares expected by staff | Complaints | Clear copy; optional dividend-equivalent later |

---

## 13. Open decisions for the owner

1. **Mint mode:** mint on vest (recommended, no contract change) or mint upfront into a vault/locked balance?
2. **Default templates:** approve the three templates and their numbers, or add a "Community / customer-owned" template
   inspired by token projects (large community/reserve share)?
3. **Approvals:** is one board approval + platform admin enough for small companies, or always two company approvals?
4. **Share classes in MVP:** ORD only for the hackathon (recommended) or show a PREF-A class in the demo?
5. **Employee shares class:** same ORD class, or a non-voting employee class (NV-EMP) by default?
6. **Pre-emption default:** on or off for new rounds?
7. **Lock-up for vested employee shares:** 0, 12 months, or 3 years (to match the AU start-up ESS concession
   holding period)?
8. **Milestone vesting evidence:** published update KPI only, or also a board confirmation?
9. **Token v2 / ERC-3643 timing:** P3 as planned or earlier for new companies?
10. **Vietnam:** confirm with a VN lawyer the ESOP transfer lock for private JSCs (a 1-year lock under Decree 155 is
    widely quoted but was not verified) and the 2024–25 securities-law amendments; show VN-specific wording (JSC "shares authorised for offering", 5% PIT on dividends) in P1 or later?

---

## 14. Sources

Case study 1 — Facebook and VC benchmarks
- Facebook final prospectus (424B4, May 2012): https://www.sec.gov/Archives/edgar/data/1326801/000119312512240111/d287954d424b4.htm
- Facebook S-1 (Feb 2012): https://www.sec.gov/Archives/edgar/data/0001326801/000119312512034517/d287954ds1.htm
- Facebook IPO overview: https://en.wikipedia.org/wiki/Initial_public_offering_of_Facebook
- Facebook funding timeline (Fortune): https://fortune.com/2011/01/11/timeline-where-facebook-got-its-funding/
- Facebook investors (CNBC): https://www.cnbc.com/2012/05/18/Facebook-Investors.html
- Facebook lock-up expiries: https://money.cnn.com/2012/08/15/technology/facebook-lockup · https://money.cnn.com/2012/11/13/technology/social/facebook-lockup/index.html
- Airbnb S-1 (Nov 2020): https://www.sec.gov/Archives/edgar/data/1559720/000119312520294801/d81668ds1.htm
- Airbnb Series B release: https://assets.airbnb.com/press/press-releases/Airbnb_PressRelease_SeriesB_07252011.pdf
- Atlassian founders' voting power (2023): https://www.businesswire.com/news/home/20230526005305/en/
- Canva employee share sale (2025): https://finance.yahoo.com/news/canva-billionaire-founders-minting-overnight-160559911.html
- Carta founder ownership 2026 (secondary summaries used): https://carta.com/data/founder-ownership-2026/ · https://waveup.com/blog/startup-dilution-per-round/
- Carta advisory shares: https://carta.com/learn/startups/equity-management/advisory-shares/
- Index Ventures, Rewarding Talent: https://www.indexventures.com/rewarding-talent/founders-investors-and-employees · https://www.indexventures.com/rewarding-talent/allocation-considerations-and-benchmarks
- Y Combinator SAFE documents: https://www.ycombinator.com/documents
- Cooley venture financing reports Q1/Q2 2026: https://www.cooley.com/news/insight/2026/2026-04-29-q1-2026-venture-financing-report · https://www.cooley.com/news/insight/2026/2026-08-17-q2-2026-venture-financing-report
- Broad-based weighted average anti-dilution: https://www.cooleygo.com/glossary/broad-based-weighted-average-anti-dilution-protection/

Case study 2 — Arbitrum, Uniswap, Optimism, ENS
- Arbitrum allocation and vesting: https://docs.arbitrum.foundation/airdrop-eligibility-distribution
- ArbitrumDAO constitution: https://docs.arbitrum.foundation/dao-constitution
- ARB cliff unlock (Mar 2024): https://finance.yahoo.com/news/arbitrum-unlock-1-2b-arb-061213848.html
- AIP-1 controversy: https://www.coindesk.com/business/2023/04/02/contentious-arbitrum-vote-over-1b-in-tokens-ratification-not-request-says-foundation · https://cointelegraph.com/news/arbitrum-s-first-governance-proposal-sparks-controversy-with-1b-at-stake
- Uniswap UNI launch: https://blog.uniswap.org/uni · contract: https://github.com/Uniswap/governance/blob/master/contracts/Uni.sol
- Uniswap governance: https://docs.uniswap.org/concepts/governance/process · fee switch (proposal 93): https://vote.uniswapfoundation.org/proposals/93 · burn: https://cointelegraph.com/news/uniswap-executes-100m-uni-burn-after-fee-switch-approval
- Optimism MintManager spec: https://specs.optimism.io/governance/mint-manager.html · OP buybacks: https://www.coindesk.com/business/2026/01/28/optimism-governance-approves-op-token-buyback-plan-tied-to-superchain-revenue · OP allocation (tracker): https://tokenomist.ai/optimism · supply mismatch: https://crypto.news/optimism-forecasts-343m-more-op-in-circulation/
- ENS token: https://basics.ensdao.org/ens-token · governance: https://docs.ens.domains/dao/governance/process/

Case study 3 — John Lewis Partnership, Exodus, standards
- JLP plc Annual Report and Accounts 2025/26: https://www.johnlewispartnership.co.uk/~/media/Files/J/john-lewis/corp/results-and-presentations/JLP-plc-Annual-Report-and-Accounts-2025-26.pdf
- JLP FY2026 results (bonus): https://www.johnlewispartnership.co.uk/media-centre/latest-news/2026/23872
- JLP Second Trust Settlement history: https://www.jlpjobs.com/blog/75-years-of-the-partnerships-second-trust-settlement/
- JLP overview and bonus history: https://en.wikipedia.org/wiki/John_Lewis_Partnership
- Exodus shares FAQ: https://www.exodus.com/support/en/articles/8722238-exodus-shares-exod-trading-faqs · Algorand token: https://www.prnewswire.com/news-releases/exodus-issues-security-token-on-algorand-expanding-access-to-the-growing-digital-security-ecosystem-301304582.html
- EIP-3643: https://eips.ethereum.org/EIPS/eip-3643 · Final status: https://www.erc3643.org/news/ethereum-community-approves-erc3643-as-the-first-tokenization-standard
- ERC-1400 / ERC-1410 / ERC-1404: https://github.com/ethereum/EIPs/issues/1411 · https://github.com/ethereum/EIPs/issues/1410 · https://github.com/ethereum/EIPs/issues/1404

Employee share schemes
- ATO key ESS changes: https://www.ato.gov.au/businesses-and-organisations/corporate-tax-measures-and-assurance/employee-share-schemes/in-detail/key-ess-changes-in-detail
- ATO start-up concession: https://www.ato.gov.au/businesses-and-organisations/corporate-tax-measures-and-assurance/employee-share-schemes/employers/types-of-ess/concessional-ess/start-up-concession-interests-acquired-after-30-june-2015
- ATO safe-harbour valuation and standard documents: https://www.ato.gov.au/businesses-and-organisations/corporate-tax-measures-and-assurance/employee-share-schemes/in-detail/safe-harbour-valuation-methods · https://www.ato.gov.au/businesses-and-organisations/corporate-tax-measures-and-assurance/employee-share-schemes/in-detail/standard-documents-for-the-start-up-concession
- ASIC ESS relief (22-370MR): https://www.asic.gov.au/about-asic/news-centre/find-a-media-release/2022-releases/22-370mr-asic-provides-legislative-relief-to-facilitate-employee-share-schemes/
- ESS A$30k cap: https://www.aghlaw.com.au/news/significant-updates-to-employee-share-schemes-in-australia · https://jws.com.au/what-we-think/long-awaited-employee-share-scheme-reforms-become-law/
- Vietnam ESOP, public companies: https://www.russinvecchi.com.vn/publication/esops-for-public-vietnamese-companies/ · https://plf.vn/regulations-and-conditions-to-implement-esop-in-vietnam/
- Vietnam ESOP, private JSCs: https://asialegal.vn/esop-of-normal-joint-stock-company/ · https://ptnlegal.com/en/legal-issues-to-note-when-businesses-implement-esop-programs/

Dividends
- s254T guide: https://www.minterellison.com/articles/how-to-pay-a-dividend-in-australia-a-guide · https://www.rsm.global/australia/insights/dividends-and-corporations-act-2001-when-can-you-declare-dividend
- Franking: https://www.ato.gov.au/businesses-and-organisations/corporate-tax-measures-and-assurance/imputation/paying-dividends-and-other-distributions/allocating-franking-credits · benchmark rule: https://www.ato.gov.au/businesses-and-organisations/corporate-tax-measures-and-assurance/imputation/paying-dividends-and-other-distributions/allocating-franking-credits/benchmark-rule · statements: https://www.ato.gov.au/businesses-and-organisations/corporate-tax-measures-and-assurance/imputation/paying-dividends-and-other-distributions/issuing-distribution-statements · base-rate entities: https://taxbanter.com.au/franking-considerations-base-rate-entities/
- Preference shares: https://legalvision.com.au/preference-share/ · https://www.bennettphilp.com.au/blog/preference-share-structures-in-australia-understanding-the-basics
- ATO TD 2014/1 (dividend access shares): https://www.ato.gov.au/law/view/document?DocID=TXD%2FTD20141%2FNAT%2FATO%2F00001&PiT=99991231235958 · https://www.smsfadviser.com/companies-with-more-than-one-share-class-should-consider-tax-risks
- Dividend equivalents: https://www.naspp.com/blog/Dividends-and-Equivalents-Ten-Things-to-Know
- Vietnam dividends (Art. 135, 5% PIT): https://english.luatvietnam.vn/legal-news/what-is-the-dividend-how-to-pay-the-dividend-4729-91135-article.html · https://globallawexperts.com/comprehensive-tax-compliance-guide-for-foreign-investors-in-vietnam/
- INX token holder rights: https://www.inx.co/inx-token-holder-rights/ · Merkle distributor: https://github.com/Uniswap/merkle-distributor

Source caveats: Carta pages returned 403 (figures via secondary summaries); some ATO pages returned 403 (facts via
ATO search snippets and law firms); OP figures come from trackers; the Vietnam 1-year ESOP lock and 2024–25 VN
amendments were not verified; Atlassian founder % at IPO only from an aggregator (not used in templates).
