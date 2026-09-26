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

Search budget: ≤3 searches per valuation (`SEARCH_MAX_QUERIES`): competitors, market, company financials.

| # | Step | Query |
|---|---|---|
| 1 | competitors | `<company> competitors alternatives <country>` |
| 2 | market | `<sector> market size growth <country> <year>` (Brave freshness: past year) |
| 3 | market | `<company> revenue ARR funding valuation <year>` — top 2 pages fetched, the next 4 results kept as snippets |

After the market analysis, one more call on the same chain (`CompanyFinancials`, research agent) reads the
search-result pages (page start + passages around revenue/ARR/valuation/funding terms + the search snippet) and
returns `company_financials` (revenue_ttm, currency, revenue_year, revenue_type revenue/ARR/GMV,
funding_raised_total, last_valuation, source_url, quote). Code keeps a figure only if
the quote appears verbatim in that page or its search snippet, states that number, and the page names the company;
amounts are converted with the fixed `config.FX_TO_AUD` table (USD 1.50, EUR 1.65, GBP 1.95, SGD 1.15, VND 0.00006;
`FX_TO_AUD_AS_OF`), rate recorded. Only revenue/ARR (≤3 years old) can feed the SVI, and only when the website and
the founder gave no revenue (`profile.metrics_sources.revenue_ttm_aud = cited_source`, with a warning).

Valuation range (`tools/svi.py`, first rule that applies, then × SVI factor):
1. revenue > 0 and the verified company financials state both revenue and last valuation → implied multiple
   = last valuation ÷ revenue ("implied multiple from cited last round: 11.0x"), low/high 0.7×/1.4× of it; ignored
   outside 0.5×–40×;
2. revenue > 0 and a multiple stated in the market or company results → that multiple (single → 0.7×–1.4×);
3. revenue > 0 otherwise → `config.DEFAULT_REVENUE_MULTIPLES` (default 2.0/3.5/6.0×, SaaS/fintech/payments
   3/6/10×) — uncalibrated default, see ROADMAP calibration; review item "multiple is a default, not cited";
4. revenue = 0 → stage benchmark range.

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
