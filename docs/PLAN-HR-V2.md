# Plan — BlockID HR v2: talent-grade design, live progress, tight link with eth.blockid.au (27 Sep 2026)

Owner feedback on v1: tabs must be bold and pinned so people know where to click; entering a person must be easier;
a "pro" look in a talent-and-innovation palette (keep the BlockID logo); the run must show what it is doing and fill
in results as they arrive instead of hanging; CTAs to eth.blockid.au (value the business, list shares); hr must give
founder and team-member assessments to the business being valued on eth.

## 1. Live progress contract (backend → UI)
`GET /v1/hr/teams/{id}` and `/v1/hr/people-reports/{id}` add:
```
progress: {
  phase: "queued|reading|searching|extracting|scoring|done|failed|stalled",
  pct: 0..100,                      // monotonic
  eta_s: int|null,                  // from step timings of recent runs
  started_at, updated_at,           // updated_at = heartbeat (≤ 10 s while running)
  current: {person: str|null, step: str, detail: str},   // e.g. "Search 2 of 3 · 'Do Van Long Vietnam Blockchain'"
  feed: [{at, level: "info|found|warn", msg, person?, source?}],  // newest last, ≤ 60 items, plain words
  counters: {pages_read, searches, facts_verified, facts_unconfirmed, people_done, people_total},
  partial: {people: [{id, name, status: "waiting|working|done|failed", facts: [...verified so far], score?, fit?}]}
}
```
- Every step writes a feed line with what it is doing and what it found ("Read blockid.au — 2 facts", "Search 1/3 — 5
  results", "Claude is reading 6 pages about Do Van Long", "Scored: Partial fit 62").
- Partial results are saved as each person finishes (their facts and score are visible before the team is done).
- Stalled: no heartbeat for 90 s → phase "stalled" in the API view; the worker's watchdog re-queues once, then fails
  with a clear reason. Model fallbacks are logged in the feed ("Claude busy → using DeepSeek").

## 2. hr.blockid.au UX
- Palette "talent & innovation": deep indigo ink + violet primary + teal for verified/positive + amber for
  unconfirmed; BlockID logo unchanged; tokens scoped to the hr app (eth keeps its green).
- Report tabs: bold, high-contrast segmented bar, **sticky** under the nav (desktop + mobile), active tab filled,
  counts as badges, keyboard arrows; left profile card sticky on desktop.
- Person form: 3-step wizard (Who → Compare with → Consent & start) with a live preview card; paste a LinkedIn/URL or CV
  text → name/headline suggested; business picker with search over BlockID businesses and your valuations; role
  target with requirement suggestions; inline validation; draft kept in the browser.
- Live run screen: progress ring with %, ETA, current action line, step timeline, live feed, and person cards that
  fill in as facts/scores arrive; "you can leave this page — the report keeps running" + link in My reports.
- CTAs to eth.blockid.au on landing, report and team pages: "Value this business", "List shares on blockchain",
  "Open the business valuation".

## 3. eth.blockid.au ↔ hr
- Valuation report: Founding team card shows live status (queued / running with % / done) and each founder's fit to
  THIS business; "Assess the founders" opens hr with the business pre-selected and people suggested from the
  business website (site intake already reads team pages).
- Company workspace overview: "Team" tile with team score and link to hr.
- hr reports for a business: "Open the business valuation" and "List shares" CTAs.

## 4. Delivery (parallel)
A backend progress + suggestions (agents/people.py, studio/hr.py, hr_store.py, worker); B hr UI (pages/hr/*, hr css,
dict.hr.ts); C eth integration (TeamCard, Valuation report card, NewWizard team panel, Company overview tile). Tests →
deploy → commit/push.
