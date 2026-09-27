# Agents

BlockID Startup Passport runs its AI agents as LangGraph workflows in `agents/src/blockid_agents/graph.py`. The
**order of steps is code, not a prompt**, and every agent's permissions come from one table in `policy.py`,
enforced in code (`policy.guard()`, called by `deps.ask()` / `deps.tool()`) before every model or tool call.
No agent holds a key: signing exists only in the isolated issuer service, which acts only on admin-approved rows.

There are two graphs:

| Graph | Status | Steps |
|---|---|---|
| **`site_valuation`** | **Live** at https://eth.blockid.au (`/start`, flow steps 1–3) | `read_site → profile → competitors → market → svi → narrative → [gate_valuation]` |
| `onboarding` + `dividend` | Legacy data-room flow (API `/v1/onboarding`, `make demo`) | `intake → research → valuation → [gate] → contract_builder → [gate] → registry`; `plan → [gate] → build_batch` |

## Policy table (`policy.POLICIES`)

| Agent | Model tiers | Tools allowed | Handles PII | Used by |
|---|---|---|---|---|
| **site_intake** | `cloud` | `fetch_url`, `store_profile` | no (public site; emails/phones stripped) | live: `read_site`, `profile` |
| **competitor_discovery** | `local`, `cloud` | `web_search`, `fetch_url`, `store_evidence` | no | live: `competitors` |
| **research** | `local`, `cloud` | `web_search`, `fetch_url`, `store_evidence` | no | live: `market`; legacy: `research` |
| **valuation** | `local`, `cloud` | `svi_score`, `hash_report` | no | live: `svi`, `narrative`; legacy: `valuation` |
| intake | `local` only | `read_dataroom`, `store_profile` | yes | legacy |
| contract_builder | `cloud`, `cloud_max` | `render_params`, `forge_test`, `slither` | no | legacy |
| registry | `local` only | `build_unsigned_tx` | yes | legacy |
| dividend | `local` only | `read_balances`, `build_merkle`, `build_unsigned_tx` | no | legacy |

`FORBIDDEN_TOOLS` for **every** agent: `sign_tx`, `send_tx`, `read_private_key`, `deploy_contract`, `shell`.
An agent marked *handles PII* may only call the `local` tier; any other combination raises `PolicyViolation`, so a
prompt-injected page cannot widen an agent's powers.

In production `SVI_TIER=cloud`: every live valuation step runs on the cloud-tier fallback chain
**SambaNova (free models) → Claude CLI bridge (subscription, `POST /complete`) → DeepInfra (paid)**
(`LLM_PROVIDER_ORDER=sambanova,claude_bridge,deepinfra`). Web search is **Brave → Claude web-search bridge**
(`SEARCH_PROVIDERS=brave,claude`). Models, benchmark and quotas: [LLM-ROUTING.md](LLM-ROUTING.md).

## Live graph: `site_valuation` (website → SVI)

1. **read_site** (`site_intake`): SSRF-safe crawl of the public site (`tools/safefetch.py`): same site, at most
   6 pages (`SITE_MAX_PAGES`), robots.txt, public IPs only, per-hop redirect checks, 2 MB / 20 s per page,
   120 s per crawl; emails and phone numbers stripped before the model sees the text.
2. **profile** (`site_intake`): LLM → `StartupProfile` from facts on the pages only (unknown figures stay 0).
   Founder self-reported figures (optional, from the wizard) override website figures and are labelled
   `self_reported`.
3. **competitors** (`competitor_discovery`): web search 1 of 3 (competitors), fetch the top results, keep only
   names present in fetched text, fetch their homepages; funding is kept only when a fetched source states it.
   If search is unavailable or fewer than 3 competitors are found, the model suggests competitors and each one is
   kept only if its fetched homepage is that brand and on-topic.
4. **market** (`research`): web searches 2 and 3 of 3 (market size/growth, valuation / revenue-multiple
   benchmark) → LLM `MarketAnalysis`; findings citing a URL that was not fetched are dropped. With no search
   results it analyses only the company's and competitors' own sites and shows a warning.
5. **svi** (`valuation`): the LLM suggests the 5 qualitative dimensions (basis `ai_suggested`); code
   (`tools/svi.py`) computes Revenue and Growth, the index, the grade A–E and the valuation range.
6. **narrative** (`valuation`): LLM investor-memo summary.
7. **gate_valuation**: LangGraph `interrupt()`; the run is checkpointed and resumes only when an admin approves
   (optionally overriding scores → basis `human`) or rejects.

Research budget: at most **8 web searches per valuation** (`SEARCH_MAX_QUERIES=8`), each planned by purpose
(competitors, market, company revenue, own valuation/round, market cap if listed, comparable multiples), 3 fetched
pages per search, up to 5 competitor homepages. Valuation v3 triangulates the company's own verified price, revenue ×
cited multiple and the stage benchmark (see [LLM-ROUTING.md](LLM-ROUTING.md), [valuation-reference.md](valuation-reference.md)).

SVI: 7 dimensions with fixed weights — Founder 20%, Product 15%, Market 20%, Revenue 20%, Growth 10%,
Investment Readiness 10%, Trust 5%. The index and grade are the quality indicator; the value is the v3 blend
(own market price, revenue × cited multiple, stage benchmark × SVI factor 0.5 + index/100) with a range and a
confidence level. Shares = approved mid valuation ÷ A$1.00 (default issue
price).

### After the gate (no agents involved)

The founder enters the company (name, 3-letter ticker, shareholders with wallets and %) and submits it. An admin
gives **one issuance approval** (`POST /v1/admin/companies/{id}/approve-issue`); the issuer then creates the
register on BlockID EVM (registry, token, distributor, KYC, issue, `anchorValuation(reportHash)`) and automatically
syncs Ethereum Hoodi and HashKey Chain testnet (paused mirror + `CapTableAnchor` Merkle root).
`approve-anchor` is only a re-sync of a failed or missing chain. The anchored `reportHash` is keccak256 of the
canonical report JSON (`studio/report_hash.py`), which `/verify/:ticker` recomputes in the browser. The agent's
internal `report_sha256` is an audit field and is not the anchored hash.

## Legacy graphs: data-room onboarding and dividends

Kept for the offline demo (`make demo`) and the async API. Gates: valuation sign-off, contract sign-off (hard-
rejects if `forge test`, dry-run deploy or Slither High/Medium fail) plus a human-run deployment, and board
approval of dividend amounts. Outputs are **unsigned** Safe Transaction Builder batches.

- **intake**: reads the data room (OCR'd text) into a `StartupProfile`; missing figures stay 0 and missing
  documents are listed.
- **research / valuation**: as above, but from the data-room profile.
- **contract_builder**: proposes `TokenParams`, runs `forge test` + dry-run + Slither; never writes Solidity or deploys.
- **registry**: turns the approved cap table into an unsigned Safe batch (KYC, issue, anchor).
- **dividend**: pro-rata split at `record_block` (rounded down), OpenZeppelin-compatible Merkle tree,
  `approve` + `createRound` batch; a relayer can pay claim gas.

| Method | Path | Description |
|---|---|---|
| POST | `/v1/onboarding` | `{dataroom:{file:text}, issuance_inputs:{...}}` → `workflow_id` |
| POST | `/v1/dividends` | `{dividend:{record_block, balances, total_amount, pay_token, distributor, board_resolution_id}}` |
| GET | `/v1/workflows/{id}` | status, pending gate, results (the data room is never returned) |
| POST | `/v1/workflows/{id}/decision` | `{decision:{approved, reviewer, ...}}`; valuation gate: `overrides`; contract gate: `deployment`, `cap_table`, `kyc` |
| GET | `/v1/workflows/{id}/safe-batch` | JSON to import into Safe |

Header `X-API-Key`. The live Studio API (`/v1/studio/...`, `/v1/admin/...`) is documented in
[IMPLEMENTATION.md](IMPLEMENTATION.md).

## Adding a new agent

1. Create `agents/src/blockid_agents/agents/<name>.py`.
2. Declare its permissions in `policy.POLICIES`.
3. Add a node and edge to a graph in `graph.py`. If the agent has an on-chain or financial effect, put an
   `interrupt()` gate before it.
4. Write a test with `FakeLLM` (see `tests/test_platform.py`).
