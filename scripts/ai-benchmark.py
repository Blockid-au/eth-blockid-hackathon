#!/usr/bin/env python3
"""AI gateway model catalogue + golden-set benchmark (docs/PLAN-AI-GATEWAY.md §1, docs/LLM-ROUTING.md).

    cd agents
    set -a; . <(sudo cat /opt/blockid/app.env); set +a      # the worker's keys (root-only file); never printed
    .venv/bin/python ../scripts/ai-benchmark.py --list       # models in SambaNova's and DeepInfra's /models
    .venv/bin/python ../scripts/ai-benchmark.py --run        # golden set on the default candidates
    .venv/bin/python ../scripts/ai-benchmark.py --run --models sambanova:DeepSeek-V3.1,deepinfra:openai/gpt-oss-120b
    .venv/bin/python ../scripts/ai-benchmark.py --record-claude   # (re)record the Claude reference answers (4 calls
                                                                   # on the host bridge's /complete daily cap)

Golden set (stored fixtures, no web access):
* extract_json / valuation: `CompanyFinancials` over the recorded page excerpts of the 8 backtest companies
  (scripts/fixtures/valuation-backtest.json); reference = the verified figures recorded there. Agreement = share of
  the reference fields (revenue within 5 %, revenue type, valuation within 5 %; "no figure" when none) matched.
* extract_json / HR: `PersonAnalysis` for 3 fictional people (scripts/fixtures/hr-extraction.json, with namesake,
  contact-detail and private-information traps); grounded = facts whose quote is verbatim on the cited page;
  recall = Claude's grounded facts also found; trap = facts from the namesake page or private information;
  score MAE = mean |difference| from Claude's 6 person scores.
* reason_score / HR: `TeamAnalysis` over the 3 people's facts; |worked_together - Claude|.

Only model ids present in the providers' /models are run. Spend is estimated from the token usage and the
config price table; the run stops calling paid models once --max-usd (default 0.50) is reached.
Results: printed table + scripts/fixtures/ai-benchmark-results.json.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agents" / "src"))

from blockid_agents.ai_gateway import estimate_cost
from blockid_agents.config import get_settings
from blockid_agents.llm import (
    _CALL,
    CallContext,
    ClaudeBridgeLLM,
    OpenAICompatLLM,
    SambaNovaLLM,
)

FIX_VAL = ROOT / "scripts" / "fixtures" / "valuation-backtest.json"
FIX_HR = ROOT / "scripts" / "fixtures" / "hr-extraction.json"
OUT = ROOT / "scripts" / "fixtures" / "ai-benchmark-results.json"

DEFAULT_MODELS = [
    "sambanova:DeepSeek-V3.1", "sambanova:DeepSeek-V3.2", "sambanova:gpt-oss-120b",
    "sambanova:Meta-Llama-3.3-70B-Instruct", "sambanova:gemma-4-31B-it",
    "deepinfra:deepseek-ai/DeepSeek-V4-Flash", "deepinfra:openai/gpt-oss-120b",
    "deepinfra:Qwen/Qwen3-235B-A22B-Instruct-2507", "deepinfra:deepseek-ai/DeepSeek-V3.2",
    "deepinfra:Qwen/Qwen3-Next-80B-A3B-Instruct", "deepinfra:zai-org/GLM-4.7",
]


# ------------------------------------------------------------------ catalogue
def list_models(s) -> dict[str, dict]:
    import httpx

    out: dict[str, dict] = {}
    for prov, base, key in (("sambanova", s.sambanova_base_url, s.sambanova_api_key),
                            ("deepinfra", s.deepinfra_base_url, s.deepinfra_api_key)):
        if not key:
            print(f"# {prov}: no API key in the environment (see the docstring)", file=sys.stderr)
            continue
        r = httpx.get(base.rstrip("/") + "/models", headers={"Authorization": f"Bearer {key}"}, timeout=30)
        r.raise_for_status()
        for m in r.json().get("data") or []:
            md = m.get("metadata") or {}
            tags = md.get("tags") or ["chat"]
            if "chat" not in tags:
                continue
            pr = m.get("pricing") or md.get("pricing") or {}
            if prov == "sambanova":
                pin, pout = float(pr.get("prompt") or 0) * 1e6, float(pr.get("completion") or 0) * 1e6
            else:
                pin, pout = float(pr.get("input_tokens") or 0), float(pr.get("output_tokens") or 0)
            out[f"{prov}:{m['id']}"] = {"context": m.get("context_length") or md.get("context_length"),
                                        "usd_in_per_mtok": round(pin, 4), "usd_out_per_mtok": round(pout, 4)}
    return out


# ------------------------------------------------------------------ clients
def client_for(mid: str, s):
    prov, _, model = mid.partition(":")
    if prov == "sambanova":
        return SambaNovaLLM(s.sambanova_base_url, s.sambanova_api_key, model, 90, park=False)
    if prov == "deepinfra":
        return OpenAICompatLLM(s.deepinfra_base_url, s.deepinfra_api_key, {"cloud": model}, max_retries=1, timeout=120)
    if mid == "claude-bridge":
        return ClaudeBridgeLLM(s.claude_search_url, s.claude_search_token, 240, park=False)
    raise ValueError(mid)


def call(mid: str, client, system: str, user: str, schema) -> dict:
    ctx = CallContext(10, 240 if mid == "claude-bridge" else 120)
    tok = _CALL.set(ctx)
    t0 = time.monotonic()
    try:
        out = client.complete_json("cloud", system, user, schema)
        err = None
    except Exception as e:  # noqa: BLE001
        out, err = None, f"{type(e).__name__}: {e}"[:300]
    finally:
        _CALL.reset(tok)
    m = ctx.meta
    cost = m.get("cost_usd")
    if cost is None:
        cost = estimate_cost(mid, m.get("tokens_in"), m.get("tokens_out"))
    return {"out": out, "error": err, "latency_s": round(time.monotonic() - t0, 2), "tokens_in": m.get("tokens_in"),
            "tokens_out": m.get("tokens_out"), "cost_usd": cost or 0.0, "headers": m.get("headers")}


# ------------------------------------------------------------------ golden set: valuation extraction
def val_cases():
    from blockid_agents.agents.research import SYSTEM_FINANCIALS, fin_excerpts
    from blockid_agents.deps import UNTRUSTED_NOTE
    from blockid_agents.schemas import CompanyFinancials

    fx = json.loads(FIX_VAL.read_text())
    cases = []
    for name, c in fx["companies"].items():
        titles = {r["url"]: r.get("title") or r["url"] for rs in c["results"].values() for r in rs}
        listing = "\n\n".join(f"[{i}] {titles.get(u, u)}\nURL: {u}\n" + fin_excerpts(t)
                              for i, (u, t) in enumerate(c["pages"].items(), 1))
        p = c["profile"]
        user = (f"Startup: {p['company_name']} — {p.get('sector', '')}; country: {p.get('country', '')}\n\n"
                f"<data>\n{listing}\n</data>")
        cases.append({"id": f"fin:{name}", "system": f"{SYSTEM_FINANCIALS}\n\n{UNTRUSTED_NOTE}", "user": user,
                      "schema": CompanyFinancials, "ref": c["claims"].get("company_financials") or {}})
    return cases


def close(a, b, tol=0.05) -> bool:
    if not a and not b:
        return True
    if not a or not b:
        return False
    return abs(float(a) - float(b)) <= tol * abs(float(b))


def score_fin(out, ref) -> float:
    if out is None:
        return 0.0
    checks = [close(out.revenue_ttm, ref.get("revenue_ttm"))]
    if ref.get("revenue_ttm"):
        checks.append((out.revenue_type or "") == (ref.get("revenue_type") or ""))
    if ref.get("last_valuation"):
        checks.append(close(out.last_valuation, ref.get("last_valuation")))
    return sum(checks) / len(checks)


# ------------------------------------------------------------------ golden set: HR
def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "")).strip().lower()


PRIVATE = re.compile(r"husband|wife|children|heart|lives in|paddington|@|\+61", re.IGNORECASE)


def hr_cases():
    from blockid_agents.agents import people as pa
    from blockid_agents.deps import UNTRUSTED_NOTE
    from blockid_agents.schemas import EvidenceItem

    fx = json.loads(FIX_HR.read_text())
    cases = []
    for p in fx["people"]:
        ev = [(EvidenceItem(url=u, title=u, snippet="", retrieved_at=time.time(), content_sha256="0" * 64,
                            query=p["full_name"], kind="web"), t) for u, t in p["pages"].items()]
        try:
            user = pa._person_prompt(p, fx["target"], ev, [])
        except Exception:  # noqa: BLE001 - People Analyst internals changed: plain listing
            user = (f"PERSON: {p['full_name']} — role: {p['role']}\n<data>\n"
                    + "\n\n".join(f"[{i}] URL: {u}\n{t}" for i, (u, t) in enumerate(p["pages"].items(), 1))
                    + "\n</data>")
        cases.append({"id": f"person:{p['id']}", "system": f"{pa.SYSTEM_PERSON}\n\n{UNTRUSTED_NOTE}", "user": user,
                      "schema": pa.PersonAnalysis, "pages": p["pages"], "name": p["full_name"]})
    return fx, cases


def grounded(facts, pages: dict) -> list:
    return [f for f in facts if f.source_url in pages and _norm(f.quote) and _norm(f.quote) in _norm(pages[f.source_url])]


def score_person(out, case, ref) -> dict:
    if out is None:
        return {"grounded": 0.0, "recall": 0.0, "traps": 0, "mae": None}
    g = grounded(out.facts, case["pages"])
    traps = sum(1 for f in out.facts if "other.example" in f.source_url or PRIVATE.search(f"{f.text} {f.quote}"))
    rq = [_norm(q) for q in (ref or {}).get("quotes", [])]
    mine = [_norm(f.quote) for f in g]
    recall = (sum(1 for q in rq if any(q[:60] in m or m[:60] in q for m in mine)) / len(rq)) if rq else None
    mae = None
    if ref and ref.get("scores"):
        mine_s = {k: getattr(out.scores, k).score for k in ref["scores"]}
        mae = statistics.mean(abs(mine_s[k] - v) for k, v in ref["scores"].items())
    return {"grounded": len(g) / len(out.facts) if out.facts else 0.0, "recall": recall, "traps": traps, "mae": mae}


def team_case(fx, facts_by_person: dict):
    from blockid_agents.agents import people as pa
    from blockid_agents.deps import UNTRUSTED_NOTE

    summary = "\n\n".join(
        f"PERSON {p['full_name']} — {p['role']} ({p['kind']})\n"
        + "\n".join(f"  [p{p['id']}f{i}] {t}" for i, t in enumerate(facts_by_person.get(p["id"], [])[:20], 1))
        for p in fx["people"])
    return {"id": "team", "system": f"{pa.SYSTEM_TEAM}\n\n{UNTRUSTED_NOTE}", "schema": pa.TeamAnalysis,
            "user": f"Business: {fx['team']['name']} ({fx['team']['website']})\n\n<data>\n{summary}\n</data>"}


# ------------------------------------------------------------------ record Claude
def record_claude(s):
    fx, cases = hr_cases()
    cl = client_for("claude-bridge", s)
    ref: dict = {}
    facts_by_person = {}
    for c in cases:
        r = call("claude-bridge", cl, c["system"], c["user"], c["schema"])
        if r["out"] is None:
            sys.exit(f"Claude failed on {c['id']}: {r['error']}")
        g = grounded(r["out"].facts, c["pages"])
        pid = int(c["id"].split(":")[1])
        facts_by_person[pid] = [f.text for f in g]
        ref[c["id"]] = {"quotes": [f.quote for f in g], "facts": [f.text for f in g],
                        "scores": {k: getattr(r["out"].scores, k).score for k in
                                   ("domain_fit", "track_record", "leadership", "functional_depth", "verifiability",
                                    "commitment")}, "latency_s": r["latency_s"]}
        print(f"claude {c['id']}: {len(g)}/{len(r['out'].facts)} grounded facts, {r['latency_s']} s")
    tc = team_case(fx, facts_by_person)
    r = call("claude-bridge", cl, tc["system"], tc["user"], tc["schema"])
    if r["out"] is None:
        sys.exit(f"Claude failed on team: {r['error']}")
    ref["team"] = {"worked_together": r["out"].worked_together.score, "facts_by_person": facts_by_person,
                   "latency_s": r["latency_s"]}
    fx["claude"] = ref
    fx["claude_recorded"] = time.strftime("%Y-%m-%d")
    FIX_HR.write_text(json.dumps(fx, indent=1, ensure_ascii=False) + "\n")
    print(f"recorded Claude reference in {FIX_HR}")


# ------------------------------------------------------------------ run
def run(s, models: list[str], max_usd: float, catalogue: dict):
    fx, hcases = hr_cases()
    ref = fx.get("claude") or {}
    if not ref:
        print("# no Claude reference recorded: HR agreement columns are empty (run --record-claude)", file=sys.stderr)
    vcases = val_cases()
    spent = 0.0
    results = {}
    for mid in models:
        if mid not in catalogue:
            print(f"skip {mid}: not in the provider's /models listing")
            continue
        cl = client_for(mid, s)
        rows = []
        for c in vcases + hcases:
            if spent >= max_usd and mid.startswith("deepinfra:"):
                print(f"spend cap US${max_usd} reached: stopping paid calls")
                break
            r = call(mid, cl, c["system"], c["user"], c["schema"])
            spent += r["cost_usd"]
            row = {"case": c["id"], "valid": r["out"] is not None, "latency_s": r["latency_s"],
                   "cost_usd": r["cost_usd"], "error": r["error"]}
            if c["id"].startswith("fin:"):
                row["agree"] = score_fin(r["out"], c["ref"])
            else:
                row.update(score_person(r["out"], c, ref.get(c["id"])))
            rows.append(row)
            if r["headers"]:
                results.setdefault("_headers", {})[mid] = r["headers"]
        if ref.get("team") and spent < max_usd:
            tc = team_case(fx, {int(k): v for k, v in ref["team"]["facts_by_person"].items()})
            r = call(mid, cl, tc["system"], tc["user"], tc["schema"])
            spent += r["cost_usd"]
            rows.append({"case": "team", "valid": r["out"] is not None, "latency_s": r["latency_s"],
                         "cost_usd": r["cost_usd"], "error": r["error"],
                         "team_diff": abs(r["out"].worked_together.score - ref["team"]["worked_together"])
                         if r["out"] is not None else None})
        results[mid] = summarise(rows)
        results[mid]["rows"] = rows
        sm = results[mid]
        print(f"{mid:48s} valid {sm['valid']:>5} fin {fmt(sm['fin_agree'])} grounded {fmt(sm['hr_grounded'])} "
              f"recall {fmt(sm['hr_recall'])} traps {sm['hr_traps']} mae {fmt(sm['hr_score_mae'], 1)} "
              f"team {fmt(sm['team_diff'], 0)} p50 {fmt(sm['p50_s'], 1)}s p90 {fmt(sm['p90_s'], 1)}s "
              f"${sm['cost_usd']:.4f}")
    results["_spent_usd"] = round(spent, 4)
    results["_date"] = time.strftime("%Y-%m-%d")
    OUT.write_text(json.dumps(results, indent=1, default=str) + "\n")
    print(f"total estimated spend US${spent:.4f}; results in {OUT}")


def fmt(v, d=2):
    return "  -  " if v is None else f"{v:.{d}f}"


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else None


def summarise(rows):
    lat = sorted(r["latency_s"] for r in rows if r["valid"])
    return {
        "valid": f"{sum(r['valid'] for r in rows)}/{len(rows)}",
        "valid_rate": sum(r["valid"] for r in rows) / len(rows) if rows else 0,
        "fin_agree": _mean([r.get("agree") for r in rows if r["case"].startswith("fin:")]),
        "hr_grounded": _mean([r.get("grounded") for r in rows if r["case"].startswith("person:") and r["valid"]]),
        "hr_recall": _mean([r.get("recall") for r in rows if r["case"].startswith("person:") and r["valid"]]),
        "hr_traps": sum(r.get("traps") or 0 for r in rows),
        "hr_score_mae": _mean([r.get("mae") for r in rows if r["case"].startswith("person:")]),
        "team_diff": _mean([r.get("team_diff") for r in rows if r["case"] == "team"]),
        "p50_s": statistics.median(lat) if lat else None,
        "p90_s": lat[min(len(lat) - 1, int(0.9 * len(lat)))] if lat else None,
        "cost_usd": round(sum(r["cost_usd"] for r in rows), 5),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--record-claude", action="store_true")
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--max-usd", type=float, default=0.50)
    a = ap.parse_args()
    s = get_settings()
    if not (s.sambanova_api_key or s.deepinfra_api_key):
        sys.exit("no provider keys in the environment: set -a; . <(sudo cat /opt/blockid/app.env); set +a")
    if a.record_claude:
        record_claude(s)
    catalogue = list_models(s) if (a.list or a.run) else {}
    if a.list:
        for mid, m in sorted(catalogue.items()):
            print(f"{mid:60s} ctx {m['context'] or '?':>8}  ${m['usd_in_per_mtok']:.3f} / "
                  f"${m['usd_out_per_mtok']:.3f} per 1M")
    if a.run:
        if s.claude_search_url and s.claude_search_token:
            catalogue["claude-bridge"] = {"context": 150000}
        run(s, [m.strip() for m in a.models.split(",") if m.strip()], a.max_usd, catalogue)
    _ = os


if __name__ == "__main__":
    main()
