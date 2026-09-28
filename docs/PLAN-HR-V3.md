# Plan — BlockID HR v3: CV ↔ source cross-check and fit to the business / JD / current role (28 Sep 2026)

Owner direction: (1) every CV that is uploaded must be **checked against the public sources the People Analyst
finds**, so a reader knows how far the CV can be trusted; (2) the report must say clearly **whether this CV fits** the
business under review, the job described in a JD, or the role the person holds now (e.g. listed as CTO).

## 0. Where v2 stands (what we build on)
- `agents/cv_review.py` reads the CV (stats → timeline → insights) next to the web research. Claim check today
  (`CVReview.finish`): a CV claim is "confirmed" when **any** verified fact names its organisation. Title, dates,
  degree and numbers are not compared, "contradicted" does not exist, and the searches ignore the CV. They start
  before the CV is structured and use only name + company / headline / role (`people.person_queries`).
- `agents/people.py` already computes a fit score when a target exists (business, or role with
  title / description / requirements). The requirement matrix is matched / partial / missing, but a CV-only match
  counts almost like a verified one (`self_reported=true`). Team mode always uses the business as the target. The
  person's **own stated role** (CTO, CFO…) is never checked as a fit lens.
- The JD form (`HrNewPerson.tsx`) turns text into requirements with a client-side keyword helper (`suggestRequirements`).
  It does not read years, seniority or knockout criteria.
- The free lookups already exist in `tools/lookups.py` (Wayback CDX, ABN Lookup when a GUID is set). HR does not use
  them yet.

## 1. CV claim ledger (cross-check)
### 1.1 Claims, built in code from the CV review
From `timeline.roles`, `timeline.education`, `certifications`, `insights.achievements` and `insights.claims` we
build a normalised list (ids `c1…`, at most 20). Each item has kind (role / education / certification / venture /
achievement / award / publication), org, title / degree, start, end, metric, `cv_quote` (an exact excerpt, which
code checks against the CV) and an importance weight: current role 3, roles in the last 5 years and roles relevant
to the target 2, highest degree 2, the rest 1.

### 1.2 Claim-led research (sequence change)
- The CV **structure** call moves in front of the searches. It runs while the provided URLs are fetched (≈ 20–60 s),
  so the searches can use the claims. If it has not finished by the time the provided URLs are done, the generic
  queries run first and the claim queries follow.
- Per person: 2 generic queries + up to `HR_CLAIM_SEARCHES_PER_PERSON` (default 3) claim queries, e.g.
  `"<name>" "<org>" <title>` or `"<name>" "<university>"`. Top claims by importance go first. Team cap rises from 12
  to `HR_SEARCHES_PER_TEAM` = 20 (owner decision D1).
- Free structured sources, cached for 7 days, fail soft, 6 s timeout, same pattern as `tools/lookups.py`:
  | Source | Checks | Notes |
  |---|---|---|
  | Wayback CDX + archived team / about page of the claimed org | person listed at org **at a date** → role dates | reuse `lookups.wayback_*` |
  | GitHub REST (public profile, repos, orgs) | tech claims, account age, org membership | only for a GitHub URL the person gave |
  | OpenAlex / ORCID public APIs | publications, affiliations with years | name + affiliation must match |
  | ABN Lookup (GUID) / company site | venture exists, registration date vs "founded X in 2019" | AU only; OpenCorporates later (key) |
  | Credential verify URLs (Credly, Coursera, Microsoft Learn, university verify pages) | certification | only when the CV / person gives the URL |
  LinkedIn stays unreadable. A LinkedIn-only claim is "unverifiable", not "not found".

### 1.3 Matching: the model suggests, code decides
- The existing person call (no extra model call) gains `claim_checks: [{claim_id, fact_ids, conflict:
  {source_url, quote, field, source_value}|null, note}]`.
- Code checks each claim along separate dimensions. Only verified facts count, plus a conflict quote that code finds
  on a stored page naming the person:
  - **identity**: the page names the person AND at least one anchor (a CV org, the city, the headline). A page that
    names the person but only other orgs in a clash is dropped as a **possible namesake** and noted.
  - **org** (`names_org`), **title** (token match + synonym map: CTO = Chief Technology Officer, Head of Eng ≈
    VP Engineering…), **dates** (a year in the quote within ±1 year of the CV span), **degree / field**, **metric**
    (the same number ±10 % in the quote).
- Status per claim:
  `verified` (identity + org + title/degree on a tier-1/2 source, or on 2 independent tier-3 sources) ·
  `partly_verified` (org confirmed, title or dates not; or snippet only) · `not_found` · `unverifiable` (the source
  type is not public, e.g. private employer, LinkedIn only) · `contradicted` (an independent source that names the
  person gives a different org / title / period, and code finds the conflict quote on the page).
- Source tiers, set by code from the host and the evidence kind: T1 issuer / registry / the org's own domain /
  university; T2 established press, conference, GitHub API, OpenAlex / ORCID; T3 other pages; T4 search snippet.
- Wording rule: **"not found" is never "false"**. `contradicted` is labelled "needs human review". It never becomes
  a red flag on its own. The requester sees both sides with quotes.

### 1.4 CV Trust Index (code)
`trust = Σ(importance × w_status) / Σ(importance × 1)` with w: verified 1.0, partly 0.6, unverifiable 0.35,
not_found 0.2, contradicted 0. The band is shown with coverage:
**High** ≥ 70 and no contradicted key claim · **Medium** 45–69 · **Low / needs review** < 45 or any contradicted
claim of importance ≥ 2. Internal consistency from the timeline (dates that do not add up, >3-month overlaps with
month-precise dates) shows next to it as its own "consistency" line. Career breaks are **never** scored.
- The `verifiability` sub-score (weight 10) is computed from the Trust Index in code. It is no longer
  model-suggested.

## 2. Fit: business, JD, current role
### 2.1 Three lenses (one report can hold several)
| Lens | When | Requirements come from |
|---|---|---|
| **Business** | team mode; person → BlockID business | sector / stage / product (as today) + **what the business needs now**: team gaps from the team report (missing function, key-person concentration) and the valuation's weak pillars |
| **JD** | person → role | JD parser (2.2), edited by the requester |
| **Current role** | always when the person has a stated role (e.g. CTO of the business) | role template library (2.3) scaled by the business stage |

### 2.2 JD parser (server)
`POST /v1/hr/jd/parse {text}` makes one cached model call. It returns title, seniority, min_years, domain,
must-haves, nice-to-haves, knockouts (licence, degree, clearance), skills, and **flagged wording**: requirements that
touch a protected attribute (age / "young", gender, nationality, family status) get a warning under AU law (Age /
Sex Discrimination Acts, Fair Work Act s351) and are left out of scoring. The requester edits the result in the
existing must / nice chips. The keyword helper stays as the offline fallback.

### 2.3 Role templates (data file, no model)
`agents/data/role_templates.json` covers CEO, CTO, CFO, COO, CMO / growth, CPO / head of product, engineering lead,
senior engineer, sales lead, advisor / board. Each has 5–8 competencies per stage band (pre-seed/seed, A/B, growth),
e.g. a seed-stage CTO needs "hands-on build of the core product" and a Series B CTO needs "scaled an engineering org
10+". The current-role lens asks: does the career show this **function**, this **level** and this **scope**? Is the
stated role consistent with the CV headline and with public sources?

### 2.4 Scoring changes (code)
- Each requirement row carries `status` (matched / partial / missing) and an **evidence level**: `verified` (fact ids)
  · `cv_only` (claim id, with the cv_quote checked by code) · `contradicted` · `none`.
- **Two fit numbers**: *Claimed fit* (CV taken at face value) and *Verified fit* (cv_only counts 0.5,
  contradicted 0). The gap between them is shown ("12 points of this fit rest on unverified CV claims").
- **Relevant experience**: the model tags each CV role's relevance to the lens (high / medium / low + reason). Code
  sums the months of high + ½·medium roles, weights the last 5 years ×1.0 and older ×0.6, and compares the result
  with the JD's min_years.
- **Knockouts**: a missing must-have or knockout caps the fit at 60 ("fit with conditions"). A contradicted
  must-have caps it at 40.
- Contribution to the team score uses **Verified fit** (was: fit). The person's contribution = 0.5 × quality +
  0.5 × verified fit.
- **Verdict** per lens: Strong fit (≥ 75) · Fit with conditions (55–74 or a knockout) · Weak fit (35–54) · Not
  suitable (< 35). It pairs with Trust in a 2×2: *Proceed* (fit high, trust high) · *Verify first* (fit high, trust
  low) · *Consider another role* (fit low, trust high) · *Stop* (both low).
- **Alternative role hint**: when the JD / current-role fit is weak but another template or a team gap scores ≥ 70,
  suggest it ("stronger as Head of Partnerships than as CTO").
- Interview questions are aimed first at **unverified or contradicted must-haves**.

## 3. UI (hr.blockid.au, EN default + VI)
- **Overview → Decision card** at the top: fit verdict per lens, Trust band + coverage, the 2×2 position, 3 reasons,
  and "3 things to verify before deciding".
- New tab **Verification** (VI: *Đối chiếu*). It replaces the claims block of the CV analysis tab and has a claim
  ledger table: *CV says* | *Public source says* (quote) | chips Identity · Org · Title · Dates · Metric | status |
  source tier + link + SHA-256. Filters: all / contradicted / not found / unverifiable. There is also a career
  timeline with verified spans in teal, unverified in amber and conflicts in red, plus a possible-namesake note.
- Tab **Requirements → Fit** (VI: *Mức phù hợp*). It has a lens switcher (Business · JD · Current role), the verdict,
  Claimed vs Verified bars, a relevant-years gauge vs min years, knockouts, the requirement matrix with an evidence
  level icon, and the alternative role hint.
- Live screen: new steps "Structuring the CV", "Searching the CV's claims (3/5)" and "Checking claims: 4 verified,
  1 conflict".
- Team report: the people table gets Trust and Current-role fit columns. A heat map shows requirements (team
  needs) × people.
- eth.blockid.au Founding team card: each founder shows Trust band + current-role fit.
- Visibility: conflict quotes and the claim ledger are visible to the requester, company admins and platform admins.
  Share links and holder views show bands only (owner decision D2).

## 4. Privacy, fairness, compliance
- Same privacy filters as v2 (public professional information only, sensitive categories dropped, contact details
  redacted). No age inference from graduation years. Gaps and part-time periods are shown as neutral questions and
  never scored.
- The report stays advisory with a human in the loop, and "not found ≠ false" is stated on the tab. The subject can
  ask for correction or removal (info@blockid.au). A "notify the person" text is offered after the run (Privacy Act
  APP 5 collection notice).
- If the product is sold into the EU later, recruitment AI is high-risk under the EU AI Act (Annex III). The audit log
  of every claim decision (inputs, source hash, rule applied) is kept now so that is ready.

## 5. Data / API changes
- `cv_review.py`: `claims_from_review()`, a new live part `ledger` (`Tracker.cv(pid, "ledger", …)`) and
  `trust_index()`. `finish()` is replaced by the ledger.
- `people.py`: `claim_queries()`, `source_tier()`, `match_claim()` (dimensions), `PersonAnalysis.claim_checks` +
  `role_relevance`, `fit_score()` with evidence levels / two numbers / knockouts / relevant years, and
  `current_role_fit()` from templates. Report `VERSION = "hr-2"`; the UI keeps reading hr-1 reports.
- `studio/hr.py`: `RoleTarget` + `jd_text`, `min_years`, `seniority`, `knockouts`; `POST /v1/hr/jd/parse`
  (rate-limited like `suggest-people`); the report adds `cv_review.ledger`, `trust`, and `fits: {business?, jd?,
  current_role?}` (`fit` stays as the main lens for older clients).
- Config: `HR_CLAIM_SEARCHES_PER_PERSON=3` and `HR_SEARCHES_PER_TEAM` hard cap 20. `HR_LOOKUPS=wayback,github,openalex`.
- Cost per person: +3 searches, +0 model calls (folded into the person call), JD parse +1 cached call per JD.
  Expected run time +20–40 s. Billing (one people report = one credit) is unchanged.

## 6. Quality gate
- Golden set `agents/tests/fixtures/hr_v3/`: 12 fictional personas with fixture pages. They are honest, inflated
  title, shifted dates, fabricated degree, same-name namesake, LinkedIn-only, and strong / weak JD fit. Offline tests
  run with the fakes.
- Targets: `verified` precision ≥ 0.95; **zero** false `contradicted`; namesake pages never used; fit verdict agrees
  with the hand labels on ≥ 10/12.
- Existing suites (`test_cv_review`, `test_people`, `test_hr_api`, `test_hr_progress`) stay green. The width audit
  `scripts/screenshots/audit-hr.mjs` covers the new tabs.

## 7. Delivery
| Phase | Scope | Est. |
|---|---|---|
| V3.1 | Claim ledger backend: claims, claim-led search, lookups, dimensions, tiers, trust index, tests | 1.5 d |
| V3.2 | Fit lenses: JD parser, role templates, two fit numbers, relevant years, knockouts, verdict, alt role | 1.5 d |
| V3.3 | UI: Decision card, Verification tab, Fit tab, live steps, team columns, eth card, dict EN/VI | 2 d |
| V3.4 | Golden set, audit, deploy (agents-worker + agents-api from a clean worktree; web via build-web) | 1 d |
| Later | Candidate proof / response link, OpenCorporates (key), VN business registry, reference checks with consent | — |

## 8. Owner decisions
- **D1** Raise the team search cap 12 → 20 (≈ +30 s and more search cost per team). *Recommended: yes.*
- **D2** Can share-link / holder viewers see conflict details, or bands only? *Recommended: bands only.*
- **D3** Team contribution uses Verified fit instead of fit. *Recommended: yes.* This lowers scores for CV-only teams.
- **D4** Build the candidate "respond / upload proof" link in v3 or later? *Recommended: later (V3.5).*

**Owner answer (28 Sep 2026): D1–D4 accepted as recommended.**

## 9. Data contract (report `version: "hr-2"`; the UI keeps reading hr-1)
```
card.cv_review.ledger = {                          # only when the person has a CV (>= 200 chars)
  claims: [{id: "c1", kind: "role|education|certification|venture|achievement|award|publication",
            text, org, title, start, end, metric, cv_quote, importance: 1|2|3,
            status: "verified|partly_verified|not_found|unverifiable|contradicted",
            dims: {identity, org, title, dates, metric, degree: true|false|null},   # null = not applicable
            fact_ids: [str], best_tier: 1|2|3|4|null, sources: [{url, tier}],
            conflict: {url, quote, field, source_value, tier} | null,              # stripped for share / holder views
            note: str}],
  counts: {verified, partly_verified, not_found, unverifiable, contradicted},
  namesakes: [{url, reason}],                                                   # stripped for share / holder views
  lookups: [{kind: "wayback|github|openalex", query, url, found: bool, detail}]
}
card.trust = {score: 0..100 | null (null for share / holder views), band: "high|medium|low",
              coverage_pct, contradicted_key: int, consistency: {overlaps, date_issues}} | null
card.fits = {business?: Fit, jd?: Fit, current_role?: Fit};  card.fit = fits.jd || fits.business (primary lens)
Fit (v1 fields kept) + {lens: "business|jd|current_role", title: str,
  score (= verified fit), claimed_score, verified_score, verdict: "strong|conditional|weak|not_suitable",
  requirements[]: {..., evidence: "verified|cv_only|contradicted|none", claim_ids: [str]},
  knockouts: [str], cap: number | null,
  relevant: {years, min_years | null, roles: [{org, title, relevance: "high|medium|low", reason, months}]} | null,
  template: {key, label, stage_band} | null,               # current_role lens
  alt_role: {role, score, reason} | null}
card.decision = {quadrant: "proceed|verify_first|other_role|stop", fit_lens, fit_score, trust_band,
                 reasons: [str] (<= 3), verify: [str] (<= 3)}
live: partial.people[].cv.ledger (same shape as ledger, arrives after scoring) ; progress feed lines
summary.people[] += {trust_band, role_fit, role_fit_verdict}
POST /v1/hr/jd/parse {text} -> {title, seniority, min_years, domain, must: [str], nice: [str], knockouts: [str],
                                skills: [str], flagged: [{text, reason}]}
RoleTarget += {min_years?: int, seniority?: str, knockouts?: [str]};  target view += {flagged: [{text, reason}]}
```
