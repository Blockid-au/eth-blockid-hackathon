# LLM routing for the valuation agents

The cloud tier (site intake, competitors, market analysis, SVI scoring, narrative) runs on a fallback chain:
free SambaNova models first, then cheap paid DeepInfra models. The `local` tier (PII) never leaves the gateway.

```
LLM_PROVIDER_ORDER=sambanova,deepinfra
SAMBANOVA_MODELS=gpt-oss-120b,DeepSeek-V3.1,gemma-4-31B-it          # free tier
DEEPINFRA_MODELS=deepseek-ai/DeepSeek-V4-Flash,openai/gpt-oss-120b  # paid fallback
```

Web search is separate: Brave first, then the Claude CLI search bridge (`deploy/search-bridge`, Claude
subscription, Haiku + WebSearch only).

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
| **DeepInfra DeepSeek-V4-Flash** | 6/6 | 14.9 s | $0.00043 | 9.1 | 7.0 | 0/62 |
| DeepInfra gpt-oss-120b | 6/6 | 13.2 s | $0.00022 | 9.4 | 5.7 | 5/56 |
| DeepInfra Qwen3-235B-2507 (old default) | 3/3 | 37.8 s | $0.00051 | 17.2 | – | – |
| Claude Sonnet (CLI, subscription) | 3/3 | 29.1 s | $0.045 notional | 0 (ref) | – | – |
| Claude Haiku (CLI) | 1/3 | 32.3 s | – | 10.2 | – | – |

Notes
- gemma-4-31B-it inflates product/market scores (85–90 where Sonnet gives 55–68), so it is last among free models.
- SambaNova MiniMax-M3 returned 402 (no balance / "high demand"): not usable on the free tier.
- Claude Haiku fails `--json-schema` structured output on 2 of 3 cases; Sonnet is reliable but ~6× slower.
- Brave: this key's monthly quota is 0, so search currently runs on the Claude bridge.

## End-to-end check

Valuation of https://www.cultureamp.com/ after the change: all 6 steps done in 107 s; every LLM call
(StartupProfile, CompetitorList, MarketAnalysis, QualitativeScores, Narrative) answered by
`sambanova:gpt-oss-120b` with no fallback, so the LLM cost was US$0.
