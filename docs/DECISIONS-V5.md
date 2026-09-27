# Owner decisions for evaluation + valuation v5 (27 Sep 2026)

Approved: docs/PLAN-EVALUATION-V5.md and docs/PLAN-VALUATION-V5.md, with these choices.

1. **UX**: more visual; complex content goes into clear step-by-step flows (wizards, tabs, progressive disclosure),
   not long pages. Every number has a visual (bars, football field, gauges, benchmark markers vs stage).
2. **Stage weights**: as in PLAN-EVALUATION-V5 §1.1 (team 0.30 always; traction > market > moat > retention).
3. **Self-reported figures** keep 60% of their effect (verified = 100%).
4. **AU round sizes**: half of US medians until AU data is added (documented, replaceable table).
5. **Share price**: recommended default by stage — A$0.10 idea/pre-seed, A$0.25 seed, A$1.00 later.
   **The founder can adjust the proposed price** (and so the share count) before finalising: within ±20% of the
   recommended value freely (with a note), beyond that it needs a written reason and platform-admin approval. The
   report always shows recommended vs chosen.
6. **Equity risk premium**: 6.0% for Australia (local practice), Damodaran total ERP for Vietnam (8.13%); dated table.
7. **Finalised value** valid 90 days; minimum confidence to finalise = medium (admin can override with reason).
8. **Assumptions**: founders may adjust their own inputs (projections, price) with audit; valuation-method
   assumptions (WACC, multiples, weights) are admin-only with reason + audit.
9. **Search**: production SEARCH_MAX_QUERIES=12 (code cap 16), 3 pages each. Brave paid credit to be attached to the
   API key by the owner (see RUNBOOK-STUDIO.md "Brave").
10. Everything behind `VALUATION_V5` (default off until the backtest passes: live median |error| ≤ 25%, SMEs ≤ 30%,
    100% of new reports recompute; all 14 on-chain reports still verify).
