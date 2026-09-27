"""Moat & Competition Analyst (evaluation v5, docs/PLAN-EVALUATION-V5.md §1.2 "Moat": Helmer's 7 Powers + NFX).

One `extract_json` call (MoatClaims): for each power the model may cite evidence (verbatim quote + URL). Code assigns
the level: 1 claimed (company's own page, no number), 2 evidenced (own page stating a number, or an independent
page), 3 registry-verified (the registry number appears on an IP Australia / patents / ABR / ASIC / regulator page);
tools/evaluation caps each power (scale 1, network effects / switching / brand 2) and maps 0/35/70/100 points.
Competitive intensity is computed from the verified competitor list (no model).
"""
from __future__ import annotations

import re

from ..schemas import MoatClaims, MoatPower, VerifiedClaim
from ..tools.evaluation import POWER_LABELS, POWER_WEIGHTS
from .analysts import ask, digest, host, number_in_quote

AGENT = "moat_analyst"
PATTERN = re.compile(r"patent|trade ?mark|licen[cs]e|AFSL|\bACL\b|TGA|integrat|API|network|marketplace|community|"
                     r"exclusive|partner|proprietary|data ?set|award|reviews?|rating|switch|migrat|embedded|workflow|"
                     r"contract|years?|scale|cost|certif|ISO ?27001|SOC ?2", re.IGNORECASE)
REGISTRY_HOSTS = ("ipaustralia.gov.au", "patents.google.com", "wipo.int", "abr.business.gov.au", "asic.gov.au",
                  "tga.gov.au", "search.ipaustralia.gov.au", "uspto.gov", "epo.org")
SYSTEM = """You look for evidence of COMPETITIVE MOAT for the named startup in the numbered evidence, using
Hamilton Helmer's powers:
- network_effects (the product gets better with more users; marketplace liquidity; user-generated content)
- switching_costs (integrations, data migration, embedded workflows, multi-year contracts, API usage)
- ip_data (granted patents, registered trade marks, proprietary datasets)
- scale (unit-cost advantages, owned infrastructure)
- brand (awards, review volume and rating, press recognition)
- counter_positioning (regulatory licences such as AFSL / ACL / TGA, exclusive partnerships, cornered resources)
For each piece of evidence: power, evidence (<= 20 words), number (if the quote states one), registry_id (patent /
trade mark / licence number if stated), source_url copied exactly, quote verbatim (<= 300 chars). Only evidence about
THIS startup. Marketing adjectives without facts are not evidence. An empty list is fine."""


def run(ctx: dict) -> dict:
    deps, profile, v = ctx["deps"], ctx["profile"], ctx["verifier"]
    text = digest(ctx["pool"], PATTERN)
    powers = {k: MoatPower(key=k, label=POWER_LABELS[k], weight=POWER_WEIGHTS[k]) for k in POWER_WEIGHTS}
    if not text:
        return {"claims": [], "dropped": [], "powers": list(powers.values())}
    out = ask(deps, AGENT, SYSTEM, f"Startup: {profile.company_name} — {profile.sector}\n\n<data>\n{text}\n</data>",
              MoatClaims)
    if out is None:
        return {"claims": [], "dropped": [], "powers": list(powers.values()), "error": "extraction failed"}
    dropped: list[str] = []
    claims: list[VerifiedClaim] = []
    for pc in out.powers[:10]:
        label = f"moat: {pc.power}"
        if not v.found(pc.quote, pc.source_url):
            dropped.append(f"{label}: quote not found on the cited page")
            continue
        if not v.names_company(pc.source_url):
            dropped.append(f"{label}: page does not name the company")
            continue
        has_num = pc.number is not None and number_in_quote(pc.number, pc.quote)
        if v.own(pc.source_url):
            level = 2 if has_num else 1
        else:
            level = 2
        rid = (pc.registry_id or "").strip()
        if rid and rid.replace(" ", "") in pc.quote.replace(" ", "") and any(
                host(pc.source_url).endswith(h) for h in REGISTRY_HOSTS):
            level = 3
        vc = VerifiedClaim(metric=f"power:{pc.power}", value=pc.number if has_num else None, unit="",
                           source_url=pc.source_url, quote=pc.quote[:300], subject="company", level=level,
                           analyst="moat")
        claims.append(vc)
        p = powers[pc.power]
        p.evidence.append(vc)
        if level > p.level:
            p.level, p.note = level, (pc.evidence or "")[:160]
    deps.audit.record(AGENT, "claims_verified", kept=len(claims), dropped=len(dropped))
    return {"claims": claims, "dropped": dropped, "powers": list(powers.values())}
