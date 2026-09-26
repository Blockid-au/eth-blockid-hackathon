"""Issuer service configuration (environment only; see docs/IMPLEMENTATION.md "Env")."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class IssuerConfig:
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL"))
    internal_token: str = field(default_factory=lambda: _env("ISSUER_INTERNAL_TOKEN"))
    local_rpc_url: str = field(default_factory=lambda: _env("LOCAL_RPC_URL", "http://127.0.0.1:8545"))
    local_chain_id: int = field(default_factory=lambda: int(_env("LOCAL_CHAIN_ID", "262626")))
    hoodi_rpc_url: str = field(default_factory=lambda: _env("HOODI_RPC_URL", "https://ethereum-hoodi-rpc.publicnode.com"))
    hoodi_chain_id: int = field(default_factory=lambda: int(_env("HOODI_CHAIN_ID", "560048")))
    hoodi_captable_anchor: str = field(default_factory=lambda: _env("HOODI_CAPTABLE_ANCHOR"))
    # HashKey Chain testnet (second external chain; synced after Hoodi)
    hsk_rpc_url: str = field(default_factory=lambda: _env("HSK_RPC_URL"))
    hsk_chain_id: int = field(default_factory=lambda: int(_env("HSK_CHAIN_ID", "133")))
    hsk_captable_anchor: str = field(default_factory=lambda: _env("HSK_CAPTABLE_ANCHOR"))
    hsk_min_gas_price: int = field(default_factory=lambda: int(_env("HSK_MIN_GAS_PRICE_WEI", "0")))
    # gas budget used for the pre-flight balance check of an external-chain sync (units, not wei)
    sync_gas_fresh: int = field(default_factory=lambda: int(_env("SYNC_GAS_FRESH", "7000000")))
    sync_gas_existing: int = field(default_factory=lambda: int(_env("SYNC_GAS_EXISTING", "400000")))
    sync_gas_per_holder: int = field(default_factory=lambda: int(_env("SYNC_GAS_PER_HOLDER", "260000")))
    local_demo_aud: str = field(default_factory=lambda: _env("LOCAL_DEMO_AUD"))
    keystore_dir: str = field(default_factory=lambda: _env("KEYSTORE_DIR", "/keys"))
    keystore_password_dir: str = field(default_factory=lambda: _env("KEYSTORE_PASSWORD_DIR"))
    deployer_account: str = field(default_factory=lambda: _env("DEPLOYER_ACCOUNT", "blockid-deployer"))
    relayer_account: str = field(default_factory=lambda: _env("RELAYER_ACCOUNT", "blockid-relayer"))
    public_base_url: str = field(default_factory=lambda: _env("PUBLIC_BASE_URL", "https://eth.blockid.au"))
    port: int = field(default_factory=lambda: int(_env("ISSUER_PORT", "8090")))
    # gas-token amounts on BlockID Chain (wei of BLKD)
    drip_wei: int = field(default_factory=lambda: int(_env("DRIP_WEI", str(10**16))))            # 0.01 BLKD
    drip_below_wei: int = field(default_factory=lambda: int(_env("DRIP_BELOW_WEI", str(10**15))))  # 0.001 BLKD
    relayer_topup_wei: int = field(default_factory=lambda: int(_env("RELAYER_TOPUP_WEI", str(10**17))))
    local_min_gas_price: int = field(default_factory=lambda: int(_env("LOCAL_MIN_GAS_PRICE_WEI", "0")))
    kyc_country: int = 36  # Australia (ISO-3166 numeric)
    max_shareholders: int = 500
