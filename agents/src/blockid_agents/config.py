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

    # --- Web search (tools/search.py): providers tried in order ------------------------------
    search_providers: tuple[str, ...] = field(default_factory=lambda: tuple(
        x.lower() for x in _csv("SEARCH_PROVIDERS", "brave,claude")))
    claude_search_url: str = field(default_factory=lambda: _env("CLAUDE_SEARCH_URL"))  # host bridge, e.g. :8765
    claude_search_token: str = field(default_factory=lambda: _env("CLAUDE_SEARCH_TOKEN"))
    claude_search_timeout: float = field(default_factory=lambda: float(_env("CLAUDE_SEARCH_TIMEOUT", "150")))
    claude_complete_timeout: float = field(default_factory=lambda: float(_env("CLAUDE_COMPLETE_TIMEOUT", "260")))
    # Research budget per valuation ("good enough for a mid-point valuation")
    search_max_queries: int = field(default_factory=lambda: int(_env("SEARCH_MAX_QUERIES", "3")))
    search_fetch_per_query: int = field(default_factory=lambda: int(_env("SEARCH_FETCH_PER_QUERY", "2")))
    competitor_homepages_max: int = field(default_factory=lambda: int(_env("COMPETITOR_HOMEPAGES_MAX", "5")))

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
    # STUDIO_DEV=1: accept localhost SIWE domains / Origins and expose /docs. Never set in production.
    studio_dev: bool = field(default_factory=lambda: _env("STUDIO_DEV", "0").lower() in ("1", "true", "yes"))
    allowed_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        o.strip().rstrip("/") for o in _env("ALLOWED_ORIGINS", "https://eth.blockid.au").split(",") if o.strip()
    ))


def get_settings() -> Settings:
    return Settings()
