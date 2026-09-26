# Agents

| # | Agent | Model | Tools allowed | Contains PII | Never allowed to |
|---|---|---|---|---|---|
| 1 | **intake** | local | `read_dataroom`, `store_profile` | yes | call cloud models, access the network |
| 2 | **research** | local | `brave_search`, `fetch_url`, `store_evidence` | no (query is filtered) | touch the chain |
| 3 | **valuation** | local (cloud if needed; input name-anonymized) | `svi_score`, `hash_report` | no | compute metrics/valuation itself (code computes it) |
| 4 | **contract_builder** | cloud / cloud_max | `render_params`, `forge_test`, `slither` | no | write Solidity, deploy |
| 5 | **registry** | (no LLM) | `build_unsigned_tx` | yes | sign/send transactions |
| 6 | **dividend** | (no LLM) | `read_balances`, `build_merkle`, `build_unsigned_tx` | no | sign/send transactions |
| – | **supervisor** | – | LangGraph: step ordering + 3 approval gates | – | be altered by a prompt |

Tools forbidden to every agent: `sign_tx`, `send_tx`, `read_private_key`, `deploy_contract`, `shell`. The permission table lives in `policy.py` and is enforced **in code** before every model or tool call, so a document containing a prompt injection still cannot expand an agent's permissions.

## Details

**1. Intake**: reads the data room (OCR'd text) and extracts a `StartupProfile` according to the schema. Any figure missing from the documents is set to 0, and missing documents are listed (audited financial statements, constitution, IP assignment, etc.).

**2. Research (Brave)**: see ARCHITECTURE §3. The result is a `MarketAnalysis` containing market growth, revenue multiples (low/median/high), and claims with source URLs.

**3. Valuation (SVI)**: 7 pillars weighted as Founder 20%, Product 15%, Market 20%, Revenue 20%, Growth 10%, Investment Readiness 10%, Trust 5%.
- Revenue and Growth: **computed by code** from the figures.
- The 5 qualitative pillars: the LLM **proposes** a score (labeled `ai_suggested`), and the approver confirms or edits it at Gate 1 (changing it to `human`).
- Valuation = revenue × multiple (sourced) × SVI factor (0.5 + index/100). If revenue or a multiple is not yet available, a stage-based range is used (**a placeholder that needs to be calibrated with SVI research data**).
- The report is hashed with SHA-256, and this hash is anchored to the token via `anchorValuation`.

**4. Contract Builder**: proposes `TokenParams` (JSON), runs `forge test` + a dry-run deploy + Slither, then has Sonnet 5 review the parameters. The agent does not write Solidity and does not deploy.

**5. Registry**: from the board-approved cap table, builds a **Safe Transaction Builder batch** containing KYC registration, issuance, and valuation anchoring. Signers import the batch into Safe{Wallet} to review and sign.

**6. Dividend**: from balances at `record_block`, splits pro-rata rounded down (the remainder is kept for the issuer), builds an OpenZeppelin-compatible Merkle tree, then creates an `approve` + `createRound` batch. Shareholders claim themselves; a relayer can pay the gas on their behalf.

## API (async)

| Method | Path | Description |
|---|---|---|
| POST | `/v1/onboarding` | `{dataroom:{file:text}, issuance_inputs:{issuer_safe, transfer_agent, kyc_agent, legal_doc_hash, board_resolution_id, share_class}}` → `workflow_id` |
| POST | `/v1/dividends` | `{dividend:{record_block, balances, total_amount, pay_token, distributor, board_resolution_id}}` |
| GET | `/v1/workflows/{id}` | status, the pending gate (`gate`), results (the data room is never returned) |
| POST | `/v1/workflows/{id}/decision` | `{decision:{approved, reviewer, ...}}`. Gate 1: `overrides`. Gate 2: `deployment`, `cap_table`, `kyc` |
| GET | `/v1/workflows/{id}/safe-batch` | JSON to import into Safe |

Header `X-API-Key`. For the staff-facing interface, Google IAP or Cloudflare Access should be placed in front of it.

## Adding a new agent

1. Create `agents/src/blockid_agents/agents/<name>.py` with a `run(state, deps) -> dict` function.
2. Declare its permissions in `policy.POLICIES`.
3. Add a node and edge to `graph.py`. If the agent has an on-chain or financial impact, place an `interrupt()` gate before it.
4. Write a test with `FakeLLM` (see `tests/test_platform.py`).
