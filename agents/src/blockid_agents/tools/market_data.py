"""Dated market-data snapshot for valuation v5 (docs/PLAN-VALUATION-V5.md §2.3).

`snapshot(dataset)` returns an immutable view of `blockid_agents/market_data/<dataset>.json` plus its sha256, so a
report records exactly which dataset it used (`svi.triangulation.market_dataset`). Every number a method uses is
copied into that method's `inputs`, so /verify never needs this file — it only feeds new valuations.
Refresh: add a new dated file in a reviewed PR and bump `valuation_params.MARKET_DATASET`; never edit an old file.
"""
from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "market_data"
_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _freeze(v: Any) -> Any:
    if isinstance(v, dict):
        return MappingProxyType({k: _freeze(x) for k, x in v.items()})
    if isinstance(v, list):
        return tuple(_freeze(x) for x in v)
    return v


class MarketSnapshot:
    def __init__(self, dataset: str, raw: bytes):
        self.dataset = dataset
        self.sha256 = hashlib.sha256(raw).hexdigest()
        self.data = _freeze(json.loads(raw))

    def country(self, code: str) -> MappingProxyType:
        c = (code or "AU").upper()
        c = {"AUS": "AU", "VNM": "VN", "VIETNAM": "VN", "AUSTRALIA": "AU"}.get(c, c)
        return self.data["countries"].get(c) or self.data["countries"]["AU"]

    def country_code(self, code: str) -> str:
        c = (code or "AU").upper()
        c = {"AUS": "AU", "VNM": "VN", "VIETNAM": "VN", "AUSTRALIA": "AU"}.get(c, c)
        return c if c in self.data["countries"] else "AU"

    def industry(self, key: str) -> MappingProxyType:
        return self.data["industries"].get(key) or self.data["industries"]["general"]

    def industry_keys(self) -> tuple[str, ...]:
        return tuple(self.data["industries"])

    def industry_for_text(self, text: str) -> str:
        """Keyword fallback when no industry was picked (first industry whose keyword appears, else 'general')."""
        t = (text or "").lower()
        for key, row in self.data["industries"].items():
            if any(k in t for k in row["keywords"]):
                return key
        return "general"

    def size_premium(self, ev_aud: float) -> float:
        for limit, prem in self.data["size_premium"]:
            if ev_aud < limit:
                return float(prem)
        return float(self.data["size_premium"][-1][1])

    def precedent_band(self, industry_key: str, ebitda_aud: float) -> tuple[str, tuple[float, float, float]]:
        th = self.data["precedent_size_thresholds_aud"]
        bands = self.data["precedent_bands"]
        if ebitda_aud < th["small_below"]:
            key = "small"
        elif ebitda_aud < th["sector_from"]:
            key = "mid_market"
        else:
            key = self.industry(industry_key)["precedent_band"]
        return key, tuple(float(x) for x in bands[key])


@lru_cache(maxsize=8)
def snapshot(dataset: str) -> MarketSnapshot:
    if not _NAME.match(dataset or ""):
        raise ValueError(f"bad dataset id {dataset!r}")
    return MarketSnapshot(dataset, (DATA_DIR / f"{dataset}.json").read_bytes())
