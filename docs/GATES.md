# Stage gates — scores and decisions

Stages and criteria: `PLAN-BUSINESS.md` §2, `PLAN-GTM.md` §6–7. Each gate gets one entry: date, scores, evidence
links, decision, who signed off. Numbers come from `/admin/analytics` and Admin → Revenue, **real users only**
(sample listings, demo, internal and judge accounts excluded — `FACTS.md`).

| Gate | Moves | Status | Date |
|---|---|---|---|
| G0 | S0 Hackathon → S1 Foundation | **open** — waiting for EAG Global Buildathon results | — |
| G1 | S1 → S2 Paid pilot | not started | — |
| G2 | S2 → S3 Paid beta | not started | — |
| G3 | S3 → S4 Scale / white label | not started | — |

## G0 — Judging closed

Facts (Devfolio, read 28 Sep 2026): EAG Global Buildathon, online, 20 Jul – **01 Oct 2026 00:00 UTC**; prize pool
US$12,500; no results date published; Sydney in-person demo was 26 Sep 2026. Project slug
`blockid-startup-passport-5dc5`, tracks: AI x Ethereum, Real-World Ethereum Applications, HSK Chain, Sydney.

Checklist (all required before billing goes live; live date = G0 + 7 days):
- [ ] Results announced — placement / prize / feedback: _…_ (link: _…_)
- [ ] Result + feedback recorded in `FACTS.md` and the Devfolio entry frozen
- [ ] Judging caps restored from `/opt/blockid/app.env.bak-judging`; `agents-api` recreated; limits checked
- [ ] Judge accounts marked `judge` (free for 30 more days)
- [ ] Traffic baseline exported from `/admin/ops` (hackathon period)
- [ ] `BILLING_START_AT` chosen and announced on /pricing 14 days ahead (target 01 Nov 2026 if results by 25 Oct)

Decision: _…_ Signed off by: _…_
