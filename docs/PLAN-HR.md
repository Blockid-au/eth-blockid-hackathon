# Plan — Founding team review (hr.blockid.au) wired into the business valuation (27 Sep 2026)

Owner direction: the founding team is the **highest-weighted** part of a business evaluation. The founder lists the
people (name + basic info); a dedicated BlockID agent researches each person's public professional profile and writes a
full team report. The full report lives on **https://hr.blockid.au**; the valuation result on eth.blockid.au shows the
team score and links to it.

## 1. Scoring model
- SVI weights change: **founder_quality 0.30** (was 0.20), product 0.15, market 0.15 (was 0.20), revenue 0.15
  (was 0.20), growth 0.10, readiness 0.10, trust 0.05. When a team report is complete, its team score replaces the
  model-suggested founder score (basis `team_report`); the admin can still override at the valuation gate.
- Person score (0–100), sub-scores with weights: domain expertise & founder–market fit 25, execution track record
  (prior ventures, exits, scale managed) 25, leadership & role fit 15, functional depth (tech / commercial / finance)
  15, verifiability of claims 10, commitment (full-time, equity, tenure) 10.
- Team score = 60% role-weighted average of people (CEO/founder 1.5×, co-founders 1.2×, key execs 1.0×, advisors 0.4×)
  + 40% team-level: complementarity (tech / commercial / domain / finance coverage), key-role completeness, prior work
  together, advisors/board, key-person concentration. Verified red flags (only from cited public sources) lower it.
- Evidence rule: the LLM only *suggests* sub-scores with rationale and citations; code computes all scores. A sub-score
  with no cited or founder-provided evidence is capped at 50. Facts must be verbatim-quoted from a stored page that
  names the person (and the company or a provided URL) — otherwise shown as "unconfirmed".

## 2. People agent (BlockID "People Analyst")
- Inputs per person: full name, role, founder/employee/advisor, full-time?, start year, equity % (optional),
  LinkedIn URL and other public URLs (site bio, GitHub, Google Scholar, press), short bio typed by the founder.
- Research: provided URLs first (LinkedIn is usually not readable; the typed bio is used and labelled "self-reported"),
  then ≤ 3 searches per person, ≤ 12 per team (name + company, name + prior company/role, name + "founder"), SSRF-safe
  fetch, evidence stored with hash, same verbatim-quote checks as the valuation research.
- Privacy: requester must confirm the people agreed; public professional information only; never health, religion,
  politics, family, home address, phone or personal email; emails/phones redacted before any search; people can ask for
  removal (info@blockid.au → admin delete). Agents hold no keys and the report is advisory.

## 3. Product
- **eth.blockid.au**: `/start` gets an optional "Founding team" panel (add people); the valuation report shows a
  "Founding team" card (team score, people with roles and scores, top strengths/gaps) + "Open the full team report" →
  `https://hr.blockid.au/r/<id>`. Team report can also be added after the valuation (re-scores and re-blends).
- **hr.blockid.au** (same SPA build, host-based routes): landing ("Know the people behind the business"), `/new`
  (evaluate a team standalone or for a business), `/r/:id` full report (team summary + radar, complementarity map,
  each person: verified facts with sources, sub-scores, strengths, gaps, questions to ask; team risks; method), `/me`
  my reports. Visibility: requester, company admins, platform admins, the demo account for demo reports, and holders of
  a listed business (team summary); share link token optional.
- API: `POST /v1/hr/teams`, `PUT /v1/hr/teams/{id}/people`, `POST /v1/hr/teams/{id}/run`, `GET /v1/hr/teams/{id}`
  (report), `GET /v1/hr/teams?mine=1`, `DELETE /v1/hr/people/{pid}` (admin/requester), link `valuation_id`.
- Infra: nginx `hr.blockid.au` → same `web/dist` + `/api/` proxy; TLS via certbot once DNS resolves; CSP + SIWE domain +
  ALLOWED_ORIGINS include hr.blockid.au.

## 4. Delivery
Phase H1 backend + agent + scoring (agent A), H2 hr.blockid.au UI + eth integration (agent B), infra (lead). Each
phase: tests → deploy → commit/push.
