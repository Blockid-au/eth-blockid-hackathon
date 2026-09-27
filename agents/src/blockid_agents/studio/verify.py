"""Public "auditable AI valuation" verifier.

The LLM only suggests scores for the 7 SVI dimensions; a fixed public formula (tools/svi.py) turns them into
the index and the valuation range; keccak256 of the canonical report JSON (studio/report_hash.py) is anchored
on-chain via BlockIDShareToken.anchorValuation -> anyone can recompute and compare with `valuationReportHash()`.

GET  /v1/verify/{ticker}  report + hash + formula + deterministic recompute + on-chain hashes per chain
POST /v1/verify/hash      {report} -> {report_hash}   (paste-your-own JSON)
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..schemas import MarketAnalysis
from ..tools import svi as svi_tools
from .report_hash import canonical_json, canonical_report, report_hash, report_view_from_row

log = logging.getLogger(__name__)

MAX_BODY = 256 * 1024
TOKEN_ABI = [
    {"type": "function", "name": "valuationReportHash", "stateMutability": "view", "inputs": [],
     "outputs": [{"name": "", "type": "bytes32"}]},
]
GRADE_BANDS = [
    {"grade": "A", "min": 80, "label": svi_tools.band(80)},
    {"grade": "B", "min": 65, "label": svi_tools.band(65)},
    {"grade": "C", "min": 50, "label": svi_tools.band(50)},
    {"grade": "D", "min": 35, "label": svi_tools.band(35)},
    {"grade": "E", "min": 0, "label": svi_tools.band(0)},
]
VALUATION_METHOD = (
    "index = round(sum(weight_i x score_i), 2) over the 7 dimensions (weights sum to 1; v4 weights: founder_quality "
    "0.30, product 0.15, market 0.15, revenue 0.15, growth 0.10, readiness 0.10, trust 0.05 - earlier reports use the "
    "v3 set recorded in svi.weights; founder_quality may come from a founding-team report, basis team_report). "
    "factor = 0.5 + index/100 (index 50 -> 1.0x). "
    "If revenue > 0 and a cited median revenue multiple exists: low/mid/high = revenue x (multiple_low | median | "
    "multiple_high) x factor, with multiple_low defaulting to 0.6 x median and multiple_high to 1.5 x median. "
    "Otherwise low/mid/high = stage benchmark range x factor. Values are rounded to the nearest A$1,000. "
    "The LLM only suggests qualitative dimension scores (human-confirmed); revenue_performance and "
    "growth_capability are computed from reported metrics; the index and valuation are plain arithmetic. "
    "v3 reports (svi.triangulation present): low/mid/high = weighted blend of up to three methods, each rebuilt from "
    "its stored inputs - the company's own verified market price (newest anchor; weight = kind x recency), revenue x "
    "cited multiple (x (1 - private-company discount)), and the stage benchmark x factor (weight 0.1 with another "
    "method, 0 when > 5x away) - range widened to at least +/-10/20/35% for high/medium/low confidence."
)
VALUATION_METHOD_V5 = (
    " v5 reports (svi.triangulation.version = 'v5'): the stage (tools/stage) and a valuation class (idea, pre-seed, "
    "seed, Series A, growth, profitable SME, listed) select up to 11 standard methods - own market price, revenue "
    "multiple, EBITDA multiple (listed peers, 25% marketability discount), precedent transactions, discounted cash "
    "flow (CAPM or venture discount rate, Gordon or exit-multiple terminal value, mid-year), First Chicago scenarios, "
    "VC method, Payne scorecard, Berkus, risk factor summation and the stage benchmark. Each method is rebuilt from "
    "the numbers stored in its inputs; its weight = the stage x method matrix x evidence-quality factors "
    "(params_by_version); a method more than 3x from the weighted median of the methods gets weight 0 (a verified own "
    "price at most 24 months old is never excluded); the blend is the weighted mean, widened to at least "
    "+/-10/20/35% by confidence. Values based on management projections are labelled as such."
)


def _params_by_version() -> dict:
    from ..tools.valuation_params import PARAMS, thaw

    return {k: {kk: thaw(vv) for kk, vv in v.items() if kk != "projection"} for k, v in PARAMS.items()}


PUBLIC_RPC = {"hoodi": "https://ethereum-hoodi-rpc.publicnode.com", "hsk": "https://testnet.hsk.xyz"}
EXPLORERS = {
    "blockid": "https://scan.blockid.au/token/{}",
    "hoodi": "https://hoodi.etherscan.io/token/{}",
    "hsk": "https://testnet-explorer.hskchain.net/token/{}",
}


def formula() -> dict:
    return {
        "weights": dict(svi_tools.WEIGHTS),
        "weights_by_version": {k: dict(v) for k, v in svi_tools.WEIGHT_SETS.items()},
        "current_formula": svi_tools.FORMULA_VERSION,
        "grade_bands": GRADE_BANDS,
        "stage_pre_revenue_range_aud": {k: list(v) for k, v in svi_tools.STAGE_PRE_REVENUE_RANGE.items()},
        "valuation_method": VALUATION_METHOD + VALUATION_METHOD_V5,
        "params_by_version": _params_by_version(),
        "hash": "report_hash = keccak256(utf8(canonical_json({url, profile, competitors, market, svi, "
                "self_reported}))) — keys sorted recursively, separators (',', ':'), no ASCII escaping",
    }


def _num(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if v == v and abs(v) != float("inf") else default


def recompute(report: dict) -> dict:
    """Deterministically recompute the SVI index, band and valuation from the report's own inputs
    (dimension scores, profile metrics/stage, cited market multiples) with the public formula."""
    s = (report or {}).get("svi") or {}
    dims = s.get("dimensions") or {}
    wver, weights = weights_for(s)
    contributions = []
    for k, w in weights.items():
        sc = _num((dims.get(k) or {}).get("score"))
        contributions.append({"dimension": k, "score": sc, "weight": w, "contribution": round(w * sc, 4),
                              "basis": (dims.get(k) or {}).get("basis")})
    index = round(sum(weights[c["dimension"]] * c["score"] for c in contributions), 2)
    factor = 0.5 + index / 100
    profile = (report or {}).get("profile") or {}
    rev = _num((profile.get("metrics") or {}).get("revenue_ttm_aud"))
    market = (report or {}).get("market") or {}
    stage = profile.get("stage") if profile.get("stage") in svi_tools.STAGE_PRE_REVENUE_RANGE else "seed"

    # Reports keep the formula version they were valued with; try the current rules first, then the
    # earlier ones, and say which version reproduces the stored numbers.
    tri = s.get("triangulation") if isinstance(s.get("triangulation"), dict) else None
    tri_ver = "v5" if (tri or {}).get("version") == "v5" else "v3"  # v5: tools/valuation_v5.recompute_v5
    candidates = [(tri_ver, _range_v3(tri, s.get("method") or ""))] if tri else []
    candidates += [("v2", _range_v2(rev, factor, market, stage, profile.get("sector") or "")),
                  ("v1b", _range_v1(rev, factor, market, stage, spread=True)),
                  ("v1", _range_v1(rev, factor, market, stage, spread=False))]

    def matches(lmh):
        low, mid, high = (round(x, -3) for x in lmh[:3])
        return {
            "low": s.get("valuation_low_aud") is not None and abs(_num(s.get("valuation_low_aud")) - low) < 0.5,
            "mid": s.get("valuation_mid_aud") is not None and abs(_num(s.get("valuation_mid_aud")) - mid) < 0.5,
            "high": s.get("valuation_high_aud") is not None and abs(_num(s.get("valuation_high_aud")) - high) < 0.5,
        }

    version, (low, mid, high, method) = candidates[0][0], candidates[0][1]
    for v, cand in candidates:
        if all(matches(cand).values()):
            version, (low, mid, high, method) = v, cand
            break
    if version == "v3" and wver == "v4":
        version = "v4"  # v4 = v3 valuation rules + the v4 dimension weights
    out = {"index": index, "band": svi_tools.band(index), "factor": round(factor, 4),
           "low": round(low, -3), "mid": round(mid, -3), "high": round(high, -3),
           "method": method, "formula_version": version, "current_formula": svi_tools.FORMULA_VERSION,
           "weights_version": wver, "weights": dict(weights), "contributions": contributions}
    if version == "v5":  # per-method values rebuilt from the stored inputs (football field on /verify)
        out["methods"] = _methods_v5(tri)
    out["matches_report"] = {
        "index": s.get("index") is not None and abs(_num(s.get("index")) - index) < 0.005,
        "band": s.get("band") == out["band"],
        **matches((low, mid, high)),
    }
    return out


def weights_for(s: dict) -> tuple[str, dict[str, float]]:
    """The dimension-weight set a stored SVI result was computed with: the set equal to its recorded `weights`
    (SVIResult.weights), else the newest set whose weighted sum reproduces its index, else the current set."""
    stored = s.get("weights") if isinstance(s.get("weights"), dict) else None
    if stored:
        for ver, w in svi_tools.WEIGHT_SETS.items():
            if set(stored) == set(w) and all(abs(_num(stored[k]) - w[k]) < 1e-9 for k in w):
                return ver, w
    dims = s.get("dimensions") or {}
    if s.get("index") is not None:
        for ver, w in svi_tools.WEIGHT_SETS.items():
            idx = round(sum(w[k] * _num((dims.get(k) or {}).get("score")) for k in w), 2)
            if abs(idx - _num(s.get("index"))) < 0.005:
                return ver, w
    ver = next(iter(svi_tools.WEIGHT_SETS))
    return ver, svi_tools.WEIGHT_SETS[ver]


def _range_v3(tri: dict, method: str):
    """v3 triangulation: every method rebuilt from its stored inputs, then blended again (tools/triangulate.py)."""
    from ..tools.triangulate import recompute as recompute_blend

    try:
        r = recompute_blend(tri)
    except Exception:  # noqa: BLE001 - malformed stored inputs -> no match
        return 0.0, 0.0, 0.0, method
    return r["low"], r["mid"], r["high"], method


def _methods_v5(tri: dict) -> list[dict]:
    from ..tools.valuation_v5 import recompute_v5

    try:
        return recompute_v5(tri)["methods"]
    except Exception:  # noqa: BLE001 - malformed stored inputs
        return []


def _range_v2(rev, factor, market: dict, stage, sector):
    try:
        m = MarketAnalysis.model_validate(market) if market else None
    except Exception:  # noqa: BLE001 - older reports may not fit the current schema
        m = None
    low, mid, high, method, _ = svi_tools.valuation_range(rev, factor, m, stage, sector)
    return low, mid, high, method


def _range_v1(rev, factor, market: dict, stage, spread: bool):
    """Earlier rules: cited multiple (optionally the 0.7x-1.4x single-multiple spread), else stage range."""
    med = _num(market.get("revenue_multiple_median"))
    if rev > 0 and med:
        lo_m = _num(market.get("revenue_multiple_low")) or med * 0.6
        hi_m = _num(market.get("revenue_multiple_high")) or med * 1.5
        if spread and (lo_m >= med * 0.95 or hi_m <= med * 1.05):
            lo_m, hi_m = min(lo_m, med * 0.7), max(hi_m, med * 1.4)
        return (rev * lo_m * factor, rev * med * factor, rev * hi_m * factor,
                f"revenue multiple ({lo_m:.1f}x / {med:.1f}x / {hi_m:.1f}x) x SVI factor {factor:.2f}")
    b_low, b_mid, b_high = svi_tools.STAGE_PRE_REVENUE_RANGE[stage]
    return b_low * factor, b_mid * factor, b_high * factor, f"stage benchmark range ({stage}) x SVI factor {factor:.2f}"


def _rpc(chain: str, settings) -> str:
    if chain == "blockid":
        return os.environ.get("LOCAL_RPC_URL") or settings.local_rpc_url
    if chain == "hoodi":
        return os.environ.get("HOODI_RPC_URL") or getattr(settings, "hoodi_rpc_url", "") or PUBLIC_RPC["hoodi"]
    return os.environ.get("HSK_RPC_URL") or getattr(settings, "hsk_rpc_url", "") or PUBLIC_RPC["hsk"]


def read_report_hash(rpc: str, token: str) -> str:
    from web3 import Web3

    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 8}))
    c = w3.eth.contract(address=Web3.to_checksum_address(token), abi=TOKEN_ABI)
    return "0x" + bytes(c.functions.valuationReportHash().call()).hex()


def onchain(company: dict, expected: str, settings, reader=read_report_hash) -> list[dict]:
    out = []
    for chain, col in (("blockid", "local_token"), ("hoodi", "hoodi_token"), ("hsk", "hsk_token")):
        token = company.get(col)
        if not token:
            continue
        item: dict[str, Any] = {"chain": chain, "token": token, "valuationReportHash": None, "match": False,
                                "explorer_url": EXPLORERS[chain].format(token), "error": None}
        rpc = _rpc(chain, settings)
        if not rpc:
            item["error"] = "RPC not configured"
        else:
            try:
                h = reader(rpc, token)
                item["valuationReportHash"] = h
                item["match"] = h.lower() == expected.lower()
            except Exception as e:  # noqa: BLE001 — one chain down must not break the page
                log.warning("verify %s %s: %s", chain, token, e)
                item["error"] = "RPC unavailable"
        out.append(item)
    return out


def build_verify_router(ctx) -> APIRouter:
    r = APIRouter()

    @r.get("/v1/verify/{ticker}")
    def verify_ticker(ticker: str):
        from .db import ONCHAIN_STATUSES

        db = ctx.need_db()
        c = db.one("SELECT * FROM studio.companies WHERE ticker=%s", (ticker.upper()[:12],))
        if not c or c.get("status") not in ONCHAIN_STATUSES:
            raise HTTPException(404, "unknown ticker")
        row = db.get_valuation(c["valuation_id"]) if c.get("valuation_id") else None
        if not row:
            raise HTTPException(404, "no valuation report for this company")
        report = canonical_report(report_view_from_row(row))
        # round-trip through canonical JSON so the served object is exactly what was hashed
        report = json.loads(canonical_json(report))
        h = report_hash(report)
        return {
            "ticker": c["ticker"], "name": c["name"], "report": report, "report_hash": h,
            "formula": formula(), "recomputed": recompute(report),
            "onchain": onchain(c, h, ctx.settings),
        }

    @r.post("/v1/verify/hash")
    async def verify_hash(request: Request):
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > MAX_BODY:
            raise HTTPException(413, "report too large (max 256 KB)")
        raw = await request.body()
        if len(raw) > MAX_BODY:
            raise HTTPException(413, "report too large (max 256 KB)")
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise HTTPException(422, "body must be JSON: {\"report\": {...}}") from None
        rep = body.get("report") if isinstance(body, dict) else None
        if not isinstance(rep, dict):
            raise HTTPException(422, "body must be JSON: {\"report\": {...}}")
        try:
            h = report_hash(rep)
        except (ValueError, RecursionError):
            raise HTTPException(422, "report contains non-finite numbers or is nested too deeply") from None
        return {"report_hash": h, "recomputed": recompute(canonical_report(rep))}

    return r
