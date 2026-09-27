# LLM routing for the valuation agents

The cloud tier (site intake, competitors, funding claims, market analysis, SVI scoring, narrative) runs on a
fallback chain ordered by marginal cost: free SambaNova models, then Claude Sonnet on the signed-in subscription
(host bridge, no tools), then cheap paid DeepInfra models. The `local` tier (PII) never leaves the gateway.

```
LLM_PROVIDER_ORDER=sambanova,claude_bridge,deepinfra
SAMBANOVA_MODELS=gpt-oss-120b,DeepSeek-V3.1,DeepSeek-V3.2,Meta-Llama-3.3-70B-Instruct,gemma-4-31B-it  # free
DEEPINFRA_MODELS=deepseek-ai/DeepSeek-V4-Flash,openai/gpt-oss-120b                                    # paid
```

Each SambaNova model has its own quota (this key: 60 req/min, 12k req/day per model) and a 429/402 parks only
that model for 10 minutes, so five models multiply the free capacity. DeepSeek-V3.2 has a 32k context, so on a
long market-analysis prompt it fails fast and the chain moves on.

`claude-bridge` = `POST /complete` on `deploy/search-bridge/claude_search_bridge.py` (Sonnet, `--tools ""`,
caller's JSON schema, own lock and daily cap `BRIDGE_COMPLETE_MAX_PER_DAY`=300). Any failure parks it for 10 min.

Web search: Brave first, then the same bridge's `POST /search` (Claude Haiku + WebSearch only). SambaNova has no
web-search tool, so it is not a search provider; it does all the LLM work around search (competitor lists and
relevance, funding claims, cited market analysis).

Search budget (valuation v3): ≤ 8 searches per valuation (`SEARCH_MAX_QUERIES`, hard cap 8), ≤ 3 fetched pages
each (`SEARCH_FETCH_PER_QUERY`, cap 3), planned by purpose in priority order; conditional queries run only when they
can change the value. Every attempt is logged in `searches` (kind, purpose, query, provider, results) and the audit
log; repeated queries hit the 72 h cache and pages already stored for the valuation are reused.

| # | Step | Purpose | Query |
|---|---|---|---|
| 1 | competitors | find competitors | `<company> competitors alternatives <country>` |
| 2 | market | market size / growth | `<sector> market size growth <country> <year>` (Brave freshness: past year) |
| 3 | market | company revenue / ARR | `<company> revenue ARR funding valuation <year>` (2 extra results kept as snippets) |
| 4 | market | own valuation / round / share sale | `<company> valuation funding round post-money valued at` |
| 5 | market | market cap — only if a listing (`<Company> (ASX: ART)`) is detected by code in stored pages | `<company> <EXCH>:<TICKER> market cap` |
| 6 | market | comparable / sector multiples — only if the company has revenue | `<sector> companies EV/revenue multiple <year>` |
| 7 | market | named competitors' valuation + revenue — only with revenue and named competitors | `<comp1> <comp2> <comp3> valuation revenue` |

After the market analysis the research agent makes `CompanyFinancials` (revenue / ARR, verified quote) — re-run once
if searches 4–5 stored new pages and no revenue was found yet — and one `ValuationEvidence` call
(`agents/market_evidence.py`): the company's own anchors (priced round, secondary sale, investor mark, reported
valuation, market cap) with the date as written, comparable companies' multiples (or valuation + revenue), sector
multiples, and the listing. Code keeps a claim only if its quote is verbatim on the cited stored page (or its search
snippet) and states the number; anchors also need valuation words, a page that names the company, a currency in the
dated FX table and a date that appears on that page (a market-cap page without a date is dated by its fetch).

Valuation v3 (`tools/triangulate.py`; the LLM never produces a number):
1. **market anchor** — the newest verified anchor (anchors within 3 months of it: median). Weight = kind
   (market cap 3.0 when ≤ 3 months old, priced round 1.0, secondary 0.9, investor mark 0.8, reported 0.7) × recency
   (≤ 12 months 1.0, ≤ 24 0.8, ≤ 36 0.45, ≤ 60 0.3, older 0.15, no date 0.35).
2. **revenue × multiple** — revenue (self-reported > website > cited, ≤ 3 years old) × median of verified
   comparable companies > verified sector multiples > the market analysis' multiple > default table (2/3.5/6×,
   SaaS/fintech 3/6/10×). Listed-company multiples on an unlisted company: −25% private-company discount. Weight
   0.6 × source (≥3 comps 1.0, 1–2 comps 0.8, sector 0.7, market analysis 0.5, default 0.25) × revenue source.
3. **stage benchmark** × SVI factor — weight 1 alone, 0.1 with another method, 0 when > 5× away from them.

Blend = weighted mean; range = weighted mean of the method ranges, at least ±10% / ±20% / ±35% for
high / medium / low confidence. Confidence: high = verified anchor ≤ 24 months carrying ≥ 50% and methods within 2×
(or a current market cap); medium = any anchor or a cited multiple; low otherwise — each with reasons. The result
is `svi.triangulation` (methods, weights, inputs, sources); `valuation_low/mid/high_aud` = the blend, the SVI index
and grade stay as the quality indicator. `/verify` rebuilds the blend from the stored inputs (formula `v3`); older
reports still verify with `v2` / `v1`. Backtest: [valuation-reference.md](valuation-reference.md).

## Benchmark (2026-09-26)

Task: the real `QualitativeScores` call from `agents/valuation.py` on three stored valuations (SafetyCulture,
Airwallex, BlockID), each run twice. Reference: Claude Sonnet via the CLI. MAE = mean absolute difference from
Sonnet over the 5 dimension scores (0–100). Unknown URL = cited source not present in the input.

| Model | Valid | Latency | Cost / call | MAE vs Sonnet | Run-to-run drift | Unknown URLs |
|---|---|---|---|---|---|---|
| **SambaNova gpt-oss-120b** | 6/6 | 5.4 s | free | 9.3 | 3.3 | 0/60 |
| SambaNova DeepSeek-V3.1 | 6/6 | 5.7 s | free | 11.9 | 4.0 | 0/43 |
| SambaNova Llama-3.3-70B | 6/6 | 2.9 s | free | 14.2 | 4.0 | 0/31 |
| SambaNova gemma-4-31B-it | 6/6 | 8.2 s | free | 14.4 | 2.3 | 0/24 |
| SambaNova DeepSeek-V3.2 (32k ctx) | 6/6 | 8.9 s | free | 12.7 | 5.3 | 0/54 |
| SambaNova MiniMax-M2.7 (excluded) | 6/6 | 17.4 s | free | 10.3 | 11.7 | 5/51 |
| **DeepInfra DeepSeek-V4-Flash** | 6/6 | 14.9 s | $0.00043 | 9.1 | 7.0 | 0/62 |
| DeepInfra gpt-oss-120b | 6/6 | 13.2 s | $0.00022 | 9.4 | 5.7 | 5/56 |
| DeepInfra Qwen3-235B-2507 (old default) | 3/3 | 37.8 s | $0.00051 | 17.2 | – | – |
| Claude Sonnet (CLI, subscription) | 3/3 | 29.1 s | $0.045 notional | 0 (ref) | – | – |
| Claude Haiku (CLI) | 1/3 | 32.3 s | – | 10.2 | – | – |

Notes
- gemma-4-31B-it inflates product/market scores (85–90 where Sonnet gives 55–68), so it is last among free models.
- MiniMax-M2.7 is excluded: unstable run to run and cites URLs that are not in the input.
- SambaNova MiniMax-M3 returned 402 (no balance / "high demand"): not usable on the free tier.
- Claude Haiku fails `--json-schema` structured output on 2 of 3 cases; Sonnet is reliable but ~6× slower.
- Brave: this key's monthly quota is 0, so search currently runs on the Claude bridge.

## End-to-end checks

With the final chain (8 backends): https://www.rokt.com/ valued in 90 s, all 7 LLM calls (incl. FundingClaims)
answered by `sambanova:gpt-oss-120b`; the worker → bridge `/complete` path was verified separately from inside the
worker container.

Earlier (3-model chain):

Valuation of https://www.cultureamp.com/ after the change: all 6 steps done in 107 s; every LLM call
(StartupProfile, CompetitorList, MarketAnalysis, QualitativeScores, Narrative) answered by
`sambanova:gpt-oss-120b` with no fallback, so the LLM cost was US$0.

## People Analyst (founding-team / person review, 27 Sep 2026)

The People Analyst (`agents/people.py`) has its **own** chain; the valuation chain above is unchanged. It is a
per-agent override in `llm.py` (`AGENT_CHAINS` → `build_agent_llms` → `Deps.agent_llm`), reusing `cloud_chain`,
`FallbackLLM` and each provider's parking / cooldown logic.

```
HR_LLM_PROVIDER_ORDER=claude_bridge,sambanova,deepinfra        # default
HR_SAMBANOVA_MODELS=DeepSeek-V3.1,DeepSeek-V3.2                 # free
HR_DEEPINFRA_MODELS=deepseek-ai/DeepSeek-V4-Flash,Qwen/Qwen3-235B-A22B-Instruct-2507   # paid, cheap
HR_SEARCH_PROVIDERS=claude,brave                                # default
HR_TIER=cloud  HR_SEARCHES_PER_PERSON=3 (cap 3)  HR_SEARCHES_PER_TEAM=12 (cap 12)  HR_RUNS_PER_DAY=5  HR_MAX_ACTIVE=5
```

- **Why Claude first**: the hard part is person disambiguation (namesakes) and verbatim quoting; Claude Sonnet via the
  host bridge (`POST /complete`, no tools, our JSON schema) is the most reliable at both. The Claude CLI is added only
  if `HR_LLM_PROVIDER_ORDER` lists `claude` (no automatic CLI insertion for this agent).
- **Fallbacks**: SambaNova DeepSeek-V3.1 / V3.2 (free, per-model quota parking), then DeepInfra DeepSeek-V4-Flash
  (closest to Sonnet in the SVI benchmark above, no invented URLs) and Qwen3-235B-A22B-Instruct-2507 (reliable JSON,
  slower). Both DeepInfra ids and both SambaNova ids were confirmed in each provider's `/models` listing with the
  worker's keys on 2026-09-27 (other candidates seen there: `moonshotai/Kimi-K2.6`, `zai-org/GLM-4.7`,
  `deepseek-ai/DeepSeek-V4-Pro`; not benchmarked for this task yet). With `LLM_BACKEND=gateway` the agent uses the
  gateway like every other agent.
- **Budget**: 1 extraction call per person + 1 team call per report (a 5-person team = 6 calls) — the bridge's daily
  cap `BRIDGE_COMPLETE_MAX_PER_DAY=300` is shared with the valuations; when it is reached the bridge parks and the
  chain falls through to SambaNova.
- **Search**: Claude web search first (better at finding the right person; Brave's monthly quota is currently 0),
  then Brave; same 72 h cache and audit log (`search_served` / `search_unavailable`). Every attempt is in the report's
  `searches` (person, query, provider, results).
- **Logging**: the model that answered each person's extraction and the team call is stored in the report
  (`method.models`, `people[].model`) and in the audit log (`person_analysed`, `team_analysed`, `llm_call`).
- **Privacy**: names (and the typed bio / CV) of people whose consent the requester confirmed are sent to these cloud
  providers and the search providers. Emails and phone numbers are redacted before anything is stored, prompted or
  searched; sensitive categories are filtered from the output by code. See [SECURITY.md](SECURITY.md).


## AI gateway (27 Sep 2026, docs/PLAN-AI-GATEWAY.md §1)

With `LLM_BACKEND=hosted` every cloud chain above is wrapped in `RoutedLLM` → `ai_gateway.Gateway`
(`agents/src/blockid_agents/ai_gateway.py`). The env lists (`LLM_PROVIDER_ORDER`, `SAMBANOVA_MODELS`,
`DEEPINFRA_MODELS`, `HR_*`) still define the candidate pool and — with the default `AI_ROUTING=static` — the order.
`AI_GATEWAY=0` restores the previous behaviour exactly (FallbackLLM, 10-min parking, no ledger).

| Piece | Default | Env |
|---|---|---|
| Deadlines (connect / total) | 10 s / Claude 120 s, SambaNova 60 s, DeepInfra 90 s; a hung call is cancelled (connection closed) | `AI_CONNECT_TIMEOUT_S`, `AI_DEADLINE_CLAUDE_S`, `SAMBANOVA_TIMEOUT`, `AI_DEADLINE_DEEPINFRA_S` |
| Hedging (HR + valuation routers) | after the primary's p90 (8–45 s, 20 s without data) the next healthy model starts; first schema-valid answer wins, the loser is cancelled | `AI_HEDGE`, `AI_HEDGE_DELAY_S`, `AI_HEDGE_MIN_S`, `AI_HEDGE_MAX_S` |
| Circuit breaker per model | 3 consecutive failures / ≥ 50 % errors over ≥ 6 calls in 5 min / one 429·402 → open 2, 4, 8, 10 min, then one half-open probe | — |
| Quota windows (ledger `studio.ai_usage` + `x-ratelimit-*` headers + bridge `/healthz`) | SambaNova 60 rpm / 12,000 rpd per model; bridge /complete 300/day, /search 150/day; Brave 2,000/month; DeepInfra US$3/day; demote ≥ 80 %, skip ≥ 95 % until reset | `SAMBANOVA_RPM`, `SAMBANOVA_RPD`, `BRIDGE_COMPLETE_MAX_PER_DAY`, `BRIDGE_MAX_PER_DAY`, `BRAVE_MONTHLY_QUOTA`, `DEEPINFRA_DAILY_BUDGET_USD`, `AI_LIMITS="sambanova:X=rpm:30,rpd:5000;claude-bridge=rpd:200"`, `AI_DEMOTE_PCT`, `AI_SKIP_PCT`, `AI_BRIDGE_POLL` |
| Pacing | token bucket per rate-limited model: 90 % of rpm, bursts rpm/6 | `AI_PACING_WAIT_S` |
| Concurrency + fair queue | SambaNova 6 per model, DeepInfra 8, bridge 2; the user served least recently goes first (user = `requested_by` of the valuation / HR run) | `AI_CONCURRENCY_*`, `AI_QUEUE_WAIT_S` |
| Task profiles | `extract_json` (StartupProfile, CompetitorList, FundingClaims, RelevanceVerdicts, CompanyFinancials, ValuationEvidence, PersonAnalysis, SuggestedPeople; v5: TractionClaims, MarketSizeClaims, MoatClaims, RetentionClaims, DeckFacts, IndustryPick, DealClaims), `reason_score` (QualitativeScores, Narrative, MarketAnalysis, TeamAnalysis, ContractReview; v5: StartupFactors; any `cloud_max`), `long_context` (> 30k tokens), `search`; callers may pass `profile=` | `AI_PROFILE_EXTRACT_JSON` / `_REASON_SCORE` / `_LONG_CONTEXT` (csv filters) |
| Ordering | `static`: env order; `dynamic`: quality × reliability ÷ cost (priors `ai_gateway.PRIORS` + ledger success / schema-valid rate / p90, re-ranked hourly). Always: context-window pre-check, HR `reason_score` pinned to Claude while healthy | `AI_ROUTING`, `AI_STATS_TTL_S`, `HR_REASON_SCORE_MODELS` |
| Schema repair | one retry on the same model with the validation error, then the next model | — |
| Result cache | 24 h, key = (profile, schema, prompt hash), `studio.ai_cache` | `AI_CACHE_TTL_HOURS` (0 = off) |

Feed events for the HR live progress: `llm_fallback` ("Claude busy → using DeepSeek"), `llm_rerouted`
("SambaNova DeepSeek-V3.1 near its daily limit → using …"), `llm_hedged` ("… is slow → also asking …").
Admin: `GET /v1/admin/ai/health`, `POST /v1/admin/ai/models/{id}/pause|resume` (shape in `studio/ai_admin.py`).

### Default order and benchmark

Default order = the env order in production (`SAMBANOVA_MODELS=DeepSeek-V3.1,gemma-4-31B-it,DeepSeek-V3.2`, then the
Claude bridge, then DeepInfra DeepSeek-V4-Flash, gpt-oss-120b; HR: Claude bridge → SambaNova DeepSeek-V3.1/V3.2 →
DeepInfra V4-Flash / Qwen3-235B, with Claude pinned for the team review). Rationale: free and strong first, the
scarce subscription where disambiguation matters, cheap paid models last; the gateway now demotes / skips any of them
before its limit is hit instead of waiting for a 429. All ids above were confirmed in `/models` on 2026-09-27
(context windows and prices in `config.MODEL_CONTEXT_TOKENS` / `MODEL_PRICES_USD_PER_MTOK`).

`scripts/ai-benchmark.py` (`--list`, `--record-claude`, `--run`, spend cap `--max-usd 0.50`) runs the golden set:
CompanyFinancials on the 8 backtest companies (agreement with the verified figures) and the HR fixtures
(`scripts/fixtures/hr-extraction.json`, fictional people with namesake / private-data traps: grounded facts, recall of
Claude's facts, trap facts, score MAE, team worked-together diff). The Claude reference was recorded on 2026-09-27
(Sonnet via the bridge: 12/13 facts grounded, 69–124 s per person). The model run was stopped before completion for the
deploy, so `PRIORS` still carry the 2026-09-26 SVI benchmark above and `AI_ROUTING` stays `static`. To finish:

    cd agents; set -a; . <(sudo cat /opt/blockid/app.env); set +a; unset DATABASE_URL
    .venv/bin/python ../scripts/ai-benchmark.py --run      # ~30 min, < US$0.10 estimated
    # then update ai_gateway.PRIORS from scripts/fixtures/ai-benchmark-results.json and set AI_ROUTING=dynamic
