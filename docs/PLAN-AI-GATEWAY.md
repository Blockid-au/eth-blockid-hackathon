# Plan — resilient, quota-aware AI gateway + fixes to the HR limitations (27 Sep 2026)

Goal: keep serving many users without hangs or "quota exhausted" failures, using the strongest reliable model for each
task at the lowest cost, switching BEFORE a limit is hit.

## 1. Gateway (agents/src/blockid_agents/llm.py + tools/search.py)
- **Per-call deadlines**: connect 10 s, first-token/response deadline per provider (Claude bridge 120 s, SambaNova
  60 s, DeepInfra 90 s); a hung call is cancelled and the chain moves on (fixes "10 min on one step").
- **Hedged requests** for interactive jobs (HR, valuation research): if the primary has not answered after its p90
  latency, start the next healthy model in parallel and take the first valid JSON; cancel the loser.
- **Circuit breaker per model**: error-rate / consecutive-failure window → open (skip) for 2–10 min with half-open
  probe; replaces the fixed 10-min park.
- **Quota-aware routing**: usage ledger per provider/model (requests per minute/day, tokens, spend) in Postgres
  (`studio.ai_usage`, shared by API + worker); known limits from config (SambaNova 60 rpm / 12k rpd per model, Claude
  bridge `BRIDGE_COMPLETE_MAX_PER_DAY`=300, Brave monthly quota, DeepInfra daily A$ budget) plus live
  `x-ratelimit-remaining/reset` headers when a provider sends them. At **≥ 80 %** of any window the model is demoted
  (used only as fallback); at **≥ 95 %** it is skipped until the window resets. Token-bucket pacing per model so
  bursts from many users are spread instead of tripping 429s.
- **Task profiles** (routing by task, not one global chain): `extract_json` (fact extraction, competitor lists),
  `reason_score` (SVI/HR scoring, fit), `long_context` (> 30k tokens → skip 32k models), `search`. Each profile has
  its own ordered candidate list; order = quality × reliability ÷ cost, recomputed hourly from the ledger
  (success rate, p50/p90 latency, schema-valid rate) with the benchmark scores as prior.
- **Context-length pre-check** (skip models whose window is too small) and schema-repair retry once on the same
  model before falling back.
- **Result cache** for identical (profile, prompt hash) → 24 h, and the existing 72 h search cache.
- **Concurrency limits** per provider (e.g. Claude bridge 2, SambaNova 6 per model, DeepInfra 8) with a fair queue
  per user so one heavy user cannot starve others.
- **Model catalogue check + benchmark**: verify available models via each provider's /models; small golden set for
  each profile (valuation extraction/scoring from stored evidence, HR fact extraction/fit) → quality, latency, cost;
  write `docs/LLM-ROUTING.md` table and defaults from it.

## 2. HR limitations
- User-facing errors are short codes + plain sentences; internal detail only for admins/audit.
- Suggestions: if the heuristic finds nobody, one cheap `extract_json` call over the stored team/about text (budgeted).
- ETA: percentile model with sensible defaults per step and per number of people; shows a range.
- Stalled detection: per-call deadlines make it ≤ 2–3 min instead of 10.

## 3. Admin "AI health" screen
`/admin/ai`: per provider/model status (healthy / demoted / skipped / open circuit), usage % of each window, error
rate, p50/p90 latency, spend today, next reset, recent fallbacks; manual pause/resume per model.

## 4. Further proposals (next)
Email when a long report is ready (needs SMTP for info@blockid.au); tracing (OpenTelemetry + self-hosted Langfuse);
golden-set evals in CI for valuation and HR; Safe 2-of-3 for issuer admin roles; per-user daily AI budget visible in
the UI; background job durability (Postgres-backed queue with leases).
