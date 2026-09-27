# Operating company — Auschain Pty Ltd (BlockID)

Canonical company facts for the website footer, legal pages, invoices, Stripe, contracts and investor material.
Status markers: **verified** = checked on a public register (date given); **owner** = stated by the owner, evidence
to attach; **TO ADD** = missing, needed before the gate named.

## 1. Legal entity (verified — ABN Lookup, record extracted 28 Sep 2026)

Source: https://abr.business.gov.au/ABN/View?id=79659615111

| Field | Value |
|---|---|
| Entity name | AUSCHAIN PTY LTD (style used on its website: AusChain Pty Ltd) |
| ABN | 79 659 615 111 — active from 06 Jul 2022 |
| ACN | 659 615 111 |
| Entity type | Australian Private Company |
| GST | Registered from 26 Mar 2025 |
| Main business location (ABR) | NSW 2010 |
| Registered business names | AUSCHAIN ADELAIDE (16 Oct 2024), AUSCHAIN PERTH (09 Sep 2024) |
| DGR | not entitled |
| ABR record last updated | 26 Mar 2025 |

## 2. Company profile (from https://australiablockchain.au, read 28 Sep 2026)

- Blockchain system development, integration and consulting; Web3 services for enterprises.
- Products listed there: Carbon Credit Exchange (CTE), **BlockID**, traceability platforms.
- Contact on the site: +61 481 993 178; address "1 Fauna Place, Kirrawee 2232 NSW, Australia".
- The site states "International Licenses from Vietnam Blockchain Corporation", 65+ clients (it names Microsoft,
  KPMG, Mobifone, LotteMart) and 45+ awards. **These are Auschain / group claims, not BlockID users.** Do not
  reuse them in BlockID material without written evidence and the client's permission (same rule as
  `FACTS.md` "sample listings, no real users yet").
- The site has its own Terms & Conditions and Privacy Policy. They cover australiablockchain.au only. BlockID
  needs its own terms and privacy policy, which must cover wallets, analytics, AI providers, CVs and investor data.

**To confirm:** the ABR location (NSW 2010) and the website address (Kirrawee 2232) differ. Before the legal pages
are written, confirm the **registered office** (from the ASIC extract) and the **principal place of business**.

## 3. Brand and intellectual property

| Item | Status | Notes |
|---|---|---|
| **BlockID trade mark, owned by Auschain Pty Ltd** | **owner** | TO ADD: TM number, classes, status, priority date (IP Australia Trade Mark Search). Check that the classes cover class 9 (software), 35 (business information / reports), 36 (share registry, valuation, financial information) and 42 (SaaS). If class 36 or 42 is missing, file a new application before launch. Consider a Madrid filing designating Vietnam before selling there. |
| ™ / ® use | rule | Use **®** only once the registration number is confirmed as *Registered*. Until then use "BlockID™" or "BlockID is a trade mark of Auschain Pty Ltd". |
| Business name "BLOCKID" | TO ADD before G1 | A trade mark is not a business name. Invoices, receipts and the site should present the seller as "Auschain Pty Ltd trading as BlockID". To do that, register BLOCKID as a business name on ASIC Business Names, linked to ABN 79 659 615 111. |
| Domains blockid.au, eth./hr./scan.blockid.au, startupvalueindex.com | TO ADD | Record the registrant. A .au name must be held by the Australian entity (Auschain). Record the renewal dates and who controls the DNS/Cloudflare account. |
| Code licence | decision | The hackathon repo `Blockid-au/eth-blockid-hackathon` is public under **MIT**, so anyone may reuse that code; the brand stays protected by the trade mark. Recommendation: freeze the hackathon repo at the judging commit and build commercial features (billing, analytics, tenants) in the private repo `Blockid-au/eth-blockid`. |
| IP with Vietnam Blockchain Corporation | TO ADD before G2 | Written agreement stating that Auschain owns BlockID IP (code, brand, data). Contractor / developer IP assignment. If the Vietnam team can access production data, the privacy policy must disclose offshore access (APP 8). |

## 4. Standard legal line (proposed; use after the TM number is confirmed)

Footer (EN):
> BlockID is a trade mark of Auschain Pty Ltd · ABN 79 659 615 111 · ACN 659 615 111 · © 2026 Auschain Pty Ltd.
> Testnet demo. Not an offer of securities or financial advice.

Footer (VI):
> BlockID là nhãn hiệu của Auschain Pty Ltd · ABN 79 659 615 111 · ACN 659 615 111 · © 2026 Auschain Pty Ltd.
> Bản demo trên testnet. Không phải chào bán chứng khoán hay tư vấn tài chính.

When S3 starts, drop the "Testnet demo" words only for modules that run on production. Keep "Not financial
advice" on every valuation report.

## 5. Billing identity (for Stripe and invoices, S2–S3)

- Seller: Auschain Pty Ltd (trading as BlockID once registered), ABN 79 659 615 111, GST-registered.
- Every paid invoice is a **tax invoice**. It shows "Tax invoice", the seller ABN, the date, the items, and the GST
  amount (10 %) or "Total price includes GST".
- Prices shown to consumers must be the total including GST (Australian Consumer Law). B2B / white-label prices
  may be shown ex GST, labelled "+ GST".
- Customers outside Australia (e.g. Vietnam) are generally GST-free as exported services. Confirm this with the
  accountant, then set it in Stripe Tax.
- Stripe account: business type company, legal name AUSCHAIN PTY LTD, ACN/ABN above, statement descriptor
  `BLOCKID.AU`, payouts to an AUD business bank account in the company name.
- BAS lodgement (quarterly or monthly) will include BlockID revenue. The ledger → Stripe → Xero reconciliation is
  in `PLAN-BUSINESS.md` §4.5.

## 6. Information still missing for the business plan (owner to provide)

| # | Item | Needed for | Gate |
|---|---|---|---|
| 1 | BlockID trade mark number, classes, status (certificate PDF) | footer ®, white-label contracts, investor deck | G1 |
| 2 | ASIC company extract: directors, secretary, registered office, shareholders | Stripe business verification, contracts, AFSL partner due diligence, investor deck | G1 |
| 3 | Register business name BLOCKID (or decide to trade only as Auschain Pty Ltd) | invoices, legal pages | G1 |
| 4 | Domain registrant and renewal dates; who holds the Cloudflare / DNS login | continuity, security | G1 |
| 5 | Business bank account (AUD) in the company name | Stripe payouts | G2 |
| 6 | Accountant / tax agent; BAS cycle; financial year (assume 1 Jul – 30 Jun) | GST on invoices, R&D claim | G2 |
| 7 | Lawyer engaged: BlockID Terms, Privacy Policy, HR consent, AFSL / CSF memo | legal pages, what may be charged | G1 (pages), G2 (memo) |
| 8 | Insurance: professional indemnity + cyber (+ public liability) | selling reports that others rely on; holding CV / PII data | G2 |
| 9 | Privacy officer name and complaint contact (e.g. privacy@blockid.au) | Privacy Policy (APP 1) | G1 |
| 10 | Agreement with Vietnam Blockchain Corporation (IP ownership, data access, services) | IP certainty for investors and white-label partners | G2 |
| 11 | Google Workspace / SMTP credentials for info@blockid.au | alerts, receipts, welcome and report emails | G1 |
| 12 | Warm leads among Auschain's existing clients who might pilot BlockID (named contact, consent to approach) | S2 pilot pipeline | G1 → S2 |
| 13 | **R&D Tax Incentive**: register the BlockID R&D activities (AI valuation, provenance, tokenised registry) with AusIndustry. For FY2025-26 (ended 30 Jun 2026) the deadline is 30 Apr 2027. Companies under A$20M turnover get a refundable offset. Keep timesheets and git history as evidence. | cash runway | before 30 Apr 2027 |
| 14 | Export grants (EMDG) if Vietnam sales start; accountant to check eligibility | VN go-to-market | S4 |
| 15 | Budget and runway: the monthly spend Auschain can commit to BlockID, and the founder time available | revenue ramp and hiring in `PLAN-BUSINESS.md` §5 | G1 |

When an item is done, update this table with the date and the evidence location, and mirror key values in
`FACTS.md`.
