# Plan v3 — investor-grade messaging, clear flow, market-close valuation (27 Sep 2026)

Owner direction: hero + pitch that attract investors, say "business" (not "private business"); two audiences —
**investors** who want to check a business, and **businesses** that want to list and put their shares on blockchain;
every investor is updated fairly and in sync with the business. Clear flow; CTAs focus on **Evaluate a business** and
**List on blockchain**. Valuation must be computed carefully from what the searches find and land close to the market.
Warnings: compact, not at the top; show status and progress clearly. A wrong website link is caught before anything runs.
Each phase: tests → deploy live → commit + push.

## Phase 1 — messaging, flow, status (agent A)
1. Hero/pitch rewrite (EN+VI), two audience paths, CTAs "Evaluate a business" (→ /start) and "List on blockchain"
   (→ /start?goal=list, same flow, copy tuned to issuing shares). Update FACTS.md + README top.
2. /start and the 8-step rail in plain words (no SVI / Hoodi / HashKey / "gold steps" on the founder path; keep the
   technical names only on /verify, /hsk and admin).
3. Status instead of warnings: one compact `StatusBar` component (status pill + step progress + elapsed/next) at the
   top of valuation, company and portfolio screens; warnings/notes move to a collapsed "Notes (n)" at the end of the
   report; "Next step" becomes a slim bar; demo notices become a small chip. No amber full-width boxes at the top.
4. Website link check: client-side validation (scheme, host, TLD, punycode/typo like `xn--`), plus
   `POST /v1/studio/check-url` (normalise, DNS resolve, fetch homepage with SSRF-safe fetch, return title) before a
   valuation starts; errors show inline and keep the user on the input. If intake still fails, the valuation page
   sends the user back to /start with the link prefilled and the reason.
5. Valuation reports readable by any signed-in viewer once linked to a listed business (demo account can open them);
   drafts stay with the requester/admin.

## Phase 2 — valuation engine v2 (agent B)
Triangulate instead of one rule: (a) the company's own latest priced round / reported valuation / listed market cap
(verbatim-cited), (b) revenue × multiple from cited comparable companies and sector data, (c) stage/scorecard for
pre-revenue; weight by evidence quality, show each method, the blended value, the range and a confidence level.
Bigger but bounded search budget (Claude bridge search first, Brave fallback), market cap lookup for listed companies,
FX dated. Backtest set: Canva, Airwallex, SafetyCulture, Go1, Airtasker (ASX), Employment Hero, Culture Amp —
report error vs latest public figure; target median |error| ≤ 30%.

## Phase 3 — share offering (agent C, after phase 1)
Simulated primary offering (see UPGRADE-INVESTOR-PLAN §3f), demoable by the demo account without a signature.

## Phase 4 — docs, deck, screenshots refresh
