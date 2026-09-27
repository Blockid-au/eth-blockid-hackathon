# Valuation reference table and backtest (valuation v3)

The reference set for `scripts/valuation-backtest.py`: the latest public valuation or market cap of each
business, with source and date, as researched on **27 Sep 2026**. AUD uses the app's dated FX table
(`config.FX_TO_AUD`, USD 1.50, as of 2026-09-26), so the engine and the reference use the same conversion.

| Business | Latest public figure | A$ (app FX) | Date | Basis | Source |
|---|---|---|---|---|---|
| Canva | US$34.9B | 52.35B | 17 Aug 2026 | Blackbird / Airtree marked their stakes down 17% (Canva's own independent valuation: US$31B; last transaction: Aug 2025 employee sale at US$42B) | [Startup Daily](https://www.startupdaily.net/advice/business-strategy/canva-wipes-10-billion-from-its-valuation-putting-ipo-plans-in-doubt/) |
| Airwallex | US$11B | 16.5B | 25 Jun 2026 | Series H post-money (US$320M raised) | [Airwallex newsroom](https://www.airwallex.com/global/newsroom/airwallex-secures-320-million-in-series-h-funding-valuation-hits-11-billion) |
| SafetyCulture | A$2.5B | 2.5B | 9 Sep 2024 | A$165M round (primary + secondary) | [Forbes Australia](https://www.forbes.com.au/news/investing/safetyculture-valued-at-2-5-billion-after-165-million-funding-round/) |
| Go1 | US$2B (A$2.8B at the time) | 3.0B | 7 Jun 2022 | funding round (no newer public price found) | [Startup Daily](https://www.startupdaily.net/topic/funding/go1-doubles-its-valuation-to-2-8-billion-after-100-million-raise/) |
| Airtasker (ASX: ART) | A$97.9M | 97.9M | 25 Sep 2026 | market capitalisation | [stockanalysis.com](https://stockanalysis.com/quote/asx/ART/market-cap/) |
| Employment Hero | A$2.2B | 2.2B | 18 Feb 2025 | implied by Seek's A$95M secondary sale to KKR | [Startup Daily](https://www.startupdaily.net/topic/seek-offloads-a-95-million-slice-of-its-employment-hero-investment-to-us-private-equity-firm-kkr/) |
| Culture Amp | A$2B | 2.0B | Jul 2021 | Series F; Blackbird cut its mark by 23.5% in late 2025 (no figure published, ≈ A$1.5B implied) | [Startup Daily](https://www.startupdaily.net/topic/business/just-days-after-blackbird-slashed-its-valuation-by-nearly-a-quarter-culture-amp-reveals-it-lost-another-37-million-last-financial-year/) |
| Linktree | US$1.3B | 1.95B | 16 Mar 2022 | funding round (US$110M) | [TechCrunch](https://techcrunch.com/2022/03/16/linktree-link-in-bio-series-c-valuation/) |

Supporting figures used by the fixtures: Canva ARR US$4B end-2025 ([TechCrunch](https://techcrunch.com/2026/02/18/canva-gets-to-4b-in-revenue-as-llm-referral-traffic-rises/));
Airwallex US$1.3B annualised revenue (newsroom above); Employment Hero A$250M ARR (Startup Daily above); Culture Amp
FY25 revenue US$177M (Startup Daily above); Airtasker revenue A$57.8M (stockanalysis above); public SaaS median
EV/Revenue 4.6x, Aug 2026 ([Aventis Advisors](https://aventis-advisors.com/saas-valuation-multiples/)); fintech median
EV/Revenue 7.6x, Q1 2026 ([Finro](https://www.finrofca.com/news/fintech-valuation-multiples-q1-2026)).

## Backtest result (offline replay, 27 Sep 2026)

`cd agents && .venv/bin/python ../scripts/valuation-backtest.py --ablation`

| Business | Reference A$ | v3 value A$ | Error | Confidence | Methods used (weight) | v2 on the live site | v3 without anchors |
|---|---|---|---|---|---|---|---|
| Canva | 52.35B | 40.56B | −22.5% | medium | own price 69% · revenue × multiple 31% | +55.3% (A$81.3B) | −60.5% |
| Airwallex | 16.5B | 15.08B | −8.6% | high | own price 74% · revenue × multiple 26% | −69.2% (A$5.08B) | −32.6% |
| SafetyCulture | 2.5B | 2.5B | 0.0% | high | own price 100% | −96.9% (A$77.1M) | −96.9% |
| Go1 | 3.0B | 3.0B | 0.0% | medium | own price 100% (51 months old) | −97.4% (A$79.4M) | −97.5% |
| Airtasker | 97.9M | 101.6M | +3.8% | high | market cap 93% · revenue 4% · stage 3% | −22.9% (A$75.5M) | +53.6% |
| Employment Hero | 2.2B | 1.76B | −20.2% | medium | own price 67% · revenue × multiple 33% | −97.0% (A$65.3M) | −60.8% |
| Culture Amp | 2.0B | 1.24B | −38.2% | medium | own price 30% (2021) · revenue × multiple 70% | – | −54.2% |
| Linktree | 1.95B | 1.95B | 0.0% | medium | own price 100% (2022) | – | −96.1% |

**Median |error|: v3 6.2%** (target ≤ 30%) · v2 as shown on eth.blockid.au today 83.1% (6 companies) · v3 without
the company's own price 60.6%. Reference inside the v3 range: 5/8.

How to read this honestly:
- The offline run replays **recorded** research (page excerpts at the real URLs + the model's extraction answers,
  `scripts/fixtures/valuation-backtest.json`). It tests the deterministic part end to end — quote verification, FX,
  dating, listing detection, weights, blend — through the real graph. It does not measure how often the live search
  finds these pages or how well the live model extracts them. Run `--live` for that (see below).
- When the business's own recent price is found, v3 lands on it by design (it is the market's number). The
  "without anchors" column shows what the fundamental methods alone give: revenue × sector multiple under-values
  fast growers (public-SaaS median 4.6x with a 25% private discount), and a growth-stage business with no revenue
  found falls back to the stage benchmark (tens of millions) — far off for unicorns.
- Stale references (Go1 2022, Linktree 2022, Culture Amp 2021) score 0% because the engine finds the same old
  number; their confidence is **medium** and the report says the price is old. For Culture Amp the engine leans on
  revenue because the 2021 price is five years old; its A$1.24B is closer to Blackbird's 2025 mark (≈ A$1.5B) than to
  the 2021 round.

## Running it live

Same code path as the worker (the graph, real search chain and LLM chain), never the production API:

```
sudo cat /opt/blockid/app.env > /tmp/w.env          # root-only; or export the same variables yourself
cd agents && set -a && . /tmp/w.env && set +a
BLOCKID_DATA_DIR=$(mktemp -d) DATABASE_URL= .venv/bin/python ../scripts/valuation-backtest.py --live --json /tmp/bt.json
rm /tmp/w.env
```

Needs `LLM_BACKEND=hosted` with SambaNova / claude_bridge / DeepInfra keys and `SEARCH_PROVIDERS` (Claude bridge
`/search` must be reachable from where it runs; the worker uses the docker host address). Cost per company: ≤ 8
searches (≤ 3 pages each) and about 9 LLM calls. Set `SEARCH_MAX_QUERIES=8`, `SEARCH_FETCH_PER_QUERY=3` (the
defaults) — `app.env` may still pin the old 3 / 2.
