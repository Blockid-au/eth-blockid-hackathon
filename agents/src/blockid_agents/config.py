"""Runtime configuration (12-factor: everything from environment variables).

Secrets (API keys, DB passwords) are injected by GCP Secret Manager at container start
(see deploy/vm-app/docker-compose.yml) — never committed and never readable by the AI VM.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in _env(name, default).split(",") if x.strip())


# Fixed, indicative currency -> AUD rates used to convert figures quoted in sources (company revenue from search
# results, competitor funding). Fixed on purpose so a valuation is reproducible; change deliberately, bump the date,
# and every conversion records the rate and FX_TO_AUD_AS_OF it used. Currencies not listed are not converted
# (the figure is dropped rather than guessed).
FX_TO_AUD_AS_OF = "2026-09-26"
FX_TO_AUD: dict[str, float] = {
    "AUD": 1.0, "USD": 1.50, "EUR": 1.65, "GBP": 1.95, "SGD": 1.15, "VND": 0.00006,
    # also accepted for competitor funding (same fixed basis)
    "NZD": 0.91, "CAD": 1.10, "HKD": 0.195, "JPY": 0.0102, "CNY": 0.21, "INR": 0.018, "CHF": 1.75, "SEK": 0.15,
    "KRW": 0.0011, "IDR": 0.000095, "ILS": 0.41,
}


# Revenue multiples (low, median, high) used ONLY when a company has revenue but no multiple is cited in the
# evidence and no implied multiple (cited last valuation / cited revenue) is available. UNCALIBRATED DEFAULTS —
# conservative placeholders pending the SVI calibration work (docs/ROADMAP-RESEARCH.md); every valuation that uses
# them says so in its method and gets a "multiple is a default, not cited" review item.
DEFAULT_REVENUE_MULTIPLES: dict[str, tuple[float, float, float]] = {
    "default": (2.0, 3.5, 6.0),
    "saas_fintech": (3.0, 6.0, 10.0),
}
SAAS_FINTECH_TERMS = ("saas", "software", "fintech", "payment", "banking", "financial technology", "cloud",
                      "platform as a service", "api")


def default_multiples(sector: str) -> tuple[str, tuple[float, float, float]]:
    """(table key, (low, median, high)) for a sector description."""
    s = (sector or "").lower()
    key = "saas_fintech" if any(t in s for t in SAAS_FINTECH_TERMS) else "default"
    return key, DEFAULT_REVENUE_MULTIPLES[key]


# Implied multiple (cited last valuation / cited revenue) is used only inside these bounds.
IMPLIED_MULTIPLE_BOUNDS = (0.5, 40.0)

# ---------------------------------------------------------------- valuation v3 (tools/triangulate.py)
# Every weight below is a deliberate, documented rule (docs/valuation-reference.md, docs/LLM-ROUTING.md).
# Market anchors: base weight by kind (a listed market cap IS the market price; a priced round is a negotiated
# price; secondary / investor marks / press-reported values are weaker signals).
ANCHOR_KIND_WEIGHT: dict[str, float] = {
    "market_cap": 3.0, "priced_round": 1.0, "secondary_sale": 0.9, "investor_mark": 0.8, "reported_valuation": 0.7,
}
# (max age in months, weight factor): the first band that fits applies. Older than 24 months -> much lower weight.
ANCHOR_RECENCY: tuple[tuple[float, float], ...] = ((12, 1.0), (24, 0.8), (36, 0.45), (60, 0.3), (1e9, 0.15))
ANCHOR_UNKNOWN_DATE_FACTOR = 0.35
MARKET_CAP_MAX_AGE_MONTHS = 3  # a market cap older than this is treated as a reported valuation
ANCHOR_AUD_BOUNDS = (100_000.0, 5e12)
# Revenue x multiple: base weight x multiple-source factor x revenue-source factor.
REVENUE_METHOD_WEIGHT = 0.6
MULTIPLE_SOURCE_FACTOR: dict[str, float] = {
    "comps_3plus": 1.0, "comps_1_2": 0.8, "sector_cited": 0.7, "market_analysis": 0.5, "default": 0.25,
}
REVENUE_SOURCE_FACTOR: dict[str, float] = {"self_reported": 0.9, "website": 0.9, "cited_source": 0.85}
MULTIPLE_BOUNDS = (0.3, 40.0)  # verified comps / sector multiples outside this are dropped
PRIVATE_COMPANY_DISCOUNT = 0.25  # applied when an unlisted company is priced off listed-company multiples
# Stage / scorecard (SVI stage benchmark x SVI factor): lowest weight when another method exists; ignored when it
# is more than STAGE_OUTLIER_RATIO away from the other methods (a stage table means nothing at Canva's scale).
STAGE_METHOD_WEIGHT_ALONE = 1.0
STAGE_METHOD_WEIGHT_WITH_OTHERS = 0.1
STAGE_OUTLIER_RATIO = 5.0
# Minimum half-width of the blended range by confidence (the method spread widens it further).
RANGE_MIN_HALF_WIDTH: dict[str, float] = {"high": 0.10, "medium": 0.20, "low": 0.35}


# ---------------------------------------------------------------- AI gateway (ai_gateway.py, docs/LLM-ROUTING.md)
# Prices in US$ per 1M tokens (input, output) as listed by each provider's /models on 2026-09-27. SambaNova is the
# free tier for this key (its /models lists paid-tier prices, not charged), Claude runs on the subscription (host
# bridge / CLI): both are 0 marginal cost here, their scarcity is handled by the quota windows instead.
# Used for the estimated spend in the usage ledger (DEEPINFRA_DAILY_BUDGET_USD) and the router's cost term.
MODEL_PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "deepinfra:deepseek-ai/DeepSeek-V4-Flash": (0.09, 0.18),
    "deepinfra:openai/gpt-oss-120b": (0.037, 0.17),
    "deepinfra:Qwen/Qwen3-235B-A22B-Instruct-2507": (0.09, 0.55),
    "deepinfra:deepseek-ai/DeepSeek-V3.2": (0.26, 0.38),
    "deepinfra:deepseek-ai/DeepSeek-V3.1": (0.25, 0.95),
    "deepinfra:moonshotai/Kimi-K2.6": (0.75, 3.5),
    "deepinfra:zai-org/GLM-4.7": (0.4, 1.75),
    "deepinfra:deepseek-ai/DeepSeek-V4-Pro": (1.3, 2.6),
    "deepinfra:meta-llama/Llama-3.3-70B-Instruct-Turbo": (0.1, 0.32),
    "deepinfra:google/gemma-4-31B-it": (0.13, 0.38),
    "deepinfra:Qwen/Qwen3-Next-80B-A3B-Instruct": (0.09, 1.1),
}
DEFAULT_PAID_PRICE_USD_PER_MTOK = (0.5, 2.0)  # unknown DeepInfra model: assume a mid-priced one (conservative)
# Context windows (tokens) from the providers' /models (2026-09-27). Unknown models: 32k (the router then keeps them
# off long prompts until their window is added here).
MODEL_CONTEXT_TOKENS: dict[str, int] = {
    "sambanova:DeepSeek-V3.1": 131072, "sambanova:DeepSeek-V3.2": 32768, "sambanova:gpt-oss-120b": 131072,
    "sambanova:Meta-Llama-3.3-70B-Instruct": 131072, "sambanova:gemma-4-31B-it": 262144,
    "sambanova:MiniMax-M2.7": 196608,
    "deepinfra:deepseek-ai/DeepSeek-V4-Flash": 1048576, "deepinfra:openai/gpt-oss-120b": 131072,
    "deepinfra:Qwen/Qwen3-235B-A22B-Instruct-2507": 262144, "deepinfra:deepseek-ai/DeepSeek-V3.2": 163840,
    "deepinfra:deepseek-ai/DeepSeek-V3.1": 163840, "deepinfra:moonshotai/Kimi-K2.6": 262144,
    "deepinfra:zai-org/GLM-4.7": 202752, "deepinfra:deepseek-ai/DeepSeek-V4-Pro": 1048576,
    "deepinfra:meta-llama/Llama-3.3-70B-Instruct-Turbo": 131072, "deepinfra:google/gemma-4-31B-it": 262144,
    "deepinfra:Qwen/Qwen3-Next-80B-A3B-Instruct": 262144,
    # the bridge refuses bodies > 600 KB (~150k tokens); Sonnet's own window is 200k
    "claude-bridge": 150000, "claude-cli": 200000,
}
DEFAULT_CONTEXT_TOKENS = 32768


def _limits_env(raw: str) -> dict[str, dict[str, float]]:
    """AI_LIMITS="sambanova:DeepSeek-V3.1=rpm:30,rpd:5000;claude-bridge=rpd:200" -> per-model limit overrides."""
    out: dict[str, dict[str, float]] = {}
    for part in (raw or "").split(";"):
        if "=" not in part:
            continue
        mid, spec = part.rsplit("=", 1) if part.count("=") > 1 else part.split("=", 1)
        vals = {}
        for kv in spec.split(","):
            k, _, v = kv.partition(":")
            try:
                vals[k.strip().lower()] = float(v)
            except ValueError:
                continue
        if mid.strip() and vals:
            out[mid.strip()] = vals
    return out


def fx_to_aud(currency: str) -> float | None:
    return FX_TO_AUD.get((currency or "").upper().strip())


@dataclass(frozen=True)
class Settings:
    # --- LLM gateway (LiteLLM on the AI VM, OpenAI-compatible) -----------------------------
    llm_gateway_url: str = field(default_factory=lambda: _env("LLM_GATEWAY_URL", "http://10.20.0.10:4000/v1"))
    llm_gateway_key: str = field(default_factory=lambda: _env("LLM_GATEWAY_KEY"))
    # Model aliases defined in deploy/vm-ai/litellm-config.yaml
    model_local: str = field(default_factory=lambda: _env("MODEL_LOCAL", "local-qwen"))
    model_cloud: str = field(default_factory=lambda: _env("MODEL_CLOUD", "cloud-sonnet"))
    model_cloud_max: str = field(default_factory=lambda: _env("MODEL_CLOUD_MAX", "cloud-opus"))

    # --- Hosted backend (LLM_BACKEND=hosted): Claude CLI first, DeepInfra as fallback -----------
    llm_backend: str = field(default_factory=lambda: _env("LLM_BACKEND", "gateway"))  # gateway | hosted
    claude_cli_enabled: bool = field(default_factory=lambda: _env("CLAUDE_CLI_ENABLED", "true").lower() == "true")
    claude_cli_path: str = field(default_factory=lambda: _env("CLAUDE_CLI_PATH"))  # empty -> auto-detect
    claude_cli_timeout: float = field(default_factory=lambda: float(_env("CLAUDE_CLI_TIMEOUT", "300")))
    claude_model_cloud: str = field(default_factory=lambda: _env("CLAUDE_MODEL_CLOUD", "sonnet"))
    claude_model_cloud_max: str = field(default_factory=lambda: _env("CLAUDE_MODEL_CLOUD_MAX", "opus"))
    deepinfra_api_key: str = field(default_factory=lambda: _env("DEEPINFRA_API_KEY"))
    deepinfra_base_url: str = field(
        default_factory=lambda: _env("DEEPINFRA_BASE_URL", "https://api.deepinfra.com/v1/openai")
    )
    # Paid fallback, tried in order. Benchmarked 2026-09-26 on SVI scoring vs Claude Sonnet (docs/LLM-ROUTING.md):
    # DeepSeek-V4-Flash is closest to Sonnet with no invented URLs (~US$0.0004/call); gpt-oss-120b is cheapest.
    deepinfra_models: tuple[str, ...] = field(default_factory=lambda: tuple(
        m.strip() for m in _env("DEEPINFRA_MODELS", "deepseek-ai/DeepSeek-V4-Flash,openai/gpt-oss-120b").split(",")
        if m.strip()
    ))

    # SambaNova Cloud (OpenAI-compatible, fast, free tier; limits are per model — this key reports 60 req/min and
    # 12k req/day — so several models are chained). gpt-oss-120b first: closest free model to Sonnet on SVI
    # scoring, ~5 s/call, no invented URLs; gemma-4-31B-it last because it inflates product/market scores.
    sambanova_api_key: str = field(default_factory=lambda: _env("SAMBANOVA_API_KEY"))
    sambanova_base_url: str = field(default_factory=lambda: _env("SAMBANOVA_BASE_URL", "https://api.sambanova.ai/v1"))
    sambanova_models: tuple[str, ...] = field(default_factory=lambda: _csv(
        "SAMBANOVA_MODELS", "gpt-oss-120b,DeepSeek-V3.1,DeepSeek-V3.2,Meta-Llama-3.3-70B-Instruct,gemma-4-31B-it"))
    sambanova_timeout: float = field(default_factory=lambda: float(_env("SAMBANOVA_TIMEOUT", "60")))
    # Cloud-tier fallback chain after the Claude CLI (when CLAUDE_CLI_ENABLED; list "claude" to place it
    # elsewhere). Providers without an API key are skipped. "claude_bridge" = the host bridge's /complete endpoint
    # (Claude subscription, no tools); it uses CLAUDE_SEARCH_URL/TOKEN. Recommended: sambanova,claude_bridge,deepinfra
    # (free first, then subscription, then paid).
    llm_provider_order: tuple[str, ...] = field(default_factory=lambda: tuple(
        x.lower() for x in _csv("LLM_PROVIDER_ORDER", "sambanova,deepinfra")))

    # --- AI gateway (ai_gateway.py; docs/PLAN-AI-GATEWAY.md §1, docs/LLM-ROUTING.md) ------------------------------
    # dynamic: each task profile orders its candidates by quality x reliability / cost (ledger + benchmark priors);
    # static: the env order above (LLM_PROVIDER_ORDER / *_MODELS) — health (breaker, quota) still demotes / skips.
    # AI_GATEWAY=0: the previous behaviour exactly (FallbackLLM in env order, per-backend 10-min parking, no ledger).
    ai_gateway: bool = field(default_factory=lambda: _env("AI_GATEWAY", "1").lower() in ("1", "true", "yes"))
    # default static until scripts/ai-benchmark.py has refreshed the priors on the live keys (docs/LLM-ROUTING.md)
    ai_routing: str = field(default_factory=lambda: _env("AI_ROUTING", "static").lower())
    ai_connect_timeout_s: float = field(default_factory=lambda: float(_env("AI_CONNECT_TIMEOUT_S", "10")))
    ai_deadline_claude_s: float = field(default_factory=lambda: float(_env("AI_DEADLINE_CLAUDE_S", "120")))
    ai_deadline_deepinfra_s: float = field(default_factory=lambda: float(_env("AI_DEADLINE_DEEPINFRA_S", "90")))
    # SambaNova's deadline is SAMBANOVA_TIMEOUT (default 60 s)
    ai_hedge: bool = field(default_factory=lambda: _env("AI_HEDGE", "1").lower() in ("1", "true", "yes"))
    ai_hedge_delay_s: float = field(default_factory=lambda: float(_env("AI_HEDGE_DELAY_S", "20")))  # no p90 yet
    ai_hedge_min_s: float = field(default_factory=lambda: float(_env("AI_HEDGE_MIN_S", "8")))
    ai_hedge_max_s: float = field(default_factory=lambda: float(_env("AI_HEDGE_MAX_S", "45")))
    ai_demote_pct: float = field(default_factory=lambda: float(_env("AI_DEMOTE_PCT", "80")))
    ai_skip_pct: float = field(default_factory=lambda: float(_env("AI_SKIP_PCT", "95")))
    ai_pacing_wait_s: float = field(default_factory=lambda: float(_env("AI_PACING_WAIT_S", "10")))
    ai_queue_wait_s: float = field(default_factory=lambda: float(_env("AI_QUEUE_WAIT_S", "30")))
    ai_cache_ttl_hours: float = field(default_factory=lambda: float(_env("AI_CACHE_TTL_HOURS", "24")))  # 0 = off
    ai_stats_ttl_s: float = field(default_factory=lambda: float(_env("AI_STATS_TTL_S", "3600")))  # re-rank hourly
    # concurrency caps: SambaNova per model, the others per provider (a fair per-user queue waits for a slot)
    ai_concurrency_sambanova: int = field(default_factory=lambda: int(_env("AI_CONCURRENCY_SAMBANOVA", "6")))
    ai_concurrency_deepinfra: int = field(default_factory=lambda: int(_env("AI_CONCURRENCY_DEEPINFRA", "8")))
    ai_concurrency_claude_bridge: int = field(default_factory=lambda: int(_env("AI_CONCURRENCY_CLAUDE_BRIDGE", "2")))
    # known limits (demote at >= AI_DEMOTE_PCT of a window, skip at >= AI_SKIP_PCT until it resets)
    sambanova_rpm: int = field(default_factory=lambda: int(_env("SAMBANOVA_RPM", "60")))  # per model
    sambanova_rpd: int = field(default_factory=lambda: int(_env("SAMBANOVA_RPD", "12000")))  # per model
    bridge_complete_max_per_day: int = field(default_factory=lambda: int(_env("BRIDGE_COMPLETE_MAX_PER_DAY", "300")))
    bridge_search_max_per_day: int = field(default_factory=lambda: int(_env("BRIDGE_MAX_PER_DAY", "150")))
    brave_monthly_quota: int = field(default_factory=lambda: int(_env("BRAVE_MONTHLY_QUOTA", "2000")))
    deepinfra_daily_budget_usd: float = field(default_factory=lambda: float(_env("DEEPINFRA_DAILY_BUDGET_USD", "3")))
    ai_limits: dict = field(default_factory=lambda: _limits_env(_env("AI_LIMITS")))  # per-model overrides
    # read the bridge's GET /healthz counters (complete_today / today) at most once a minute: they also count calls
    # the ledger has not seen (e.g. before a deploy), so the bridge windows start from the real usage
    ai_bridge_poll: bool = field(default_factory=lambda: _env("AI_BRIDGE_POLL", "1").lower() in ("1", "true", "yes"))
    # optional per-profile candidate filters (csv of model ids, e.g. "sambanova:DeepSeek-V3.1,claude-bridge")
    ai_profile_extract_json: tuple[str, ...] = field(default_factory=lambda: _csv("AI_PROFILE_EXTRACT_JSON", ""))
    ai_profile_reason_score: tuple[str, ...] = field(default_factory=lambda: _csv("AI_PROFILE_REASON_SCORE", ""))
    ai_profile_long_context: tuple[str, ...] = field(default_factory=lambda: _csv("AI_PROFILE_LONG_CONTEXT", ""))

    # --- Web search (tools/search.py): providers tried in order ------------------------------
    search_providers: tuple[str, ...] = field(default_factory=lambda: tuple(
        x.lower() for x in _csv("SEARCH_PROVIDERS", "brave,claude")))
    claude_search_url: str = field(default_factory=lambda: _env("CLAUDE_SEARCH_URL"))  # host bridge, e.g. :8765
    claude_search_token: str = field(default_factory=lambda: _env("CLAUDE_SEARCH_TOKEN"))
    claude_search_timeout: float = field(default_factory=lambda: float(_env("CLAUDE_SEARCH_TIMEOUT", "150")))
    claude_complete_timeout: float = field(default_factory=lambda: float(_env("CLAUDE_COMPLETE_TIMEOUT", "260")))
    # Research budget per valuation (valuation v3): at most 8 searches, each planned by purpose (tools/search.py
    # QUERY_PLAN: competitors, market size, company revenue, company valuation/round, market cap if listed,
    # comparable multiples), at most 3 result pages fetched per search. Every attempt is logged in `searches`.
    search_max_queries: int = field(default_factory=lambda: min(int(_env("SEARCH_MAX_QUERIES", "8")), 16))
    search_fetch_per_query: int = field(default_factory=lambda: min(int(_env("SEARCH_FETCH_PER_QUERY", "3")), 4))
    competitor_homepages_max: int = field(default_factory=lambda: int(_env("COMPETITOR_HOMEPAGES_MAX", "5")))

    # --- People Analyst (founding-team review, agents/people.py; docs/LLM-ROUTING.md "People Analyst") ----------
    # Its own LLM chain (the valuation chain above is unchanged): Claude via the host bridge first (best person
    # disambiguation), then free SambaNova, then cheap DeepInfra models (both verified in /models on 2026-09-27).
    hr_llm_provider_order: tuple[str, ...] = field(default_factory=lambda: tuple(
        x.lower() for x in _csv("HR_LLM_PROVIDER_ORDER", "claude_bridge,sambanova,deepinfra")))
    hr_sambanova_models: tuple[str, ...] = field(default_factory=lambda: _csv(
        "HR_SAMBANOVA_MODELS", "DeepSeek-V3.1,DeepSeek-V3.2"))
    hr_deepinfra_models: tuple[str, ...] = field(default_factory=lambda: _csv(
        "HR_DEEPINFRA_MODELS", "deepseek-ai/DeepSeek-V4-Flash,Qwen/Qwen3-235B-A22B-Instruct-2507"))
    # models tried first for the People Analyst's reason_score calls (the team review) when healthy
    hr_reason_score_models: tuple[str, ...] = field(default_factory=lambda: _csv(
        "HR_REASON_SCORE_MODELS", "claude-bridge"))
    hr_search_providers: tuple[str, ...] = field(default_factory=lambda: tuple(
        x.lower() for x in _csv("HR_SEARCH_PROVIDERS", "claude,brave")))
    hr_tier: str = field(default_factory=lambda: _env("HR_TIER", "cloud"))
    hr_searches_per_person: int = field(default_factory=lambda: min(int(_env("HR_SEARCHES_PER_PERSON", "3")), 3))
    # team cap 20 (HR v3, owner decision D1: room for the claim-led searches); per person: 3 general + up to 3 aimed
    # at the CV's most important claims (docs/PLAN-HR-V3.md §1.2)
    hr_searches_per_team: int = field(default_factory=lambda: min(int(_env("HR_SEARCHES_PER_TEAM", "20")), 20))
    hr_claim_searches_per_person: int = field(default_factory=lambda: min(int(_env(
        "HR_CLAIM_SEARCHES_PER_PERSON", "3")), 3))
    # free structured lookups for the CV cross-check (tools/people_lookups.py); empty = none
    hr_lookups: tuple[str, ...] = field(default_factory=lambda: tuple(
        x.lower() for x in _csv("HR_LOOKUPS", "wayback,github,openalex")
        if x.lower() in ("wayback", "github", "openalex")))
    hr_runs_per_day: int = field(default_factory=lambda: int(_env("HR_RUNS_PER_DAY", "5")))
    hr_max_active: int = field(default_factory=lambda: int(_env("HR_MAX_ACTIVE", "5")))
    hr_public_url: str = field(default_factory=lambda: _env("HR_PUBLIC_URL", "https://hr.blockid.au").rstrip("/"))

    # --- Brave Search ----------------------------------------------------------------------
    brave_api_key: str = field(default_factory=lambda: _env("BRAVE_API_KEY"))
    brave_max_rps: float = field(default_factory=lambda: float(_env("BRAVE_MAX_RPS", "1")))
    brave_cache_ttl_hours: int = field(default_factory=lambda: int(_env("BRAVE_CACHE_TTL_HOURS", "72")))
    # Model tier for the research + valuation agents (both see only public or redacted data).
    svi_tier: str = field(default_factory=lambda: _env("SVI_TIER", "local"))

    # --- Storage ---------------------------------------------------------------------------
    data_dir: str = field(default_factory=lambda: _env("BLOCKID_DATA_DIR", "./data"))
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", ""))  # Postgres in prod

    # --- Chain -----------------------------------------------------------------------------
    chain_id: int = field(default_factory=lambda: int(_env("BLOCKID_CHAIN_ID", "262626")))
    chain_rpc: str = field(default_factory=lambda: _env("BLOCKID_CHAIN_RPC", "http://127.0.0.1:8545"))
    issuer_safe: str = field(default_factory=lambda: _env("ISSUER_SAFE", "0x" + "0" * 40))
    contracts_dir: str = field(default_factory=lambda: _env("CONTRACTS_DIR", "../contracts"))

    # --- Async AI (GPU on demand) ----------------------------------------------------------
    gcp_project: str = field(default_factory=lambda: _env("GCP_PROJECT"))
    ai_vm_zone: str = field(default_factory=lambda: _env("AI_VM_ZONE", "asia-southeast1-c"))
    ai_vm_name: str = field(default_factory=lambda: _env("AI_VM_NAME", "blockid-ai"))
    gpu_autostart: bool = field(default_factory=lambda: _env("GPU_AUTOSTART", "false").lower() == "true")

    # --- API -------------------------------------------------------------------------------
    api_key: str = field(default_factory=lambda: _env("BLOCKID_API_KEY"))

    # --- Issuance Studio (docs/IMPLEMENTATION.md) ---------------------------------------------
    admin_wallets: tuple[str, ...] = field(default_factory=lambda: tuple(
        a.strip().lower() for a in _env("ADMIN_WALLETS").split(",") if a.strip()
    ))
    admin_username: str = field(default_factory=lambda: _env("ADMIN_USERNAME", "admin"))
    admin_password_hash: str = field(default_factory=lambda: _env("ADMIN_PASSWORD_HASH"))
    session_secret: str = field(default_factory=lambda: _env("SESSION_SECRET"))
    session_hours: int = field(default_factory=lambda: int(_env("SESSION_HOURS", "12")))
    issuer_url: str = field(default_factory=lambda: _env("ISSUER_URL", "http://issuer:8090"))
    issuer_internal_token: str = field(default_factory=lambda: _env("ISSUER_INTERNAL_TOKEN"))
    local_rpc_url: str = field(default_factory=lambda: _env("LOCAL_RPC_URL", "http://127.0.0.1:8545"))
    local_chain_id: int = field(default_factory=lambda: int(_env("LOCAL_CHAIN_ID", "262626")))
    hoodi_rpc_url: str = field(default_factory=lambda: _env("HOODI_RPC_URL"))
    hoodi_chain_id: int = field(default_factory=lambda: int(_env("HOODI_CHAIN_ID", "560048")))
    hsk_chain_id: int = field(default_factory=lambda: int(_env("HSK_CHAIN_ID", "133")))
    public_base_url: str = field(default_factory=lambda: _env("PUBLIC_BASE_URL", "https://eth.blockid.au"))
    valuations_per_day: int = field(default_factory=lambda: int(_env("VALUATIONS_PER_DAY", "3")))
    site_max_pages: int = field(default_factory=lambda: int(_env("SITE_MAX_PAGES", "6")))
    valuations_global_per_day: int = field(default_factory=lambda: int(_env("VALUATIONS_GLOBAL_PER_DAY", "60")))
    valuations_max_active: int = field(default_factory=lambda: int(_env("VALUATIONS_MAX_ACTIVE", "5")))
    # Sign-in without MetaMask (accounts.py). GOOGLE_CLIENT_ID is the public OAuth web client id (not a secret).
    google_client_id: str = field(default_factory=lambda: _env("GOOGLE_CLIENT_ID"))
    # OPEN_ISSUE=1 (demo default): any signed-in wallet may submit its company for admin approval, without first
    # being granted the issuer-wallet role. The admin approval gate is unchanged.
    open_issue: bool = field(default_factory=lambda: _env("OPEN_ISSUE", "1").lower() in ("1", "true", "yes"))
    # DEMO_WALLET: the project's shared demo investor. POST /v1/auth/demo opens a session for it (no login), so a first
    # visit lands straight in a working account. Its key is not used by the app (/opt/blockid/demo-wallet.key, root).
    demo_wallet: str = field(default_factory=lambda: _env("DEMO_WALLET"))
    # Wallet whose holdings /v1/demo/holdings shows ("" = the wallet holding shares in the most companies).
    demo_holder: str = field(default_factory=lambda: _env("DEMO_HOLDER"))
    # STUDIO_DEV=1: accept localhost SIWE domains / Origins and expose /docs. Never set in production.
    studio_dev: bool = field(default_factory=lambda: _env("STUDIO_DEV", "0").lower() in ("1", "true", "yes"))
    allowed_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        o.strip().rstrip("/") for o in _env("ALLOWED_ORIGINS", "https://eth.blockid.au").split(",") if o.strip()
    ))


def get_settings() -> Settings:
    return Settings()
