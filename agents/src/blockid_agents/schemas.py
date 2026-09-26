"""Typed contracts between agents. Every hand-off in the graph is one of these models."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
BYTES32_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")


def _addr(v: str) -> str:
    if not ADDRESS_RE.match(v):
        raise ValueError(f"not an EVM address: {v}")
    return v


# ------------------------------------------------------------------ Intake
class Founder(BaseModel):
    name: str
    role: str
    years_experience: float = 0
    prior_exits: int = 0
    domain_expertise: bool = False


class Metrics(BaseModel):
    revenue_ttm_aud: float = 0
    revenue_growth_yoy_pct: float = 0
    gross_margin_pct: float = 0
    burn_monthly_aud: float = 0
    runway_months: float = 0
    paying_customers: int = 0
    raised_to_date_aud: float = 0


class SelfReportedMetrics(BaseModel):
    """Optional figures a founder types in on /new. Never verified; every use is labelled `self_reported`."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    revenue_ttm_aud: float | None = Field(default=None, ge=0, le=1e12)
    revenue_growth_yoy_pct: float | None = Field(default=None, ge=-100, le=10_000)
    gross_margin_pct: float | None = Field(default=None, ge=-100, le=100)
    customers: int | None = Field(default=None, ge=0, le=1_000_000_000)
    raised_to_date_aud: float | None = Field(default=None, ge=0, le=1e12)
    runway_months: float | None = Field(default=None, ge=0, le=600)
    employees: int | None = Field(default=None, ge=0, le=10_000_000)


# self-reported field -> StartupProfile.metrics field (employees has no metric; it is shown, not scored)
SELF_REPORTED_TO_METRIC = {
    "revenue_ttm_aud": "revenue_ttm_aud",
    "revenue_growth_yoy_pct": "revenue_growth_yoy_pct",
    "gross_margin_pct": "gross_margin_pct",
    "customers": "paying_customers",
    "raised_to_date_aud": "raised_to_date_aud",
    "runway_months": "runway_months",
}


def self_reported_metric_fields(self_reported: dict | None) -> list[str]:
    """StartupProfile.metrics field names overridden by founder-provided figures."""
    return [SELF_REPORTED_TO_METRIC[k] for k, v in (self_reported or {}).items()
            if v is not None and k in SELF_REPORTED_TO_METRIC]


class StartupProfile(BaseModel):
    company_name: str
    company_number: str = ""
    country: str = "AU"
    sector: str
    stage: Literal["idea", "pre-seed", "seed", "series-a", "growth"] = "seed"
    description: str
    founders: list[Founder] = []
    metrics: Metrics = Metrics()
    competitors: list[str] = []
    search_keywords: list[str] = Field(default_factory=list, description="terms for market research")
    documents_reviewed: list[str] = []
    missing_items: list[str] = Field(default_factory=list, description="what the data room is missing")


# ------------------------------------------------------------------ Research (Brave)
class EvidenceItem(BaseModel):
    url: str
    title: str
    snippet: str = ""
    retrieved_at: float
    content_sha256: str = ""
    query: str = ""
    kind: str = ""  # site | web | search_snippet ("" -> derived: query "site" -> site, else web)


class Finding(BaseModel):
    claim: str
    source_urls: list[str] = Field(min_length=1, description="every claim must cite at least one fetched URL")


class MarketAnalysis(BaseModel):
    market_summary: str
    market_growth_pct: float | None = None
    revenue_multiple_low: float | None = None
    revenue_multiple_median: float | None = None
    revenue_multiple_high: float | None = None
    competitor_notes: list[Finding] = []
    key_findings: list[Finding] = []
    risks: list[Finding] = []
    confidence: Literal["low", "medium", "high"] = "low"


# ------------------------------------------------------------------ Valuation (SVI)
Basis = Literal["computed", "ai_suggested", "human", "self_reported"]


class DimensionScore(BaseModel):
    score: float = Field(ge=0, le=100)
    basis: Basis
    rationale: str = ""
    sources: list[str] = []


class QualitativeScores(BaseModel):
    """What the LLM is allowed to suggest. Numbers from metrics are NOT here — code computes them."""

    founder_quality: DimensionScore
    product_strength: DimensionScore
    market_attractiveness: DimensionScore
    investment_readiness: DimensionScore
    trust_verification: DimensionScore


class SVIResult(BaseModel):
    index: float
    band: str
    dimensions: dict[str, DimensionScore]
    weights: dict[str, float]
    valuation_low_aud: float
    valuation_mid_aud: float
    valuation_high_aud: float
    method: str
    needs_human_review: list[str]
    report_sha256: str = ""
    narrative: str = ""


class Narrative(BaseModel):
    summary: str
    strengths: list[str]
    concerns: list[str]


# ------------------------------------------------------------------ Contracts / chain
class TokenParams(BaseModel):
    name: str
    symbol: str = Field(pattern=r"^[A-Z0-9\-]{2,16}$")
    companyName: str
    companyNumber: str
    shareClass: str = Field(pattern=r"^[A-Z0-9\-]{2,12}$")
    issuerSafe: str
    transferAgent: str
    kycAgent: str
    identityRegistry: str = "0x" + "0" * 40
    lockupUntil: int = Field(ge=0)
    maxShareholders: int = Field(ge=0, le=100_000)
    legalDocHash: str

    _v_addr = field_validator("issuerSafe", "transferAgent", "kycAgent", "identityRegistry")(_addr)

    @field_validator("legalDocHash")
    @classmethod
    def _v_hash(cls, v: str) -> str:
        if not BYTES32_RE.match(v):
            raise ValueError("legalDocHash must be 0x + 32 bytes hex")
        return v


class ContractCheck(BaseModel):
    forge_passed: bool
    forge_summary: str
    slither_high: int
    slither_medium: int
    slither_summary: str
    ai_review: str = ""
    ai_review_blocking_issues: list[str] = []


class ContractReview(BaseModel):
    """Output of the cloud reviewer on the *parameters* (not code) of a new issuance."""

    approve: bool
    blocking_issues: list[str] = []
    notes: str = ""


class CapTableEntry(BaseModel):
    wallet: str
    shares: int = Field(gt=0)
    holder_ref: str = Field(description="internal investor id — never a name")
    _v = field_validator("wallet")(_addr)


class UnsignedTx(BaseModel):
    to: str
    value: str = "0"
    data: str
    description: str


class SafeBatch(BaseModel):
    """Safe{Wallet} Transaction Builder JSON — the issuer imports and signs it in the Safe UI."""

    version: str = "1.0"
    chainId: str
    createdAt: int
    meta: dict
    transactions: list[UnsignedTx]


class DividendPlan(BaseModel):
    record_block: int
    pay_token: str
    total_amount: int
    merkle_root: str
    holders: int
    claims: dict[str, dict]
    remainder_to_issuer: int


# ------------------------------------------------------------------ Studio: site valuation
class CompetitorCandidate(BaseModel):
    name: str
    url: str = ""
    note: str = Field(default="", description="one line: what they do / how they compare")


class CompetitorList(BaseModel):
    competitors: list[CompetitorCandidate] = Field(default_factory=list, description="at most 9 companies")


class FundingClaim(BaseModel):
    name: str = Field(description="competitor name exactly as given")
    amount: float = Field(description="total amount raised, in `currency` units (e.g. 25000000)")
    currency: str = Field(default="USD", description="ISO code: AUD, USD, EUR, GBP, ...")
    source_url: str = Field(description="URL of the evidence page that states the amount")
    quote: str = Field(description="short verbatim excerpt (<= 200 chars) from that page stating the amount")


class FundingClaims(BaseModel):
    items: list[FundingClaim] = Field(default_factory=list)


class RelevanceVerdict(BaseModel):
    name: str
    relevant: bool = Field(description="true only if the page shows a business offering a similar product or "
                                        "service to similar customers")
    reason: str = ""


class RelevanceVerdicts(BaseModel):
    items: list[RelevanceVerdict] = Field(default_factory=list)


class Competitor(BaseModel):
    name: str
    url: str = ""
    raised_aud: float | None = None
    note: str = ""
    sources: int = 0
    basis: str = "search"  # search | model_suggested_verified
