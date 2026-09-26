# BlockID Startup Passport: architecture diagrams

> **Testnet demo. Not an offer of securities.**

These diagrams describe the system **as deployed** on eth.blockid.au (single VM) and as implemented in this repo.
They were checked against the code (`agents/src/blockid_agents/**`, `contracts/src/*.sol`, `web/app/src/**`),
the compose files in `deploy/`, and the host nginx config. GitHub renders the ```` ```mermaid ```` blocks inline.
Pre-rendered SVG/PNG copies and the `.mmd` sources are in [`docs/diagrams/`](diagrams/).

| # | Diagram | Type |
|---|---|---|
| 1 | [System context](#1-system-context) | flowchart |
| 2 | [Deployment / runtime topology](#2-deployment--runtime-topology) | flowchart |
| 3 | [Valuation pipeline](#3-valuation-pipeline-site_valuation-graph) (+ [SVI scoring](#3b-svi-scoring-and-valuation-formula), [LLM and search routing](#3c-llm-and-web-search-routing)) | flowchart |
| 4 | [Issuance: one approval, three chains](#4-issuance-one-approval-three-chains) | sequence |
| 5 | [Public `/verify` flow](#5-public-verify-flow) | sequence |
| 6 | [Security trust boundaries](#6-security-trust-boundaries) | flowchart |
| 7 | [Smart contracts](#7-smart-contracts) | class |
| 8 | [Data model (`studio.*`)](#8-data-model-studio-schema) | ER |
| 9 | [Company status and per-chain sync states](#9-company-status-state-machine) | state |

---

## 1. System context

Four kinds of people use the system. Founders submit a website and a cap table. Investors and shareholders hold
the tokens. An admin approves every valuation, issuance, mint and dividend. Judges and other public verifiers
recompute report hashes without logging in. Everything is behind Cloudflare. The platform runs its own zero-gas
BlockID EVM chain (262626) as the register of record and mirrors and anchors each cap table on Ethereum Hoodi
(560048) and HashKey Chain testnet (133). The AI side uses SambaNova (free models, tried first) and DeepInfra
(paid, tried last) for LLM calls. Web search goes to Brave first, then to Claude web search through a host bridge.

```mermaid
flowchart LR
  founder["Founder / SME owner<br/>MetaMask + SIWE"]
  investor["Investor / shareholder<br/>MetaMask wallet"]
  admin["Admin / approver<br/>SIWE admin wallet or<br/>username + password"]
  judge["Judge / public verifier<br/>no login"]

  cf["Cloudflare<br/>DNS, TLS edge, proxy<br/>CF-Connecting-IP"]

  subgraph sys["BlockID Startup Passport (single GCP VM)"]
    app["eth.blockid.au<br/>SPA + agents API + worker<br/>+ isolated issuer"]
    scan["scan.blockid.au<br/>Blockscout explorer"]
    chain[("BlockID EVM<br/>chain 262626, gas 0<br/>register of record")]
  end

  sites["Startup + competitor<br/>public websites"]
  samba["SambaNova Cloud<br/>free LLMs (primary)"]
  deepinfra["DeepInfra<br/>paid LLMs (last resort)"]
  brave["Brave Search API"]
  claude["Claude CLI on host<br/>(Anthropic subscription)<br/>web search + completion"]
  hoodi[("Ethereum Hoodi<br/>chain 560048")]
  hsk[("HashKey Chain testnet<br/>chain 133")]

  founder -->|submit website, cap table| cf
  investor -->|view holdings, transfers, dividends| cf
  admin -->|approve valuation / issue / mint / dividend| cf
  judge -->|/verify, /hsk, company pages| cf
  cf --> app
  cf --> scan
  founder -. add network / token .-> chain
  investor -. wallet RPC via /rpc .-> chain

  app -->|SafeFetcher crawl| sites
  app -->|LLM calls| samba
  app -->|LLM fallback| deepinfra
  app -->|web search #1| brave
  app -->|web search #2 + LLM fallback<br/>via host bridge| claude
  app -->|issue, KYC, dividends| chain
  app -->|mirror + CapTableAnchor| hoodi
  app -->|mirror + CapTableAnchor| hsk
  scan -->|index| chain
  judge -. check txs .-> hoodi
  judge -. check txs .-> hsk
```

Rendered: [SVG](diagrams/01-system-context.svg) · [PNG](diagrams/01-system-context.png) · source [`01-system-context.mmd`](diagrams/01-system-context.mmd)

---

## 2. Deployment / runtime topology

The host runs nginx on :443. It serves the SPA from `web/dist` and proxies everything else to services that only
listen on `127.0.0.1`. The containers belong to the docker compose project `blockid-app` (`deploy/vm-app`, with
`docker-compose.override.yml` for single-host ports), plus a separate `blockscout` project. The Claude bridge is
a **systemd service on the host**, not a container. It listens on `172.18.0.1:8765`, which is the gateway of
the `blockid-app_default` network, so only containers on that network can call it.

```mermaid
flowchart TB
  user(["Browsers / wallets"]) --> cf["Cloudflare edge"]
  cf -->|HTTPS 443| nginx

  subgraph host["Host VM"]
    nginx["host nginx :443<br/>real_ip from CF-Connecting-IP<br/>CSP / HSTS / X-Frame-Options"]
    dist[/"web/dist<br/>React SPA (static)"/]
    bridge["claude-search-bridge (systemd)<br/>172.18.0.1:8765 = gateway of default net<br/>/search: Haiku + WebSearch<br/>/complete: Sonnet, no tools"]
    keys[/"/opt/blockid/keys<br/>encrypted keystores"/]
  end

  subgraph compose["docker compose project blockid-app"]
    api["agents-api :8080<br/>nets: default + issuer"]
    worker["agents-worker<br/>nets: default only"]
    issuer["issuer :8090 (ONLY key holder)<br/>nets: issuer + issuer-backend<br/>+ issuer-egress"]
    pg[("postgres :5432<br/>nets: default + issuer-backend")]
    evmd["evmd (BlockID EVM 262626)<br/>:8545 :8546 :26657 :1317<br/>nets: default + issuer-backend"]
    explorer["explorer (Ping.pub)<br/>nets: default"]
  end

  subgraph bs["docker compose project blockscout"]
    bsfront["frontend :3000"]
    bsback["backend :4000<br/>nets: blockscout_default<br/>+ blockid-app_default"]
    bsdb[("bs-db + bs-redis")]
  end

  nginx -->|"eth.blockid.au /"| dist
  nginx -->|"/api/ → 127.0.0.1:8080"| api
  nginx -->|"/rpc → :8080/v1/rpc<br/>(eth_ / net_ / web3_ allowlist)"| api
  nginx -->|"/cometbft/ read-only routes<br/>(others 403), /lcd/ → :1317"| evmd
  nginx -->|"/explorer/ → :8082"| explorer
  nginx -->|"scan.blockid.au /api, /socket → :8200"| bsback
  nginx -->|"scan.blockid.au / → :8201"| bsfront

  api -->|SQL| pg
  api -->|"JSON-RPC proxy, reads"| evmd
  api -->|"POST /issue /anchor /mint ...<br/>X-Internal-Token (issuer net)"| issuer
  worker -->|"claim jobs, write results"| pg
  worker -->|"POST /search, /complete<br/>X-Bridge-Token"| bridge
  issuer -->|"SQL (issuer-backend)"| pg
  issuer -->|"signed txs (issuer-backend)"| evmd
  keys -. "read-only mount /keys" .-> issuer
  bsfront --> bsback
  bsback --> bsdb
  bsback -->|"index via evmd:8545"| evmd
  explorer -. "browser calls /cometbft, /lcd" .-> nginx

  worker -. "NO route: not on issuer networks,<br/>no ISSUER_INTERNAL_TOKEN" .-x issuer

  issuer -->|"issuer-egress"| extc[("Ethereum Hoodi RPC<br/>HashKey testnet RPC")]
  worker -->|"default egress"| extw["SambaNova, DeepInfra,<br/>Brave, startup websites"]
  api -->|"default egress (/verify reads)"| extc
  bridge --> anth["Anthropic (Claude CLI)"]
```

Rendered: [SVG](diagrams/02-deployment-topology.svg) · [PNG](diagrams/02-deployment-topology.png) · source [`02-deployment-topology.mmd`](diagrams/02-deployment-topology.mmd)

**nginx routes (eth.blockid.au).** `/` goes to `web/dist` (SPA, `try_files … /index.html`). `/api/` goes to
`agents-api` :8080, with the prefix stripped. `/rpc` goes to `agents-api /v1/rpc`, a JSON-RPC allowlist proxy
(`eth_*` minus signing and node-account methods, plus `net_*` and `web3_*`, batch ≤ 20, body ≤ 256 KB).
`/cometbft/(status|block|blockchain|block_results|block_by_hash|commit|validators|genesis|abci_info|tx|tx_search|block_search|consensus_params|health)`
goes to evmd :26657, and every other `/cometbft/` path returns 403. `/lcd/` goes to :1317 and `/explorer/` to
Ping.pub on :8082. **scan.blockid.au** sends `/api` and `/socket` to the Blockscout backend on :8200 and
everything else to the frontend on :8201. nginx takes the client IP from `CF-Connecting-IP`, but only when the
request comes from a Cloudflare range (`conf.d/cloudflare-realip.conf`).

**Docker networks (verified with `docker network inspect`).**

| Network | Internal | Members | Purpose |
|---|---|---|---|
| `blockid-app_default` (172.18.0.0/16) | no | agents-api, agents-worker, postgres, evmd, explorer, blockscout backend | app traffic + internet egress for LLM/search/crawl |
| `blockid-app_issuer` | **yes** | agents-api, issuer | the only path to the issuer's :8090 |
| `blockid-app_issuer-backend` | **yes** | issuer, postgres, evmd | issuer → DB and BlockID chain |
| `blockid-app_issuer-egress` | no | issuer only | outbound Hoodi / HSK RPC |
| `blockscout_default` | no | blockscout frontend, backend, db, redis | explorer internals |

`agents-worker` handles untrusted web content, and it is only on `default`. It has no route to the issuer and
does not get `/opt/blockid/issuer.env` (`ISSUER_INTERNAL_TOKEN`). The keystores in `/opt/blockid/keys` are
mounted read-only into the issuer only. The `web` container in the compose file is not used on this host,
because nginx serves `web/dist` directly.

---

## 3. Valuation pipeline (`site_valuation` graph)

The step order is fixed in code (`graph.py`), not by a prompt. Each step is a LangGraph node, and state is
checkpointed in Postgres. The run stops at a human gate (`interrupt()`). The research budget is at most **3 web
searches per valuation**: the competitors query in the competitor step, and the market and valuation-benchmark
queries in the market step. The top 2 results of each search are fetched and stored as evidence (URL, time,
SHA-256).

```mermaid
flowchart TD
  req["POST /v1/studio/valuations {url, metrics?}<br/>limits: 3 / wallet / day, 60 / day global, 5 active"] --> q[("studio.valuations<br/>status = queued")]
  q -->|"worker claims row<br/>FOR UPDATE SKIP LOCKED → running"| rs

  subgraph graph["LangGraph site_valuation (fixed order in code, checkpointed in Postgres)"]
    rs["read_site<br/>SafeFetcher: same site, ≤ 6 pages (SITE_MAX_PAGES)<br/>robots.txt, public IPs only, 2 MB / 20 s per page, 120 s crawl<br/>emails + phones stripped"]
    pr["profile<br/>LLM → StartupProfile (facts on pages only;<br/>unknown numbers stay 0)"]
    co["competitors<br/>search 1/3: '&lt;name&gt; competitors alternatives &lt;country&gt;'<br/>fetch top 2 results → LLM names ≤ 9<br/>keep only names present in fetched text<br/>fetch homepages; funding only with verbatim quote"]
    fb{"&lt; 3 competitors<br/>or search down?"}
    sg["model-suggested competitors<br/>kept only if fetched homepage<br/>is that brand and on-topic"]
    mk["market<br/>search 2/3: '&lt;sector&gt; market size growth'<br/>search 3/3: '&lt;sector&gt; startup funding valuation<br/>revenue multiple' → LLM MarketAnalysis<br/>findings citing unknown URLs are dropped"]
    mfb["no search results: analyse only the company's<br/>and competitors' own sites (warning shown)"]
    sv["svi<br/>LLM suggests 5 qualitative scores (ai_suggested)<br/>code computes revenue + growth, index, band,<br/>valuation low / mid / high, report_sha256"]
    na["narrative<br/>LLM → investor-memo summary"]
    gate[["gate_valuation<br/>LangGraph interrupt()"]]
  end

  rs --> pr --> co --> fb
  fb -->|yes| sg --> mk
  fb -->|no| mk
  mk -. "0 search pages" .-> mfb -.-> sv
  mk --> sv --> na --> gate
  gate -->|"status = waiting_approval"| adm{"Admin decision<br/>POST .../decision"}
  adm -->|"approve (+ optional overrides → basis human)"| ok[("approved<br/>→ founder can create company")]
  adm -->|reject| rej[("rejected")]
  rs & pr & co & mk & sv & na -. "any step fails" .-> fail[("failed")]
```

Rendered: [SVG](diagrams/03-valuation-pipeline.svg) · [PNG](diagrams/03-valuation-pipeline.png) · source [`03-valuation-pipeline.mmd`](diagrams/03-valuation-pipeline.mmd)

Controls against hallucination, all enforced in code:

- Competitor names are kept only if they literally appear in the fetched text, and the startup itself is
  removed.
- A funding amount is kept only with a source URL and a verbatim quote from a page fetched in that step.
- Market findings are dropped if they cite a URL that was not fetched.
- Model-suggested competitors are kept only if their fetched homepage names that brand and is on-topic.

After the admin decision, the result is stored in `studio.valuations` (`waiting_approval` → `approved` or
`rejected`). Overrides change a dimension's basis to `human`.

### 3b. SVI scoring and valuation formula

The LLM **only suggests** the 5 qualitative dimension scores. `tools/svi.py` computes revenue performance, growth
capability, the index, the band and the valuation range. The same inputs always give the same output.

```mermaid
flowchart LR
  subgraph llm["LLM (suggests only, labelled ai_suggested)"]
    f["founder_quality · w 0.20"]
    p["product_strength · w 0.15"]
    m["market_attractiveness · w 0.20"]
    i["investment_readiness · w 0.10"]
    t["trust_verification · w 0.05"]
  end
  subgraph code["Code (tools/svi.py, deterministic)"]
    r["revenue_performance · w 0.20<br/>0.7 × log-scale revenue vs stage benchmark<br/>+ 0.3 × gross margin"]
    g["growth_capability · w 0.10<br/>0.6 × (YoY growth / 2)<br/>+ 0.4 × (runway / 24 months)"]
  end
  metrics[/"profile metrics<br/>website facts or founder self_reported"/] --> r & g
  f & p & m & i & t & r & g --> idx["index = round(Σ weight × score, 2)"]
  idx --> band["grade band<br/>A ≥ 80 · B ≥ 65 · C ≥ 50 · D ≥ 35 · E &lt; 35"]
  idx --> fac["factor = 0.5 + index / 100"]
  fac --> val{"revenue &gt; 0 and cited<br/>median revenue multiple?"}
  val -->|yes| rm["low / mid / high = revenue × (multiple_low | median | multiple_high) × factor<br/>(low defaults to 0.6 × median, high to 1.5 × median)"]
  val -->|no| st["low / mid / high = stage benchmark range × factor<br/>(idea, pre-seed, seed, series-a, growth)"]
  rm & st --> round["rounded to nearest A$1,000<br/>total_shares = mid / A$1.00"]
  human(["Admin override"]) -. "replaces ai_suggested score,<br/>basis = human" .-> llm
```

Rendered: [SVG](diagrams/04-svi-scoring.svg) · [PNG](diagrams/04-svi-scoring.png) · source [`04-svi-scoring.mmd`](diagrams/04-svi-scoring.mmd)

### 3c. LLM and web search routing

The live configuration is `LLM_BACKEND=hosted`, `SVI_TIER=cloud`, `LLM_PROVIDER_ORDER=sambanova,claude_bridge,deepinfra`
and `SEARCH_PROVIDERS=brave,claude`. The `local` tier (PII agents) always stays on the LiteLLM gateway and never
falls back to a hosted provider. The first answer that passes the Pydantic schema wins. Each call records which
provider answered in `llm_providers_used`, and the valuation page shows it.

```mermaid
flowchart TD
  call["deps.ask(agent, tier, schema)<br/>policy.guard(): allowed tier + tools"] --> tier{"tier"}
  tier -->|local| gw["LiteLLM gateway (GPU VM)<br/>PII agents only, never falls back to cloud"]
  tier -->|"cloud / cloud_max<br/>(SVI_TIER=cloud: all valuation steps)"| chain

  subgraph chain["FallbackLLM: LLM_PROVIDER_ORDER = sambanova, claude_bridge, deepinfra"]
    s1["sambanova: gpt-oss-120b"] -->|fail| s2["sambanova: DeepSeek-V3.1"]
    s2 -->|fail| s3["sambanova: DeepSeek-V3.2"]
    s3 -->|fail| s4["sambanova: Llama-3.3-70B"]
    s4 -->|fail| s5["sambanova: gemma-4-31B-it"]
    s5 -->|fail| cb["claude-bridge POST /complete<br/>Sonnet, no tools, 300 / day"]
    cb -->|fail| d1["deepinfra: DeepSeek-V4-Flash"]
    d1 -->|fail| d2["deepinfra: gpt-oss-120b"]
  end
  d2 -->|fail| err[("LLMError → step failed")]
  s1 & s2 & s3 & s4 & s5 & cb & d1 & d2 -->|"first answer that validates<br/>against the Pydantic schema"| out[("typed result<br/>+ llm_providers_used")]
  note1["SambaNova: 429 or 402 parks that model 10 min;<br/>timeout / 5xx = one retry; JSON mode falls back to prompt-only JSON<br/>Claude bridge: any failure parks it 10 min"] -.- chain

  subgraph search["SearchChain: SEARCH_PROVIDERS = brave, claude (budget 3 queries / valuation)"]
    b["Brave Search API<br/>1 req/s, 72 h cache"] -->|"quota / error / empty"| cs["claude bridge POST /search<br/>Haiku + WebSearch only, 150 / day"]
  end
  cs -->|"all fail → SearchUnavailable"| fbk["fallback: model-suggested competitors<br/>verified by homepage fetch; market from own sites"]
```

Rendered: [SVG](diagrams/05-llm-search-routing.svg) · [PNG](diagrams/05-llm-search-routing.png) · source [`05-llm-search-routing.mmd`](diagrams/05-llm-search-routing.mmd)

---

## 4. Issuance: one approval, three chains

The founder creates the company as a `draft` and submits it (`pending_issue`). **One** admin approval starts the
whole chain:

1. The API flips the status with a single guarded `UPDATE` (the atomic claim).
2. The API calls the issuer over the internal network with `X-Internal-Token`.
3. The issuer issues on BlockID Chain.
4. The issuer syncs Ethereum Hoodi, then HashKey testnet, with no second gate.

Each external chain gets a **paused** mirror token with the same balances, the same `valuationReportHash`, and a
`CapTableAnchor.anchor` of the OpenZeppelin Merkle root over `(holder, balance)` at BlockID block N. A failure
on one chain is recorded per chain and does not block the next one. Retries are idempotent: deployed contracts
are reused, only balance differences are issued, and paid claims are skipped.

```mermaid
sequenceDiagram
  autonumber
  actor F as Founder (browser)
  actor A as Admin (browser)
  participant API as agents-api
  participant DB as Postgres studio.*
  participant I as issuer (keys)
  participant L as BlockID EVM 262626
  participant H as Ethereum Hoodi 560048
  participant K as HashKey testnet 133

  F->>API: POST /v1/studio/companies {valuation_id, name, ticker, holders}
  API->>DB: insert company (draft) + holders<br/>checks: approved valuation, pct sum 100, EIP-55, unique ticker
  F->>API: POST /v1/studio/companies/{id}/submit (admin or active issuer wallet)
  API->>DB: status = pending_issue
  A->>API: POST /v1/admin/companies/{id}/approve-issue<br/>(admin session: SIWE or password, Origin allowlisted)
  API->>DB: single UPDATE ... WHERE status = pending_issue<br/>OR (failed AND local_block IS NULL) → issuing
  API->>DB: audit + event issue_approved
  API->>I: POST /issue {company_id} (X-Internal-Token, internal network)
  I-->>API: 202 Accepted (work runs in background thread)
  Note over API,I: if the issuer call fails the API reverts the status and returns 502

  I->>DB: re-read company inside per-company lock, require issuing
  rect rgb(235, 244, 255)
    Note over I,L: BlockID Chain (register of record)
    I->>L: deploy IdentityRegistry, grant KYC_AGENT_ROLE
    I->>L: deploy BlockIDShareToken (decimals 0, max 500 holders)
    I->>L: deploy DividendDistributor
    loop each holder
      I->>L: registerInvestor(wallet, 36, now+1y, keccak(name))
      I->>L: drip 0.01 BLKD if balance < 0.001
      I->>L: issue(wallet, shares - balance, keccak("studio-issue:id"))
    end
    I->>L: anchorValuation(reportHash = keccak256(canonical report), cents)
    I->>DB: events kyc / drip / issued / valuation_anchored, mark 1.00, status issued, sync.blockid = done
  end
  I->>DB: status = anchoring
  rect rgb(240, 250, 240)
    Note over I,H: Sync Hoodi (preflight: chain id + enough ETH for gas)
    I->>L: snapshot balances at block N (sum must equal totalSupply)
    I->>H: deploy mirror IdentityRegistry + BlockIDShareToken (if missing)
    I->>H: KYC + issue / cancel to match balances, anchorValuation(same hash), pause()
    I->>H: CapTableAnchor.anchor(ticker, localToken, 262626, N, merkleRoot, supply, uri)
    I->>DB: events hoodi_mirrored + anchored, hoodi_* columns, sync.hoodi = done or failed
  end
  rect rgb(255, 246, 235)
    Note over I,K: Sync HSK, same steps, with a read-lag guard that waits until the RPC read path sees each receipt block
    I->>K: mirror registry + token, balances, anchorValuation, pause()
    I->>K: CapTableAnchor.anchor(...)
    I->>DB: events hsk_mirrored + anchored, hsk_* columns, sync.hsk = done or failed
  end
  I->>DB: status = anchored (all done) / partially_anchored (some) / issued (none)

  loop every 3 s while issuing or anchoring
    F->>API: GET /v1/companies/{ticker}
    API-->>F: status, sync {blockid, hoodi, hsk, step, errors}, events
  end
  opt a chain failed
    A->>API: POST /v1/admin/companies/{id}/approve-anchor (re-sync)
    API->>I: POST /anchor → re-runs only missing or failed chains (idempotent)
  end
```

Rendered: [SVG](diagrams/06-issuance-sequence.svg) · [PNG](diagrams/06-issuance-sequence.png) · source [`06-issuance-sequence.mmd`](diagrams/06-issuance-sequence.mmd)

The founder's tracker (`/c/:ticker`) polls `GET /v1/companies/{ticker}` every 3 s while the status is
`issuing` or `anchoring`, then every 15 s while the status is transient, and shows `sync.step`
(`{chain, action, n, of}`). Mints and dividends use the same pattern. Their rows are claimed atomically
(`approved` → `minting`, and `approved` → `paying`). The relayer pays gas for `claimFor`, and a mint re-anchors
every external chain that was already synced.

---

## 5. Public `/verify` flow

`/verify/:ticker` lets anyone check that the valuation report shown is exactly the one anchored on-chain. The
report is the subset `{url, profile, competitors, market, svi, self_reported}` of the API valuation view.
It is hashed as `keccak256(utf8(canonical JSON))`, where canonical JSON means keys sorted recursively,
separators `(",", ":")` and no ASCII escaping (`studio/report_hash.py`, `web/app/src/lib/canonical.ts`).

```mermaid
sequenceDiagram
  autonumber
  actor V as Verifier (browser /verify/:ticker)
  participant API as agents-api /v1/verify
  participant DB as Postgres
  participant L as BlockID EVM
  participant H as Hoodi
  participant K as HashKey testnet

  V->>API: GET /v1/verify/{ticker}
  API->>DB: company (on-chain status) + stored valuation row
  API->>API: report = {url, profile, competitors, market, svi, self_reported}<br/>canonical JSON: keys sorted, separators (",", ":"), no ASCII escaping<br/>report_hash = keccak256(utf8(json)), recompute SVI with the public formula
  par read the anchored hash on each chain
    API->>L: token.valuationReportHash()
  and
    API->>H: mirror.valuationReportHash()
  and
    API->>K: mirror.valuationReportHash()
  end
  API-->>V: report (raw JSON text), report_hash, formula, recomputed, onchain[{chain, hash, match}]
  V->>V: parse losslessly (number lexemes kept)<br/>canonicalJson + keccak256 in the browser (viem)
  V->>API: POST /v1/verify/hash {report} (same text, debounced)
  API-->>V: server keccak256 (Python)
  V->>V: verdict OK only if browser hash = server hash<br/>= every on-chain valuationReportHash
  opt Tamper test
    V->>V: change founder_quality score by 1 → both hashes change → verdict "Mismatch"
    V->>V: Reset → original text → verdict OK again
  end
```

Rendered: [SVG](diagrams/07-verify-flow.svg) · [PNG](diagrams/07-verify-flow.png) · source [`07-verify-flow.mmd`](diagrams/07-verify-flow.mmd)

The page also recomputes the SVI index, band and valuation from the report's own inputs with the public formula
(`GET /v1/verify` returns `formula` and `recomputed`). A reader can see that the numbers follow from the scores,
not only that the bytes match.

---

## 6. Security trust boundaries

There are three zones. The **edge** is Cloudflare plus nginx. The **application zone** holds the API, the
worker, the SafeFetcher and Postgres, and has no keys. The **key zone** holds only the issuer, on internal
networks plus an egress-only network. Untrusted web content enters only through the SafeFetcher into the worker.
Nothing reaches a chain except through an admin-approved row that the issuer claims atomically.

```mermaid
flowchart LR
  subgraph z0["Untrusted: internet"]
    web["Websites being valued<br/>(prompt-injection risk)"]
    usr["Browsers, wallets,<br/>scripts"]
  end

  subgraph z1["Edge"]
    cf["Cloudflare<br/>TLS, proxy"]
    ng["nginx: real IP from CF-Connecting-IP only for CF ranges<br/>CSP (self + hashed bootstrap), HSTS, X-Frame DENY, nosniff<br/>/rpc and /cometbft allowlists"]
  end

  subgraph z2["Application zone (network: default)"]
    api["agents-api<br/>SIWE (EIP-4361, single-use nonce, domain/chain checks)<br/>or bcrypt password + lockout by real IP<br/>__Host- cookie, HttpOnly, Secure, SameSite=Lax<br/>CSRF: Origin/Referer allowlist on writes<br/>valuation rate limits, API docs off"]
    wk["agents-worker (no keys, no issuer token)<br/>policy.guard(): per-agent tools + tiers<br/>FORBIDDEN: sign_tx, send_tx, read_private_key,<br/>deploy_contract, shell<br/>web text wrapped in &lt;data&gt;, Pydantic outputs,<br/>uncited claims dropped"]
    sf["SafeFetcher (SSRF guard)<br/>public IPs only, DNS pinned,<br/>per-hop redirect checks, size/time caps"]
    db[("Postgres studio.*<br/>approval states, audit")]
  end

  subgraph z3["Key zone (internal networks issuer + issuer-backend, egress-only net)"]
    is["issuer<br/>X-Internal-Token, acts only on<br/>admin-approved rows (atomic claim)<br/>checks chain state before retry"]
    ks[/"keystores, read-only, uid 10001"/]
  end

  usr --> cf --> ng --> api
  web -->|HTML| sf --> wk
  wk -->|results, status| db
  api --> db
  api -->|approved actions only| is
  is --> db
  ks --> is
  is -->|signed txs| chains[("BlockID EVM · Hoodi · HSK")]
  wk -. "blocked: no network path" .-x is
  sf -. "blocked: private / internal hosts<br/>(issuer, postgres, 10.x, 127.x)" .-x db
```

Rendered: [SVG](diagrams/08-security-boundaries.svg) · [PNG](diagrams/08-security-boundaries.png) · source [`08-security-boundaries.mmd`](diagrams/08-security-boundaries.mmd)

| Boundary | Control | Where |
|---|---|---|
| Browser → API | SIWE (EIP-4361, single-use nonce, domain/URI/chain checks) or admin password (bcrypt, 5 failures / 15 min per real IP); cookie `__Host-bid_session`; Origin/Referer allowlist on every non-GET (except the cookie-less `/v1/rpc`) | `studio/auth.py`, `api.py` |
| Public RPC | `/rpc` method allowlist; `/cometbft/` read-only routes | `studio/routes.py`, nginx |
| Web content → agents | SafeFetcher (public IPs only, DNS pinned, per-hop redirect checks, 2 MB / 20 s per page, 120 s per crawl, robots.txt); `<data>` wrapping; Pydantic outputs; uncited claims dropped | `tools/safefetch.py`, agents |
| Agents → tools / models | `policy.guard()` per agent; `FORBIDDEN_TOOLS`; PII agents local tier only | `policy.py` |
| API → issuer | internal network + `X-Internal-Token`; only admin-approved rows; atomic status claims; revert on issuer error | `studio/routes.py`, `issuer/app.py` |
| Keys | encrypted keystores, read-only mount, issuer container only | compose, `issuer/keys.py` |
| Abuse | valuations: 3 / wallet / day, 60 / day global, 5 active | `studio/services.py` |
| Web | CSP (self + hashed bootstrap script, Google Fonts, Hoodi RPC, scan.blockid.au), HSTS, X-Frame-Options DENY, nosniff, Permissions-Policy; API docs disabled | nginx snippet, `api.py` |

---

## 7. Smart contracts

All contracts are Solidity 0.8.28 on OpenZeppelin v5.4.0. The same bytecode is deployed on all three chains. In
the Studio flow, the issuer key receives `DEFAULT_ADMIN_ROLE`, `ISSUER_ROLE`, `PAUSER_ROLE` and
`TRANSFER_AGENT_ROLE` on each company token, and `KYC_AGENT_ROLE` on its registry. `CapTableAnchor` is deployed
once per external chain and grants `ANCHOR_ROLE` to the issuer.

```mermaid
classDiagram
  direction LR
  class IdentityRegistry {
    <<AccessControl>>
    +KYC_AGENT_ROLE
    -mapping investors: verified, country, expiresAt, kycRef
    +countryBlocked(uint16) bool
    +registerInvestor(wallet, country, expiresAt, kycRef)
    +revokeInvestor(wallet)
    +setCountryBlocked(country, blocked)
    +isVerified(wallet) bool
    +investorOf(wallet) Investor
  }
  class BlockIDShareToken {
    <<ERC20 + AccessControl + Pausable>>
    +ISSUER_ROLE
    +TRANSFER_AGENT_ROLE
    +PAUSER_ROLE
    +decimals() 0
    +lockupUntil
    +maxShareholders
    +valuationReportHash bytes32
    +valuationPerShareCents
    +legalDocHash bytes32
    +issue(to, amount, resolutionRef)
    +cancel(from, amount, resolutionRef)
    +anchorValuation(reportHash, perShareCents)
    +setLegalDocHash(docHash)
    +pause() / unpause()
    +setFrozen(wallet, frozen)
    +forcedTransfer(from, to, amount, reason)
    #_update() KYC, freeze, lock-up, pause, holder cap
  }
  class DividendDistributor {
    <<AccessControl + ReentrancyGuard>>
    +ISSUER_ROLE
    +shareToken
    +createRound(merkleRoot, payToken, total, recordBlock, deadline, resolutionRef) roundId
    +claim(roundId, amount, proof)
    +claimFor(roundId, account, amount, proof)
    +closeRound(roundId, to)
    +hasClaimed(roundId, account) bool
  }
  class CapTableAnchor {
    <<AccessControl>>
    +ANCHOR_ROLE
    -history per ticker: Anchor[]
    +anchor(ticker, localToken, localChainId, localBlock, merkleRoot, totalSupply, uri) index
    +latest(ticker) Anchor
    +anchorCount(ticker)
    +anchorAt(ticker, index)
    +verify(ticker, holder, balance, proof) bool
  }
  class AgentProvenance {
    <<AccessControl>>
    +REGISTRAR_ROLE
    +RECORDER_ROLE
    +APPROVER_ROLE
    +registerAgent(agentId, name, policyHash)
    +setAgentActive(agentId, active)
    +propose(agentId, kind, contentHash, modelId, uri) id
    +approve(id) approver != recorder
    +reject(id, reason)
    +markExecuted(id, executionRef) only if Approved
    +verify(id, contentHash) bool
  }
  class DemoAUD {
    <<ERC20 + Ownable>>
    +decimals() 6
    +mint(to, amount) onlyOwner
  }
  BlockIDShareToken --> IdentityRegistry : isVerified() on every transfer
  DividendDistributor --> BlockIDShareToken : shareToken (record block)
  DividendDistributor --> DemoAUD : payToken (mAUD)
  CapTableAnchor ..> BlockIDShareToken : anchors Merkle root of (holder, balance)
  AgentProvenance ..> BlockIDShareToken : HSK demo - issue guarded by verify()
```

Rendered: [SVG](diagrams/09-contracts-class.svg) · [PNG](diagrams/09-contracts-class.png) · source [`09-contracts-class.mmd`](diagrams/09-contracts-class.mmd)

Notes:

- `BlockIDShareToken._update` checks `isVerified(to)` on every mint and transfer. For ordinary transfers it also
  enforces pause, freeze, lock-up and `isVerified(from)`. `forcedTransfer` bypasses pause, freeze and lock-up,
  but not KYC of the receiver. Holder count is capped (`maxShareholders`, 500 in the Studio).
- `AgentProvenance` enforces four-eyes approval on-chain: the approver must differ from the recorder, and
  `markExecuted` works only after approval. It is deployed and exercised by `scripts/hsk-demo.sh` on HashKey
  testnet. The live Studio issuer does **not** call it yet. The Studio anchors the report hash through
  `anchorValuation` instead.
- `DemoAUD` (mAUD, 6 decimals) is the dividend pay token on BlockID Chain. `DividendDistributor` rounds use
  OpenZeppelin double-hashed Merkle leaves, the same scheme as `CapTableAnchor.verify`.

---

## 8. Data model (`studio` schema)

The schema is `agents/src/blockid_agents/studio/schema.sql`, applied idempotently when the API starts. Some
tables are not shown as related because they have no foreign keys: `admin_users`, `sessions`, `nonces`,
`issuer_wallets` and `audit`. Actors appear as a wallet address or username in text columns such as
`requested_by`, `created_by` and `audit.actor`. Evidence pages and the search cache live in
`/data/evidence.sqlite`, and the hash-chained agent audit log lives in `/data/audit.jsonl`, both on the shared
`/mnt/app-data/agents` volume. LangGraph checkpoints are stored in Postgres.

```mermaid
erDiagram
  valuations ||--o{ companies : "valuation_id"
  companies ||--o{ holders : "company_id"
  companies ||--o{ marks : "company_id"
  companies ||--o{ events : "company_id"
  companies ||--o{ mints : "company_id"
  companies ||--o{ dividends : "company_id"
  companies ||--o{ transfers : "company_id"
  companies ||--o{ kyc_requests : "company_id"

  valuations {
    text id PK
    text url
    text requested_by
    text status "queued running waiting_approval approved rejected failed"
    jsonb steps
    jsonb result "profile competitors market svi evidence"
    jsonb self_reported
    text error
  }
  companies {
    serial id PK
    text ticker UK
    text name
    text valuation_id FK
    numeric svi
    text grade
    numeric valuation_aud
    numeric share_price_aud
    bigint total_shares
    text status
    text created_by
    text local_registry
    text local_token
    text local_distributor
    bigint local_block
    text hoodi_registry
    text hoodi_token
    text hoodi_anchor_tx
    text merkle_root
    text hsk_registry
    text hsk_token
    text hsk_anchor_tx
    text hsk_merkle_root
    jsonb sync "per-chain state"
    text valuation_report_hash
    text transfer_mode "free or approval"
    text error
  }
  holders {
    serial id PK
    int company_id FK
    text name
    text wallet
    numeric pct
    bigint shares
  }
  marks {
    serial id PK
    int company_id FK
    numeric valuation_aud
    numeric mark_aud
    text source "issuance or revaluation"
  }
  events {
    serial id PK
    int company_id FK
    text kind
    text chain "blockid hoodi hsk"
    text tx_hash
    bigint block
    jsonb data
  }
  mints {
    serial id PK
    int company_id FK
    text to_wallet
    bigint shares
    text status "pending approved minting minted failed rejected"
    text tx_hash
  }
  dividends {
    serial id PK
    int company_id FK
    bigint total_units
    text merkle_root
    jsonb claims
    text status "pending approved paying ..."
    int round_id
    text tx_hash
  }
  transfers {
    serial id PK
    int company_id FK
    text from_wallet
    text to_wallet
    bigint shares
    text mode
    text status
    text tx_hash UK
  }
  kyc_requests {
    serial id PK
    int company_id FK
    text wallet
    text name
    text status
    text tx_hash
  }
  admin_users {
    text username PK
    text password_hash
    boolean must_change
  }
  sessions {
    text id PK
    text address
    text username
    text role "user or admin"
    timestamptz expires_at
  }
  nonces {
    text nonce PK
  }
  issuer_wallets {
    text address PK
    text label
    text status "active or revoked"
  }
  audit {
    serial id PK
    text actor
    text action
    text target
    jsonb detail
  }
```

Rendered: [SVG](diagrams/10-data-model-er.svg) · [PNG](diagrams/10-data-model-er.png) · source [`10-data-model-er.mmd`](diagrams/10-data-model-er.mmd)

`events.kind` includes `submitted, issue_approved, deployed, kyc, drip, issued, valuation_anchored,
sync_started, hoodi_mirrored, hsk_mirrored, anchored, sync_failed, sync_skipped, resync_requested, revalued,
mint_requested, minted, dividend_created, dividend_claimed, transfer_requested, transferred, transfer_mode, rejected`.

---

## 9. Company status state machine

`studio.companies.status` is written by the API (draft, pending_issue, issuing, rejected, and reverts when the
issuer is unreachable) and by the issuer (issued, anchoring, anchored, partially_anchored, failed).
`pending_anchor` is a legacy status that is still accepted but is no longer entered, because anchoring now
follows issuance automatically.

```mermaid
stateDiagram-v2
  [*] --> draft : founder POST /studio/companies
  draft --> pending_issue : submit (admin or active issuer wallet)
  pending_issue --> issuing : admin approve-issue (atomic UPDATE)
  issuing --> pending_issue : issuer unreachable (API reverts, 502)
  issuing --> issued : BlockID Chain done
  issuing --> failed : revert / error on BlockID Chain
  failed --> issuing : approve-issue again (local_block IS NULL, idempotent)
  issued --> anchoring : automatic, same approval
  anchoring --> anchored : Hoodi and HSK done
  anchoring --> partially_anchored : one external chain failed
  anchoring --> issued : no external chain done
  partially_anchored --> anchoring : admin approve-anchor (re-sync missing chains)
  issued --> anchoring : admin approve-anchor
  anchored --> anchoring : re-anchor after mint / revaluation
  failed --> anchoring : approve-anchor (local_block set)
  draft --> rejected : admin reject
  pending_issue --> rejected : admin reject
  issued --> rejected : admin reject
  failed --> rejected : admin reject
  anchored --> [*]
  rejected --> [*]
```

Rendered: [SVG](diagrams/11-company-state-machine.svg) · [PNG](diagrams/11-company-state-machine.png) · source [`11-company-state-machine.mmd`](diagrams/11-company-state-machine.mmd)

### Per-chain sync states (`studio.companies.sync`, written only by the issuer)

Each chain is in one of `pending | running | done | failed | skipped`. The company status after a sync pass
comes from `syncstate.overall()`. It is `anchored` if every external chain is done, `partially_anchored` if at
least one is done, and `issued` if none is. Admin re-sync (`approve-anchor`) re-runs only the chains that
`syncstate.missing()` reports.

```mermaid
stateDiagram-v2
  direction LR
  state "companies.sync.blockid" as B {
    [*] --> b_pending
    b_pending --> b_running : issue starts
    b_running --> b_done : registry, token, distributor,<br/>KYC, issue, anchorValuation
    b_running --> b_failed : error (company failed)
    b_failed --> b_running : approve-issue retry
  }
  state "companies.sync.hoodi / companies.sync.hsk (run in order: Hoodi, then HSK)" as X {
    [*] --> x_pending
    x_pending --> x_skipped : RPC or CapTableAnchor not configured
    x_pending --> x_running : BlockID done
    x_running --> x_done : mirror + pause + CapTableAnchor.anchor
    x_running --> x_failed : preflight (gas, chain id) or tx error<br/>(does not block the next chain)
    x_failed --> x_running : approve-anchor re-sync
    x_done --> x_running : re-anchor after mint / revaluation
  }
  B --> X
```

Rendered: [SVG](diagrams/12-chain-sync-states.svg) · [PNG](diagrams/12-chain-sync-states.png) · source [`12-chain-sync-states.mmd`](diagrams/12-chain-sync-states.mmd)

---

### Where the older docs differ from the code

- `docs/IMPLEMENTATION.md` describes a separate `approve-anchor` gate for Hoodi and `anchorValuation(keccak(valuation id))`.
  The current code runs Hoodi and HSK automatically after the single `approve-issue`, and anchors
  `keccak256(canonical report JSON)`. `approve-anchor` is now only a retry / re-sync.
- `docs/ARCHITECTURE.md` (§1) shows the earlier two-VM design (Caddy, GPU VM, Sepolia). The live system is the
  single VM shown in diagram 2, with Ethereum Hoodi.
- `docs/RUNBOOK-STUDIO.md` mentions "DeepInfra + Brave" for the worker. The live LLM chain is SambaNova → Claude
  bridge → DeepInfra, and search is Brave → Claude bridge (see diagram 3c and `docs/LLM-ROUTING.md`).

### Re-rendering

```bash
cd docs/diagrams
for f in *.mmd; do n=${f%.mmd}
  sudo docker run --rm -u $(id -u):$(id -g) -v $PWD:/data minlag/mermaid-cli -i /data/$f -o /data/$n.svg -b white
  sudo docker run --rm -u $(id -u):$(id -g) -v $PWD:/data minlag/mermaid-cli -i /data/$f -o /data/$n.png -b white --size 3000
done
```
