# BlockID — go-to-market strategy and revenue execution plan (2026-09-28)

Status: **PLAN — approved direction pending owner sign-off.** VI summary: `PLAN-GTM.vi.md`. Builds on
`PLAN-BUSINESS.md` (tracking, billing, gates) and `COMPANY.md` (Auschain Pty Ltd, BlockID™).
Market numbers come from public sources listed in §10; "[u]" marks figures that could not be verified on the
vendor's own page. Prices are AUD incl. GST for consumers and ex GST ("+GST") for business plans.

**One-line strategy:** make money first from **reports people already pay for** (people checks, business checks,
valuation reports), use them to pull founders and investors onto the **Business Passport** (cap table + investor
updates, subscription), and grow through **partners** (accelerators, angel groups, accountants, CSF platforms,
Vietnamese securities / exchange licensees) who later take **white label**. Tokenised-share transaction fees come
last, only through a licensed partner after the Digital Assets Framework starts (9 Apr 2027).

---

## 1. What the research says (Sep 2026)

| Finding | Evidence | What it means for BlockID |
|---|---|---|
| Recruiters already pay A$35–100 per check | Certn: reference A$35, employment verification A$34.90, **social media check A$66.99**, police A$85; Xref ≈ A$44–50 per candidate on entry plans | An AI people report at **A$39–59** is inside the price people expect; a team report can be A$149–249 |
| 8,518 recruitment businesses in AU, A$20.8B revenue | IBISWorld 2025 | Small total market: sell **credits**, not big subscriptions; reach through RCSA + ATS marketplaces |
| Candidates are covered by the Privacy Act; scraping public data can be "unfair collection" (OAIC v Clearview); automated-decision disclosure from **10 Dec 2026**; Fair Work s351 protected attributes | OAIC, law-firm notes | The HR product must be **consent-based** (candidate consents, sees and can dispute the report), never infer protected attributes or spent convictions — this becomes a selling point |
| Founders choose between free DIY valuation and A$1.5k+ accountant valuations | Equidam free / US$323 / US$834; AU accountants A$1.5k–7.5k for small businesses | **A$299 AI valuation report** and **A$890 expert-reviewed report** fill the gap |
| Business credit reports cost A$18–131 each | Equifax reseller list, CreditorWatch A$99–449/mo | A **Business Passport check (A$59)** that investors can open by link has no direct competitor |
| Cap-table tools: free up to 5–25 stakeholders, then ~US$1,000–3,500 a year | Cake (AU) free ≤5, Build US$1,000/yr; Carta free ≤25; Qapita free ≤25 | Founder plan **A$49/mo (A$490/yr)**, Growth **A$149/mo** — about half of Cake, with no surprise stakeholder cliffs |
| **Pulley is shutting down on 8 Dec 2026** and moving its customers to Carta | TechCrunch 16 Sep 2026 | Time-boxed campaign: "Move from Pulley free, keep a flat price" (Oct–Dec 2026) |
| Investor updates: free up to 100 investors; US$59–199/mo paid | Visible, Foundersuite | Include updates in the founder plans; don't sell them alone |
| ~5,150 startups; A$5.48B raised in 390 deals in 2025; ~56 accelerators; Sydney Angels 100+, Scale Investors ~250 angels | StartupBlink, Cut Through / ScaleSuite, Failory | Enough for a founder niche; accelerators + angel groups are low-cost channels. **SXSW Sydney 2026 is cancelled** — don't plan around it |
| Equity crowdfunding: ~A$40M over 49 raises in FY26; OnMarket 73 % share and requires a registry (partner **Boulevard**); Birchal cutting costs and "building tools beyond the raise"; Equitise and VentureCrowd's parent in administration | FinTech Australia, BNA, Startup Daily | Few new raises, but ~700+ post-raise companies [u]. **OnMarket / Birchal are white-label or partner targets**; Boulevard is the direct incumbent |
| Xero pays app partners **15 % revenue share** on referrals | Xero partner docs | Model for an **accountant referral programme** (20 % first year) |
| Freemium converts 3–5 % (5–7 % with sales help); card-upfront trials ≈ 49 % vs ≈ 18 % without a card; SMB CAC payback 8–12 months | ChartMogul, 1Capture, Benchmarkit | Plan funnel numbers on 3 % free→paid and pay-per-report as the main entry |
| Vietnam: 825 startups, US$509M VC (2025); ~78 securities firms; crypto pilot has **7 applicants, 0 licences** (Aug 2026); PDPL + Decree 356 from 1 Jan 2026 (explicit consent, transfer impact assessment within 60 days) | VnExpress, CryptoRank, DFDL | Sell **SaaS + HR** there; tech-vendor role to exchange applicants (CAEX / VPBank, TCEX / Techcombank); PayOS (no fee) for VND payments |
| AU tokenisation: DAF Act from 9 Apr 2027 (DAP / TCP need an AFSL); 45+ digital-asset AFSL applications; RBA/ASIC **DFMI sandbox H2 2027** | ASIC, RBA | Stay a software / record-keeping provider until then; partner with a new licensee (e.g. Zerocap-type); apply to the DFMI sandbox |

## 2. Positioning

- **Category:** "Business Passport" — a verified, shareable profile of a private business and its team, plus the
  share register and investor updates that keep it current after the raise.
- **Promise (public copy, FACTS.md rule: plain words):** "Know the business before you invest." For founders:
  "One link that answers every investor question." For recruiters: "Check a candidate's public track record in
  minutes, with their consent."
- **Why us:** AU-native (ASIC / ABN checks, AUD, ESS / ESIC aware), cheaper and faster than accountants, each report
  records its sources and is anchored on-chain (tamper-evident). No other product combines check + valuation +
  register + investor portal.
- **Proof we must build:** 10 named pilot logos, 3 case studies, method page with backtest error (valuation), consent
  and privacy page (HR).

## 3. Customers — ranked by speed to cash

| # | Segment | Pain | Entry product | Price | Channel | First cash |
|---|---|---|---|---|---|---|
| 1 | **Recruiters and in-house hiring managers** (SME, tech, exec search) | Reference and background checks are slow; CV claims are unchecked | People report (consent-based) | A$49 each; 10 for A$390; 50 for A$1,690; CV analysis A$19 | LinkedIn outbound, RCSA, JobAdder / Bullhorn marketplace (later) | **Month 1** |
| 2 | **Angel investors and angel groups** (Sydney Angels, Scale Investors, Melbourne / Brisbane Angels, syndicates) | Deal flow is unverified; founder due diligence is manual | Team report + Business Passport check on pipeline deals | Group plan A$199/mo for 10 checks, or A$59 per passport + A$149 per team report | Group admins, pitch nights, one free "deal check" per cycle | Month 1–2 |
| 3 | **Founders raising pre-seed → Series A** | Investors ask the same questions; valuation is guesswork; cap table in spreadsheets | Free passport → A$299 valuation report → Founder / Growth plan | Free / A$299 / A$890 / A$49–149 per month | Accelerator perks, angel groups ask founders for a passport, Pulley migration, content / SEO | Month 2 |
| 4 | **Accountants and startup lawyers** (Sprintlaw-type, Bentleys / Findex offices, boutique firms) | Clients need valuations, share registers (s169), ESS paperwork | Partner dashboard; client reports at partner price | 20 % referral, or buy reports wholesale at −30 % | Partner programme, CPD webinars | Month 3–4 |
| 5 | **Post-raise companies from CSF / private raises** | Many small shareholders, updates and dividends are painful | Growth plan + investor portal | A$149/mo; +A$2 per holder per year above 50 | OnMarket / Birchal alumni, Equitise orphans | Month 3–6 |
| 6 | **White label**: CSF platforms, accountant networks, VN securities firms / exchange applicants | Need a post-raise layer or a verified-profile layer under their brand | Branded tenant | Setup A$5–15k + A$1.5–3k/mo + usage | Direct partnership sales | Month 6–9 |
| 7 | **Tokenised-share flows** (issuance, transfers, dividends) | Paper registers, slow transfers | via licensed partner only | Issuance A$490, transfer A$15–25, dividends 0.5–1 % | AFSL / TCP partner | After Apr 2027 |

**Not now:** retail investors as paying users (keep free), large enterprises, US market (Carta), pure crypto users.

## 4. Price book v1 (replaces the §4.3 hypotheses in PLAN-BUSINESS.md)

| Product | Price | Anchor (why) |
|---|---|---|
| Business Passport — free | A$0: business check on screen, public passport link, cap table ≤ 10 holders, updates to 25 investors | Cake free ≤ 5, Visible free ≤ 100 investors |
| **Passport check report** (PDF + verified link, ABN/ASIC, risk signals, sources) | **A$59** | Equifax A$43–131, CreditorWatch ≈ A$45–50 per report |
| **Valuation report** (AI, ranges by method, benchmarks, PDF) | **A$299** | Equidam US$323 (≈ A$490); below the A$1.5k accountant floor |
| Valuation report, expert-reviewed (+ 30-min call) | **A$890** | Equidam Expert US$834 (≈ A$1,270) |
| **People report** (consent-based) | **A$49**; packs 10 = A$390, 50 = A$1,690 | Certn social media A$66.99, reference A$35, Xref ≈ A$44–50 |
| CV analysis add-on | A$19 | — |
| Team report (founding team, up to 6 people) | **A$199** | 4–6 individual checks |
| Founder plan | **A$49/mo or A$490/yr** +GST: 25 holders, updates to 250 investors, 1 valuation report / year | Cake Build US$1,000/yr |
| Growth plan | **A$149/mo or A$1,490/yr** +GST: 100 holders, unlimited updates, expert valuation / year, 3 admins | Cake Team US$2,750/yr, Visible Core US$129/mo |
| Extra holders | A$2 per holder per year (flat, no cliffs) | Cake +US$1–5 |
| Angel group plan | A$199/mo +GST: 10 passport or team checks per month, shared deal room | — |
| Recruiter team plan | A$299/mo +GST: 10 people reports / month, 3 seats; extra report A$35 | Xref Growth A$210/mo for 50 profiles/yr |
| White label | Setup A$5–15k; A$1,500–3,000/mo; A$2–5 per holder per year; revenue share on regulated fees via partner | Fintech white-label norms |

Rules:
- Every price is published; there is no "contact sales" below white label.
- The paid trigger is always a concrete deliverable, such as a report or a verified link.
- Pay-per-report is always available next to plans.
- Annual plans get 2 months free.
- Launch offer: the first 50 customers ("founding customers") get 30 % off for life, in exchange for a testimonial and a case study.
- Pulley migrants get 6 months free.
- AI cost per report must stay under 10 % of price. The ledger in `PLAN-BUSINESS.md` §3 proves this.

## 5. Unit economics and revenue model

- Variable cost per report: LLM ≈ US$0.01–0.50 on metered models, search ≈ US$0.01–0.05, Stripe 1.7 % + A$0.30. On a A$49 report, gross margin is **≈ 95 %**. The expert review costs about 1 hour of analyst time (≈ A$100–150).
- Fixed cost today: about A$300–600/mo for the VM, storage, email and domains. With paid APIs, insurance and tooling it becomes about A$1.5–3k/mo. Break-even is therefore **≈ A$3–5k/month** of revenue.

**Funnel maths to reach A$10k/month by March 2027:**

| Stream | Volume / month | Price | A$ / month |
|---|---|---|---|
| People reports (recruiters, founders hiring) | 100 | ~A$42 avg (packs) | 4,200 |
| Team + passport checks (angel groups, investors) | 20 | ~A$120 avg | 2,400 |
| Valuation reports | 8 | ~A$400 avg | 3,200 |
| Founder / Growth plans | 25 | ~A$80 avg | 2,000 |
| **Total** | | | **≈ 11,800** |

To produce those volumes:
- About 25 active recruiter accounts at 4 reports/month each. At a 20 % trial→paid rate, that needs about 125 trials.
- About 4 angel groups.
- About 800 free passports at a 3 % conversion to plans.

That in turn needs:
- 600 outbound contacts per month (LinkedIn + email, 5–8 % reply rate).
- 3–5 accelerator / angel partnerships.
- Pulley migration and SEO content running continuously.

**Targets (commit to these at G2; the actuals go in `GATES.md`):**

| Month | Oct 26 | Nov 26 | Dec 26 | Jan 27 | Mar 27 | Jun 27 | Dec 27 |
|---|---|---|---|---|---|---|---|
| Revenue / month (A$) | 0 | 1,000 | 3,000 | 5,000 | 10,000 | 20,000 | 50,000 |
| Paying customers | 0 | 15 | 40 | 70 | 130 | 250 | 550 |
| White-label tenants | — | — | — | — | LOI | 1 | 3 |

## 6. Change to the stage plan: charge earlier for one-off reports

`PLAN-BUSINESS.md` had shadow pricing only in the S2 free pilot. Because reports are non-regulated and people already
pay for them, the plan changes to **"paid pilot"**:

- **One-off reports go live for payment in S2** (week 5, early Nov 2026). They use Stripe Checkout / Payment Links (Auschain Pty Ltd, tax invoice, GST). This needs only webhook → credit, not the full subscription system.
- **Subscriptions** (Founder / Growth / group / recruiter plans) switch on when G2 passes, and stay shadow-priced until then.
- G2 now uses **real revenue** where it exists. Its target line becomes "real revenue ≥ A$1,500 in the last 30 days, or shadow MRR ≥ A$1,500".
- Anything regulated (issuance, transfers, dividends, offerings) stays on testnet / demo until a licensed partner is signed.

## 7. Execution plan — 26 weeks (Oct 2026 – Mar 2027)

Roles:
- **Owner / founder:** sales and partnerships, about 50 % of time.
- **Claude + developer:** product and ops.
- **Advisor / lawyer:** privacy, terms and AFSL memo.
- **Optional from month 3:** a part-time BD / recruiter-market contractor on commission.

### Phase A — Launch-ready (weeks 1–4, 29 Sep – 26 Oct 2026)

| Week | Sales and marketing (owner) | Product and ops (Claude / dev) | Exit check |
|---|---|---|---|
| 1 | Close G0 (record the judging result). Build ideal-customer lists in a CRM (HubSpot free / Attio): 300 recruiters, 50 angel-group contacts, 56 accelerators, 100 founders from the Startmate / Antler / Giants alumni, 20 accountants | Tracking foundation (`PLAN-BUSINESS.md` §3); remove admin/admin; nightly backups | G0 recorded |
| 2 | Write 3 outbound sequences (recruiter, angel, founder) and the founding-customer offer. Book 10 discovery calls from the owner's network and Auschain's clients | HR **consent flow**: candidate invite link, consent screen, candidate can view and dispute; protected-attribute and spent-conviction filters; Privacy / Terms / ADM disclosure drafts | 10 calls booked |
| 3 | Run 10 discovery calls (WTP questions, which report they'd buy today). Pitch 2 accelerators (perk) and 2 angel groups (deal-check pilot) | `/pricing` page (price book v1); Stripe Checkout for one-off reports (credits table + webhook); tax invoice email | Pricing live in test mode |
| 4 | Publish a "Pulley is closing — move your cap table free" page and email; LinkedIn posts from the founder profile (2/week) | Cap-table import (Pulley / Carta / Cake CSV); `/admin/analytics` v1; **score G1** | G1 passed |

### Phase B — First revenue (weeks 5–12, 27 Oct – 21 Dec 2026)

| Focus | Actions | Weekly metric |
|---|---|---|
| Recruiters | 150 contacts a week (LinkedIn + email); free first report; packs of 10 at the founding price. Aim for 1 recruiter case study by week 8 | Trials, paid packs, reports per account |
| Angels | 2 angel groups on a pilot: free deal checks for one cycle, then the group plan. Present at one pitch night | Checks run, founders invited to the passport |
| Founders | Accelerator perk live with ≥ 2 programs (3 months of the Founder plan free + 1 valuation report at 50 %). Pulley campaign until 8 Dec | Free passports, valuation reports sold |
| Content | 1 article per week: "How much is my startup worth in Australia", "ESS safe-harbour valuation explained", "Reference check vs public-record check" | Organic sign-ups |
| Compliance | Privacy policy with the automated-decision disclosure **live before 10 Dec 2026** | Done / not done |
| Product | Paid reports live (week 5); passport share link with viewer analytics (founders see which investors opened it); team report bundle | Report success rate, time to report |
| **Gate** | **Score G2 by week 12**, using real revenue from reports + shadow MRR from plans | G2 |

### Phase C — Subscriptions and channels (weeks 13–26, Jan – Mar 2027)

- Switch on the Founder, Growth, angel-group and recruiter plans in Stripe, with the customer portal and dunning.
- **Accountant partner programme:** 20 % referral in year 1, a partner dashboard, co-branded reports, and one CPD webinar per month. Target 10 firms.
- **Recruiter channel:** apply for the RCSA member benefit and the JobAdder marketplace listing (Bullhorn later).
- **CSF / registry partnerships:** pitch OnMarket and Birchal a post-raise investor portal + passport for their alumni, with a revenue share. Target 1 LOI by March.
- **Vietnam:**
  - Auschain / VBC network sells SaaS + HR (VI UI already exists) with PayOS for VND.
  - PDPL consent and transfer impact assessment (TIA) filed before the first VN customer data is transferred.
  - Tech-vendor pitch to 2 exchange applicants (CAEX, TCEX).
- **Licensing track:** shortlist 3 digital-asset AFSL holders / applicants (Zerocap-type) as TCP partner; legal memo; DFMI sandbox expression of interest (H2 2027).
- **Gate:** score G3 at the end of March 2027 (MRR, churn, partner signed).

### Phase D — Scale (Apr – Dec 2027, outline)

- White-label tenants (theming by host, tenant admins, partner billing).
- Regulated flows go live only through the partner after DAF starts (9 Apr 2027) and after the contract audit.
- Hire a sales lead once MRR ≥ A$20k.
- Consider a seed raise using real metrics from `/admin/analytics`.

## 8. Metrics dashboard (weekly review every Monday, from `/admin/analytics`)

Scope rule: count **real users only**; sample, demo and internal accounts are excluded.

**North star:** paid reports + active paid plans per week.

**Funnel, tracked by segment:**
1. Visitors
2. Sign-ups
3. First report
4. Paid
5. Repeat purchase within 30 days

**Revenue:**
- MRR
- One-off revenue
- ARPA
- Gross margin (AI cost from the ledger)

**Sales:**
- Contacts
- Reply rate
- Calls
- Trials
- Win rate
- CAC by channel (target payback < 6 months)

**Quality:**
- Report success rate
- Disputes raised by candidates
- NPS after each report

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| HR report seen as unfair collection or discrimination | Consent-first flow, candidate view and dispute, no protected attributes, sources shown, lawyer-reviewed wording, ADM disclosure |
| Valuation read as financial advice (RG 255) or relied on for pricing | "General information, not advice", method page, ranges not points, expert tier reviewed by a qualified person, PI insurance |
| Name clash with 1Kosmos "BlockID" | Clearance search before filing (`COMPANY.md` §3.1); use a composite mark if needed |
| Owner time split with Auschain work | Fixed weekly sales block (3 half-days); commission-only BD from month 3 |
| Small recruiter market | Recruiters are the cash engine, not the whole business; founders and partners are the growth engine |
| Partner platforms are financially weak (Equitise, VentureCrowd) | Prefer partners with licence and volume (OnMarket); take setup fees upfront |
| Incumbents (Carta, Cake, Boulevard) copy the features | Win on the AU bundle, the verified shareable passport, flat prices and partner distribution |

## 10. Sources

- **Pricing:**
  - [Cake Equity](https://www.cakeequity.com/pricing)
  - [Pulley pricing](https://pulley.com/pricing)
  - [Pulley shutdown](https://techcrunch.com/2026/09/16/pulley-a-carta-rival-is-shutting-down/)
  - [Qapita](https://www.qapita.com/pricing)
  - [Eqvista](https://eqvista.com/pricing/)
  - [Visible](https://visible.vc/pricing/)
  - [Foundersuite](https://foundersuite.com/pricing)
  - [Equidam](https://www.equidam.com/pricing/)
  - [CreditorWatch](https://creditorwatch.com.au/pricing/)
  - [Equifax reseller list](https://tascol.com.au/wp-content/uploads/2025/05/Client-Equifax-Price-List-2025.pdf)
  - [AU valuation cost](https://www.scalesuite.com.au/resources/how-much-does-a-business-valuation-cost-in-australia)
  - [ATO ESS safe harbour](https://www.ato.gov.au/businesses-and-organisations/corporate-tax-measures-and-assurance/employee-share-schemes/in-detail/safe-harbour-valuation-methods)
- **HR:**
  - [Certn ANZ](https://certn.co/anz/pricing/)
  - [CVCheck](https://help.cvcheck.com/article/show/49546-how-much-does-a-police-check-cost)
  - [Xref](https://www.xref.com/pricing)
  - [IBISWorld recruitment](https://www.ibisworld.com/australia/industry/employment-placement-recruitment-services/569/)
  - [OAIC employee records](https://www.oaic.gov.au/privacy/privacy-guidance-for-organisations-and-government-agencies/organisations/employee-records-exemption)
  - [OAIC Clearview](https://www.oaic.gov.au/news/media-centre/clearview-ai-breached-australians-privacy)
  - [Privacy reforms 2026](https://www.ashurstperkinscoie.com/en/insights/australias-2026-privacy-reforms-a-first-look-at-pivotal-new-changes/)
  - [Fair Work s351](https://www.austlii.edu.au/cgi-bin/viewdoc/au/legis/cth/consol_act/fwa2009114/s351.html)
- **Ecosystem:**
  - [StartupBlink AU](https://www.startupblink.com/startup-ecosystem/australia)
  - [AU funding 2025](https://www.scalesuite.com.au/resources/state-of-australian-startup-funding)
  - [Failory accelerators](https://www.failory.com/startups/australia-accelerators-incubators)
  - [Startmate partners](https://startmate.com/partner-with-startmate)
  - [Sydney Angels](https://www.sydneyangels.net.au/about-us)
  - [SXSW Sydney cancelled](https://www.smartcompany.com.au/technology/sxsw-sydney-2026-cancelled/)
  - [Xero partners](https://www.xero.com/au/partner/)
- **Conversion:**
  - [ChartMogul](https://chartmogul.com/reports/saas-conversion-report/)
  - [1Capture](https://www.1capture.io/blog/free-trial-conversion-benchmarks-2025)
  - [Benchmarkit](https://www.benchmarkit.ai/2025benchmarks)
- **CSF / tokenisation:**
  - [FinTech Australia CSF](https://www.fintechaustralia.org.au/newsroom/equity-crowd-sourced-funding-remains-stable-amid-major-funding-declines)
  - [FY26 CSF](https://www.businessnewsaustralia.com/articles/australias-equity-crowdfunding-market-storms-back-with-40-million-raised-in-fy26.html)
  - [OnMarket partners](https://www.onmarket.com.au/about-us/partners/)
  - [Birchal cuts](https://www.startupdaily.net/topic/business/birchal-cuts-jobs-and-costs-by-30-as-crowdfunding-flatlines/)
  - [RBA Acacia](https://www.rba.gov.au/payments-and-infrastructure/tokenised-money/project-acacia/)
  - [ASIC digital asset roadmap](https://www.asic.gov.au/about-asic/news-centre/news-items/asics-roadmap-for-digital-assets-law-reform-implementation)
  - [ASIC licensing deadline](https://www.asic.gov.au/about-asic/news-centre/news-items/final-call-for-firms-to-act-before-asic-s-digital-asset-licensing-deadline)
- **Vietnam:**
  - [VN ecosystem](https://e.vnexpress.net/news/tech/vietnam-innovation/vietnam-debuts-in-global-top-50-startup-ecosystems-5076481.html)
  - [VN crypto pilot](https://cryptorank.io/news/feed/b7225-nine-months-seven-applicants-zero-licences-vietnams-crypto-waiting-game)
  - [VN PDPL](https://www.dfdl.com/insights/legal-and-tax-updates/vietnam-personal-data-protection-2026-what-foreign-organizations-need-to-know/)
  - [payOS](https://payos.vn/)
  - [VNPay fees](https://vnpayment.vnpay.vn/phi.htm)
