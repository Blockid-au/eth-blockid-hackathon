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
    # Provenance of non-zero metrics, set by code (never by the model): metric field -> "website" (stated on the
    # company's own site) | "self_reported" (founder-typed) | "cited_source" (third-party page found by search).
    metrics_sources: dict[str, str] = Field(default_factory=dict, description="set by code; leave empty")


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


class CompanyFinancials(BaseModel):
    """The startup's OWN reported figures, only when a fetched page or search snippet states them verbatim.
    The model fills the claim fields; code verifies the quote and fills the *_aud / fx fields."""

    revenue_ttm: float | None = Field(default=None, description="latest annual revenue or ARR of THIS company, "
                                      "plain number in `currency` units (e.g. 'US$900 million' -> 900000000)")
    currency: str = Field(default="USD", description="ISO code of the stated figures: USD, AUD, EUR, GBP, SGD, VND")
    revenue_year: int | None = Field(default=None, description="year the revenue figure refers to, if stated")
    revenue_type: Literal["revenue", "ARR", "GMV"] | None = Field(
        default=None, description="'revenue' (annual/TTM revenue), 'ARR' (annualised recurring revenue) or 'GMV' "
        "(transaction/payment volume, gross merchandise value — NOT revenue)")
    funding_raised_total: float | None = Field(default=None, description="total funding raised to date, if stated")
    last_valuation: float | None = Field(default=None, description="latest stated company valuation, if stated")
    source_url: str = Field(default="", description="evidence URL (copied exactly) that states the figures")
    quote: str = Field(default="", description="verbatim excerpt (<= 300 chars) from that page stating the revenue")
    funding_quote: str = Field(default="", description="verbatim excerpt from the same page stating the funding "
                               "total (only if not already in `quote`)")
    valuation_quote: str = Field(default="", description="verbatim excerpt from the same page stating the "
                                 "valuation (only if not already in `quote`)")
    # --- filled by code after verification (the model must leave these null)
    revenue_ttm_aud: float | None = None
    funding_raised_total_aud: float | None = None
    last_valuation_aud: float | None = None
    fx_rate_to_aud: float | None = None
    fx_as_of: str = ""
    usable_for_valuation: bool = False  # verified revenue/ARR (GMV is shown but never used)


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
    company_financials: CompanyFinancials | None = Field(
        default=None, description="leave null: filled by code from a separate, verified extraction step")


# ------------------------------------------------------------------ Valuation (SVI)
Basis = Literal["computed", "ai_suggested", "human", "self_reported", "cited_source", "team_report"]


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
    # v3: the headline valuation_* come from this blend of methods (None on reports valued before v3)
    triangulation: Triangulation | None = None


class Narrative(BaseModel):
    summary: str
    strengths: list[str]
    concerns: list[str]


# ------------------------------------------------------------------ Valuation v3: market evidence + triangulation
AnchorKind = Literal["priced_round", "secondary_sale", "reported_valuation", "investor_mark", "market_cap"]


class AnchorClaim(BaseModel):
    """What the model may claim about THIS company's own market price. Code verifies every field it uses."""

    kind: AnchorKind = Field(description="priced_round (post-money of a funding round), secondary_sale (employee / "
                             "secondary share sale or tender price), reported_valuation (a valuation reported by the "
                             "press without a round), investor_mark (a fund's marked value of its stake), market_cap "
                             "(listed company market capitalisation)")
    amount: float = Field(description="the company valuation / market cap as a plain number in `currency` units "
                          "(e.g. 'US$11 billion' -> 11000000000). NEVER the amount raised in the round.")
    currency: str = Field(default="USD", description="ISO code: USD, AUD, EUR, ... ('A$' -> AUD)")
    date_text: str = Field(default="", description="the date of the valuation exactly as written on the page "
                           "(e.g. 'June 2026', '25 June 2026', '2024'); empty if the page gives none")
    source_url: str = Field(description="evidence URL copied exactly")
    quote: str = Field(description="verbatim excerpt (<= 300 chars) from that page stating the amount")


class CompClaim(BaseModel):
    """A comparable company's revenue multiple stated in the evidence (or its valuation and revenue, both stated)."""

    name: str
    public: bool = Field(default=False, description="true if the comparable is a listed company")
    multiple: float | None = Field(default=None, description="EV/Revenue or valuation/revenue multiple as stated "
                                   "(e.g. '12x revenue' -> 12)")
    valuation: float | None = Field(default=None, description="its valuation / market cap, if stated")
    revenue: float | None = Field(default=None, description="its annual revenue / ARR, if stated")
    currency: str = "USD"
    source_url: str
    quote: str = Field(description="verbatim excerpt stating the multiple (or the valuation)")
    revenue_quote: str = Field(default="", description="verbatim excerpt from the same page stating the revenue, "
                               "when not inside `quote`")


class SectorMultipleClaim(BaseModel):
    multiple: float = Field(description="a sector median / average EV-to-revenue multiple as stated (e.g. 4.6)")
    sector: str = Field(default="", description="what the multiple covers, e.g. 'public SaaS'")
    public: bool = Field(default=True, description="true if it is measured on listed companies")
    source_url: str
    quote: str = Field(description="verbatim excerpt stating the multiple")


class ListingClaim(BaseModel):
    exchange: str = Field(description="ASX, NYSE, NASDAQ, LSE, SGX, HOSE, ...")
    ticker: str
    source_url: str
    quote: str = Field(description="verbatim excerpt showing the listing, e.g. 'Airtasker (ASX: ART)'")


class ValuationEvidence(BaseModel):
    anchors: list[AnchorClaim] = Field(default_factory=list, description="THIS company's own valuations, newest "
                                       "first (at most 5)")
    comps: list[CompClaim] = Field(default_factory=list, description="comparable companies (at most 8)")
    sector_multiples: list[SectorMultipleClaim] = Field(default_factory=list, description="at most 4")
    listing: ListingClaim | None = Field(default=None, description="only if THIS company is listed on an exchange")


class Anchor(BaseModel):
    """A verified market anchor (set by code)."""

    kind: AnchorKind
    amount: float
    currency: str
    amount_aud: float
    fx_rate_to_aud: float
    fx_as_of: str
    as_of: str = ""  # YYYY-MM (or YYYY) parsed from date_text / the page; "" = unknown
    age_months: float | None = None
    date_text: str = ""
    source_url: str
    quote: str


class CompMultiple(BaseModel):
    name: str
    multiple: float
    public: bool = False
    basis: Literal["stated", "valuation/revenue"] = "stated"
    source_url: str
    quote: str


class SectorMultiple(BaseModel):
    multiple: float
    sector: str = ""
    public: bool = True
    source_url: str
    quote: str


class Listing(BaseModel):
    exchange: str
    ticker: str
    source_url: str
    quote: str


class VerifiedValuationEvidence(BaseModel):
    anchors: list[Anchor] = Field(default_factory=list)
    comps: list[CompMultiple] = Field(default_factory=list)
    sector_multiples: list[SectorMultiple] = Field(default_factory=list)
    listing: Listing | None = None
    dropped: list[str] = Field(default_factory=list, description="claims rejected by verification, with the reason")
    as_of: str = ""  # YYYY-MM-DD the evidence was gathered (anchor ages are measured from it)


class ValuationMethod(BaseModel):
    method: Literal["market_anchor", "revenue_multiple", "stage_scorecard"]
    label: str
    value_aud: float
    low_aud: float
    high_aud: float
    raw_weight: float
    weight: float = 0.0  # normalised share of the blend (0..1)
    inputs: dict = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class Triangulation(BaseModel):
    version: str = "v3"
    value_aud: float
    low_aud: float
    high_aud: float
    confidence: Literal["high", "medium", "low"]
    confidence_reasons: list[str] = Field(default_factory=list)
    methods: list[ValuationMethod] = Field(default_factory=list)
    listed: bool = False
    listing: str = ""  # e.g. "ASX: ART" when verified
    as_of: str = ""
    fx_as_of: str = ""




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


SVIResult.model_rebuild()
