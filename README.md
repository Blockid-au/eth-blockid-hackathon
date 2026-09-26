# eth.blockid.au — BlockID Agent Platform

Nền tảng **định giá startup bằng AI (SVI) → phát hành cổ phần số → quản lý sổ cổ đông → chia cổ tức tự động** trên chuỗi Cosmos EVM (zero-gas), liên kết Ethereum testnet, dùng MetaMask.

**Nguyên tắc:** AI đề xuất, code tính toán, con người phê duyệt, multisig ký. Không agent nào giữ private key hoặc tự deploy/gửi giao dịch.

```
blockid-eth-platform/
├── agents/                  Python: 6 agent + LangGraph supervisor + API + worker hàng đợi
│   ├── src/blockid_agents/
│   │   ├── agents/          intake · research(Brave) · valuation(SVI) · contract_builder · registry · dividend
│   │   ├── tools/           svi.py · brave.py · merkle.py · chain.py · foundry.py
│   │   ├── graph.py         luồng cố định + 3 cổng duyệt (interrupt)
│   │   ├── policy.py        quyền tối thiểu từng agent (enforce bằng code)
│   │   ├── audit.py         audit log chuỗi hash, phát hiện sửa/xoá
│   │   ├── jobs.py          hàng đợi batch + bật GPU theo nhu cầu
│   │   ├── worker.py · api.py · llm.py · __main__.py
│   └── tests/               19 test (policy, audit, Merkle↔Solidity, SVI, Brave, E2E có cổng duyệt, API)
├── contracts/               Foundry: IdentityRegistry · BlockIDShareToken · DividendDistributor (20 test + fuzz)
├── infra/terraform/         GCP: VPC 2 vùng, 2 VM, Secret Manager, IAM tối thiểu, snapshot
├── deploy/vm-app/           Sydney: Caddy(HTTPS) · web · agents-api · agents-worker · Postgres · evmd · explorer
├── deploy/vm-ai/            Singapore GPU: vLLM(Qwen3.8-27B) · embeddings · LiteLLM gateway · idle-shutdown
├── scripts/                 bootstrap VM · deploy-company.sh (người chạy, key trong keystore)
├── web/                     placeholder frontend
└── docs/                    ARCHITECTURE · AGENTS · SECURITY · RUNBOOK
```

## Chạy thử ngay (không tốn API, không cần GPU)

```bash
make contracts-deps          # OpenZeppelin v5.4.0 + forge-std
make test                    # 20 test Solidity + 19 test Python
make demo                    # chạy trọn luồng: hồ sơ → Brave → SVI → duyệt → contract → sổ cổ đông → cổ tức
```

Kết quả demo (dữ liệu giả lập): SVI 66.77 (B – strong), định giá giữa ~A$3.36M, Safe batch 7 giao dịch (3 KYC + 3 phát hành + neo báo cáo SVI), vòng cổ tức có Merkle root, audit chain hợp lệ.

## Triển khai lên GCP

Xem [docs/RUNBOOK.md](docs/RUNBOOK.md). Tóm tắt:

| Máy | Vùng | Cấu hình | Vai trò |
|---|---|---|---|
| `blockid-app` | australia-southeast1 (Sydney) | n2-standard-8, SSD 500GB | web, API, worker, Postgres, chain node, explorer, dữ liệu KYC |
| `blockid-ai` | asia-southeast1 (Singapore) | g2-standard-8 (L4 24GB), **Spot**, tự tắt khi rảnh | Qwen3.8-27B local + LiteLLM gateway |

Sydney hiện không có GPU L4/RTX PRO 6000 trên GCP, nên máy AI đặt ở Singapore, không có IP public, chỉ nhận kết nối nội bộ VPC từ máy app.

## Tài liệu

- [ARCHITECTURE.md](docs/ARCHITECTURE.md): kiến trúc, luồng dữ liệu, chế độ batch & chi phí
- [AGENTS.md](docs/AGENTS.md): 6 agent, quyền, model, cổng duyệt, API
- [SECURITY.md](docs/SECURITY.md): mô hình bảo mật, pháp lý (ASIC/AFSL), việc cần làm trước production
- [RUNBOOK.md](docs/RUNBOOK.md): cài đặt từng bước, vận hành, xử lý sự cố

> ⚠️ Đây là khung kỹ thuật cho demo/testnet. Hợp đồng cổ phần là bản rút gọn tương thích giao diện ERC-3643; trước khi phát hành cổ phần thật cần: dùng bộ T-REX/ERC-3643 chính thức đã audit, audit độc lập, và tư vấn pháp lý về AFSL (xem SECURITY.md).

## Định giá SVI thật (Brave + Claude CLI, fallback DeepInfra)

```bash
cp .env.example .env    # điền BRAVE_API_KEY, DEEPINFRA_API_KEY; LLM_BACKEND=hosted, SVI_TIER=cloud
make svi PROFILE=examples/agritrace.json
```

- Tầng `cloud`: Claude CLI (`claude -p --json-schema`, không tool, không MCP) → lỗi/timeout/hết quota thì chuyển sang
  DeepInfra theo thứ tự `DEEPINFRA_MODELS` (mặc định Qwen3-235B-A22B-Instruct-2507, rồi gpt-oss-120b).
- Tầng `local` (intake, registry — có PII) luôn đi qua gateway riêng, không bao giờ gửi ra nhà cung cấp hosted.
- Brave hết quota tháng → `BraveQuotaError`, research dừng gọi và ghi `search_quota_exhausted` vào audit log.
