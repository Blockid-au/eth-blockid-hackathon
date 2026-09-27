"""Typed contracts between agents. Every hand-off in the graph is one of these models."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer

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
    # v5 (VALUATION_V5, docs/EVALUATION-V5-API.md): per-dimension detail, stage, evidence. Both fields are left out of
    # the serialised result when None, so v1-v4 results (and flag-off reports) keep their exact JSON and hashes.
    analysis: Analysis | None = None
    weights_profile: str | None = None  # "v5:<stage>"

    @model_serializer(mode="wrap")
    def _omit_absent_v5(self, handler):
        d = handler(self)
        if isinstance(d, dict):
            for k in ("analysis", "weights_profile"):
                if k in d and d[k] is None:
                    d.pop(k)
        return d


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


# v3 methods + valuation v5 methods (tools/valuation_methods.py, docs/PLAN-VALUATION-V5.md §4.4)
MethodName = Literal["market_anchor", "revenue_multiple", "stage_scorecard",
                     "ebitda_multiple", "precedents", "dcf", "vc_method", "scorecard", "berkus", "rfs", "first_chicago"]


class Check(BaseModel):
    """A deterministic check on a method or on uploaded projections (plain-words message)."""

    code: str
    severity: Literal["error", "warning", "info"]
    message: str
    year: int | None = None
    row: str | None = None
    used_value: float | None = None


class ValuationMethod(BaseModel):
    method: MethodName
    label: str
    value_aud: float
    low_aud: float
    high_aud: float
    raw_weight: float
    weight: float = 0.0  # normalised share of the blend (0..1)
    inputs: dict = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    checks: list[Check] = Field(default_factory=list)  # v5 only (omitted from dumps when empty: v3 JSON unchanged)

    @model_serializer(mode="wrap")
    def _omit_empty_v5(self, handler):
        d = handler(self)
        if isinstance(d, dict) and not d.get("checks"):
            d.pop("checks", None)
        return d


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
    # ---- valuation v5 (tools/valuation_v5.py); every field is omitted from dumps when unset, so v3 JSON is unchanged
    params_version: str = ""
    market_dataset: str = ""
    valuation_class: str = ""  # idea|pre_seed|seed|series_a|growth|profitable_sme|listed
    stage: dict | None = None  # tools/stage StageDecision (+ class reasons)
    football_field: list[dict] = Field(default_factory=list)
    without_projections: dict | None = None
    projections: dict | None = None  # {sha256, attested_by, attested_at, label}
    tokenisation: dict | None = None  # TokenisationProposal (docs/VALUATION-V5-API.md)

    @model_serializer(mode="wrap")
    def _omit_absent_v5(self, handler):
        d = handler(self)
        if isinstance(d, dict):
            for k in ("params_version", "market_dataset", "valuation_class", "stage", "football_field",
                      "without_projections", "projections", "tokenisation"):
                if k in d and d[k] in (None, "", []):
                    d.pop(k)
        return d


# ------------------------------------------------------------------ valuation v5: projections + agent outputs
class ProjectionYear(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    year: int = Field(ge=1990, le=2100)
    actual: bool
    revenue: float = Field(ge=0, le=1e13)
    cogs: float = Field(ge=0, le=1e13)
    opex: float = Field(ge=0, le=1e13)
    ebitda: float | None = Field(default=None, ge=-1e13, le=1e13)
    d_and_a: float = Field(ge=0, le=1e13)
    tax: float | None = Field(default=None, ge=0, le=1e13)
    capex: float = Field(ge=0, le=1e13)
    nwc: float | None = Field(default=None, ge=-1e13, le=1e13)
    change_nwc: float | None = Field(default=None, ge=-1e13, le=1e13)
    headcount: float | None = Field(default=None, ge=0, le=1e7)
    customers: float | None = Field(default=None, ge=0, le=1e10)


class ProjectionInput(BaseModel):
    """What a business uploads (XLSX / CSV template or the in-page grid). Never read by a model."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    currency: str = Field(default="AUD", max_length=8)
    fiscal_year_end: str = Field(default="06-30", max_length=10)
    audited: bool = False
    prepared_by: str = Field(default="", max_length=200)
    basis_notes: str = Field(default="", max_length=500)
    cash: float = Field(default=0, ge=0, le=1e13)
    debt: float = Field(default=0, ge=0, le=1e13)
    shares_fd: int | None = Field(default=None, ge=1, le=10**15)
    planned_raise: float = Field(default=0, ge=0, le=1e13)
    years: list[ProjectionYear] = Field(min_length=1, max_length=8)


BerkusKey = Literal["sound_idea", "prototype", "quality_team", "strategic_relationships", "product_rollout"]
RfsKey = Literal["management", "stage", "legislation", "manufacturing", "sales_marketing", "funding", "competition",
                 "technology", "litigation", "international", "reputation", "exit"]


class FactorScore(BaseModel):
    score: float = Field(ge=0, le=100, description="0-100: how far this risk reducer is achieved")
    rationale: str = Field(default="", max_length=400)
    sources: list[str] = Field(default_factory=list, description="evidence URLs copied exactly")


class RfsRating(BaseModel):
    rating: int = Field(ge=-2, le=2, description="-2 very high risk, -1 high, 0 neutral, +1 low, +2 very low risk")
    rationale: str = Field(default="", max_length=400)
    sources: list[str] = Field(default_factory=list, description="evidence URLs copied exactly")


class StartupFactors(BaseModel):
    """LLM suggestion (basis ai_suggested until an admin confirms). Never a value, only ratings with evidence."""

    berkus: dict[BerkusKey, FactorScore] = Field(default_factory=dict)
    rfs: dict[RfsKey, RfsRating] = Field(default_factory=dict)


class IndustryPick(BaseModel):
    industry: str = Field(description="one key from the given industry list, copied exactly")
    rationale: str = Field(default="", max_length=300)


class DealClaim(BaseModel):
    target: str
    acquirer: str = ""
    ev: float | None = Field(default=None, description="deal value / enterprise value paid, plain number")
    revenue: float | None = Field(default=None, description="target's annual revenue, if stated")
    ebitda: float | None = Field(default=None, description="target's EBITDA, if stated")
    multiple: float | None = Field(default=None, description="stated multiple, e.g. '6.5x EBITDA' -> 6.5")
    basis: Literal["revenue", "ebitda"] = "ebitda"
    currency: str = "AUD"
    date_text: str = Field(default="", description="deal date exactly as written on the page")
    source_url: str
    quote: str = Field(description="verbatim excerpt (<= 300 chars) stating the multiple (or the price)")


class DealClaims(BaseModel):
    deals: list[DealClaim] = Field(default_factory=list, description="at most 6 acquisitions of comparable businesses")




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


# ------------------------------------------------------------------ Evaluation v5: stage (tools/stage.py)
StageKey = Literal["idea", "pre-seed", "seed", "series-a", "growth"]
StageBasis = Literal["listing", "round", "revenue", "raised", "hint", "human", "default"]


class StageDecision(BaseModel):
    """Evidence-based stage (docs/PLAN-EVALUATION-V5.md §6.1), decided by code in tools/stage.classify_stage."""

    stage: StageKey
    basis: StageBasis
    reasons: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    # every signal that was available, e.g. {"round": "seed", "revenue": "series-a", "raised": "seed", "hint": "seed"}
    signals: dict[str, str] = Field(default_factory=dict)
    conflict: bool = False
    table_version: str = ""


# ------------------------------------------------------------------ Evaluation v5: evidence, metrics, dimensions
# Verification levels (§4.2): 0 missing, 1 self-reported / founder deck / own-site marketing claim, 2 document-backed
# (typed value matches an upload, or computed from an uploaded CSV that passed the checks), 3 publicly corroborated /
# approved on-chain KPI update / registry, 4 connected system. Scores shrink toward 50 by level (tools/stage.shrink).
MetricSource = Literal["self_reported", "csv", "deck", "site", "cited", "kpi", "registry", "lookup", "computed",
                       "connector", "competitors", ""]


class MetricValue(BaseModel):
    value: float | None = None
    unit: str = ""  # AUD | % | count | months | x | rating | rank
    as_of: str = ""  # YYYY-MM when known
    level: int = Field(default=0, ge=0, le=4)
    source: MetricSource = ""
    source_url: str = ""
    quote: str = ""
    note: str = ""


class SubMetric(BaseModel):
    key: str  # "T1".."T4", "M1".."M5", "R1".."R5", "E1".., "Mo:network_effects", ...
    metric: str  # metric key, e.g. "arr_aud", "yoy_growth_pct"
    label: str
    weight: float
    value: MetricValue | None = None
    benchmark: list[float] | None = None  # [P25, P50, P75, P90] for this stage / sector (lower-is-better: worst->best)
    lower_is_better: bool = False
    score_raw: float | None = None  # 0-100 vs the benchmark
    score: float | None = None  # after the evidence-level shrink (and any cap)
    status: Literal["scored", "missing", "not_benchmarked", "not_applicable", "capped"] = "missing"
    note: str = ""


class VerifiedClaim(BaseModel):
    """A claim the LLM extracted that code verified (quote found verbatim in stored text, number stated)."""

    metric: str
    value: float | None = None
    unit: str = ""
    period: str = ""
    as_of: str = ""
    value_aud: float | None = None
    source_url: str = ""
    quote: str = ""
    subject: Literal["company", "market", "competitor"] = "company"
    level: int = Field(default=1, ge=0, le=4)
    analyst: str = ""  # traction | market_size | moat | retention | deck


class ConsistencyFlag(BaseModel):
    code: str  # cross_source_gap | arr_vs_mrr | nrr_below_grr | grr_over_100 | implausible | csv_duplicate_rows | ...
    severity: Literal["info", "warning", "high"] = "warning"
    message: str
    metrics: list[str] = Field(default_factory=list)
    action: str = ""  # "lower_used" | "capped" | "review" | ""


class MoatPower(BaseModel):
    key: str  # network_effects | switching_costs | ip_data | scale | brand | counter_positioning | competition
    label: str
    weight: float
    level: int = Field(default=0, ge=0, le=3)  # 0 none, 1 claimed, 2 evidenced on public pages, 3 registry / document
    level_cap: int = 3
    points: float = 0.0  # 0 / 35 / 70 / 100 by level (competition: computed 0-100)
    evidence: list[VerifiedClaim] = Field(default_factory=list)
    note: str = ""


class MarketSizing(BaseModel):
    sam_aud: float | None = None  # bottom-up: target customers x annual price
    target_customer: str = ""
    target_customers: float | None = None
    target_customers_source: str = ""  # "abs:<division>:<band>" | URL | "self_reported"
    annual_price_aud: float | None = None
    annual_price_source: str = ""
    tam_aud: float | None = None  # top-down cited figure (cross-check)
    tam_source_url: str = ""
    tam_quote: str = ""
    cagr_pct: float | None = None
    cagr_source_url: str = ""
    som_share: list[float] = Field(default_factory=list)  # [low, high] achievable share in 5 years (stage table)
    som_aud_5y: list[float] = Field(default_factory=list)  # [low, high]
    source_tier: int = 0  # 1 gov/statutory .. 4 blog/vendor, 0 unknown
    warnings: list[str] = Field(default_factory=list)


class DimensionDetail(BaseModel):
    key: str
    label: str
    weight: float
    score: float  # the score used in the index (0-100)
    score_raw: float | None = None  # weighted mean of scored sub-metrics before the coverage cap
    coverage: float = 0.0  # share of sub-metric weight with data (0-1)
    cap: float = 100.0  # 40 + 60 x coverage for code-computed dimensions
    level: float = 0.0  # weight-weighted mean verification level of the scored sub-metrics (0-4)
    confidence: Literal["high", "medium", "low"] = "low"
    status: Literal["scored", "not_enough_data", "not_applicable", "ai_suggested", "team_report", "human"] = "scored"
    basis: Basis = "computed"
    sub_metrics: list[SubMetric] = Field(default_factory=list)
    evidence: list[VerifiedClaim] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    improve: list[str] = Field(default_factory=list)  # "what would raise this score"
    rationale: str = ""


class Analysis(BaseModel):
    """svi.analysis (v5 only). Everything a v5 report needs to render and to recompute."""

    version: str = "v5"
    stage: StageDecision
    stage_profile: dict = Field(default_factory=dict)  # tools/stage.profile_snapshot() — the values actually used
    sector_key: str = "saas"
    revenue_model: str = ""
    dimensions: dict[str, DimensionDetail] = Field(default_factory=dict)
    metrics: dict[str, MetricValue] = Field(default_factory=dict)  # resolved inputs after consistency checks
    claims: list[VerifiedClaim] = Field(default_factory=list)
    dropped: list[str] = Field(default_factory=list)
    flags: list[ConsistencyFlag] = Field(default_factory=list)
    powers: list[MoatPower] = Field(default_factory=list)
    market_sizing: MarketSizing | None = None
    lookups: dict = Field(default_factory=dict)  # tranco / wayback / app_store / abn results (cached)
    trust_share: float = 0.0  # share of scored weight at level >= 2 (0-1)
    confidence: Literal["high", "medium", "low"] = "low"
    top_improvements: list[str] = Field(default_factory=list)
    documents: list[dict] = Field(default_factory=list)  # [{doc_id, kind, filename, sha256}]
    analysts: dict = Field(default_factory=dict)  # {name: {model, claims, dropped, searches, error}}


# ------------------------------------------------------------------ Evaluation v5: LLM extraction schemas (extract_json)
class MetricClaim(BaseModel):
    """What an analyst model may claim. Code verifies the quote and converts the number; the model never scores."""

    metric: str = Field(description="one of the metric keys listed in the instructions")
    value: float | None = Field(default=None, description="the number as stated, in `unit` (e.g. 'A$2.4m' -> 2400000)")
    unit: str = Field(default="", description="AUD | USD | EUR | GBP | ... | % | count | months | rating")
    period: str = Field(default="", description="the period as written ('FY24', 'June 2026', 'last 12 months')")
    source_url: str = Field(default="", description="evidence URL copied exactly from the list, or 'doc:<id>'")
    quote: str = Field(default="", description="verbatim excerpt (<= 300 chars) from that source containing the number")
    subject: Literal["company", "market", "competitor"] = "company"


class LogoClaim(BaseModel):
    name: str = Field(description="a named customer / partner organisation of THIS company")
    source_url: str = ""
    quote: str = Field(default="", description="verbatim excerpt naming the customer")


class TractionClaims(BaseModel):
    claims: list[MetricClaim] = Field(default_factory=list, description="at most 12")
    logos: list[LogoClaim] = Field(default_factory=list, description="at most 12 named customers")
    revenue_model: Literal["subscription", "transactional", "marketplace", "services", "hardware", "other", ""] = ""
    revenue_model_quote: str = ""


class MarketSizeClaims(BaseModel):
    claims: list[MetricClaim] = Field(default_factory=list, description="tam / sam / cagr / target_customer_count / "
                                      "annual_price claims, at most 8")
    target_customer: str = Field(default="", description="who pays, in <= 12 words (e.g. 'Australian dental clinics')")
    anzsic_division: str = Field(default="", description="ANZSIC division letter A-S of the TARGET CUSTOMERS if they "
                                 "are Australian businesses, else ''")
    size_band: Literal["all", "employing", "non_employing", "1-19", "20-199", "200+", ""] = ""
    customer_quote: str = Field(default="", description="verbatim excerpt describing who the customers are")
    customer_source_url: str = ""


MoatPowerKey = Literal["network_effects", "switching_costs", "ip_data", "scale", "brand", "counter_positioning"]


class PowerClaim(BaseModel):
    power: MoatPowerKey
    evidence: str = Field(default="", description="what the evidence shows, <= 20 words")
    number: float | None = Field(default=None, description="a number stated in the quote if any (integrations, "
                                 "patents, reviews, users)")
    registry_id: str = Field(default="", description="patent / trade mark / licence number if stated")
    source_url: str = ""
    quote: str = ""


class MoatClaims(BaseModel):
    powers: list[PowerClaim] = Field(default_factory=list, description="at most 10")


class RetentionClaims(BaseModel):
    claims: list[MetricClaim] = Field(default_factory=list, description="nrr / grr / logo_churn_monthly / "
                                      "review_rating / review_count / nps / customer_since claims, at most 10")


class DeckFacts(BaseModel):
    claims: list[MetricClaim] = Field(default_factory=list, description="figures the deck states, at most 20")
    round_type: str = Field(default="", description="the round being raised or last raised, as written")
    round_quote: str = ""


# ------------------------------------------------------------------ Evaluation v5: founder inputs (v2)
RevenueModel = Literal["subscription", "transactional", "marketplace", "services", "hardware", "other"]


class SelfReportedMetricsV2(SelfReportedMetrics):
    """Founder figures v2 (§3.1): the v1 keys stay valid; everything optional; every use is self-reported (L1) unless
    an uploaded document / CSV backs it (L2). Derived values (growth, CMGR, runway, burn multiple) are computed."""

    revenue_prev_ttm_aud: float | None = Field(default=None, ge=0, le=1e12)
    arr_aud: float | None = Field(default=None, ge=0, le=1e12)
    mrr_aud: float | None = Field(default=None, ge=0, le=1e11)
    mrr_6m_ago_aud: float | None = Field(default=None, ge=0, le=1e11)
    mrr_12m_ago_aud: float | None = Field(default=None, ge=0, le=1e11)
    revenue_model: RevenueModel | None = None
    gmv_ttm_aud: float | None = Field(default=None, ge=0, le=1e13)
    take_rate_pct: float | None = Field(default=None, ge=0, le=100)
    paying_customers_12m_ago: int | None = Field(default=None, ge=0, le=1_000_000_000)
    active_users_monthly: int | None = Field(default=None, ge=0, le=10_000_000_000)
    active_users_daily: int | None = Field(default=None, ge=0, le=10_000_000_000)
    waitlist: int | None = Field(default=None, ge=0, le=1_000_000_000)
    pilots_paid: int | None = Field(default=None, ge=0, le=100_000)
    lois: int | None = Field(default=None, ge=0, le=100_000)
    contracted_backlog_aud: float | None = Field(default=None, ge=0, le=1e12)
    qualified_pipeline_aud: float | None = Field(default=None, ge=0, le=1e12)
    top_customer_share_pct: float | None = Field(default=None, ge=0, le=100)
    public_logos: list[str] | None = Field(default=None, max_length=30)
    logo_churn_monthly_pct: float | None = Field(default=None, ge=0, le=100)
    grr_pct: float | None = Field(default=None, ge=0, le=100)
    nrr_pct: float | None = Field(default=None, ge=0, le=500)
    m3_retention_pct: float | None = Field(default=None, ge=0, le=100)
    m12_retention_pct: float | None = Field(default=None, ge=0, le=100)
    nps: float | None = Field(default=None, ge=-100, le=100)
    cash_aud: float | None = Field(default=None, ge=0, le=1e12)
    burn_monthly_aud: float | None = Field(default=None, ge=0, le=1e11)
    net_new_arr_12m_aud: float | None = Field(default=None, ge=-1e12, le=1e12)
    cac_aud: float | None = Field(default=None, ge=0, le=1e9)
    arpa_monthly_aud: float | None = Field(default=None, ge=0, le=1e9)
    target_customer: str | None = Field(default=None, max_length=120)
    target_customer_count: float | None = Field(default=None, ge=0, le=1e10)
    target_count_source_url: str | None = Field(default=None, max_length=500)
    annual_price_aud: float | None = Field(default=None, ge=0, le=1e9)
    geographies: list[str] | None = Field(default=None, max_length=20)
    patents: list[str] | None = Field(default=None, max_length=20)
    trademarks: list[str] | None = Field(default=None, max_length=20)
    licences: list[str] | None = Field(default=None, max_length=20)
    integrations_count: int | None = Field(default=None, ge=0, le=100_000)
    exclusive_contracts: int | None = Field(default=None, ge=0, le=10_000)
    moat_note: str | None = Field(default=None, max_length=500)
    last_round_type: str | None = Field(default=None, max_length=40)
    last_round_date: str | None = Field(default=None, pattern=r"^\d{4}(-\d{2})?$")
    last_round_post_money_aud: float | None = Field(default=None, ge=0, le=1e13)
    lead_investor: str | None = Field(default=None, max_length=120)
    as_of: dict[str, str] | None = Field(default=None, description="field -> YYYY-MM")
    doc_ref: dict[str, str] | None = Field(default=None, description="field -> uploaded document id")

    @field_validator("public_logos", "geographies", "patents", "trademarks", "licences")
    @classmethod
    def _short_items(cls, v):
        if v is not None and any(len(str(x)) > 120 for x in v):
            raise ValueError("each item must be <= 120 characters")
        return v


SVIResult.model_rebuild()
