# Các agent

| # | Agent | Model | Tool được phép | Chứa PII | Không bao giờ được |
|---|---|---|---|---|---|
| 1 | **intake** | local | `read_dataroom`, `store_profile` | có | gọi model cloud, gọi mạng |
| 2 | **research** | local | `brave_search`, `fetch_url`, `store_evidence` | không (query đã lọc) | chạm chain |
| 3 | **valuation** | local (cloud nếu cần; input đã ẩn tên) | `svi_score`, `hash_report` | không | tự tính chỉ số/định giá (code tính) |
| 4 | **contract_builder** | cloud / cloud_max | `render_params`, `forge_test`, `slither` | không | viết Solidity, deploy |
| 5 | **registry** | (không dùng LLM) | `build_unsigned_tx` | có | ký/gửi giao dịch |
| 6 | **dividend** | (không dùng LLM) | `read_balances`, `build_merkle`, `build_unsigned_tx` | không | ký/gửi giao dịch |
| – | **supervisor** | – | LangGraph: thứ tự bước + 3 cổng duyệt | – | bị prompt thay đổi |

Tool cấm với mọi agent: `sign_tx`, `send_tx`, `read_private_key`, `deploy_contract`, `shell`. Bảng quyền nằm trong `policy.py` và được kiểm tra **bằng code** trước mỗi lần gọi model hoặc tool, nên tài liệu có chứa prompt injection cũng không mở rộng được quyền của agent.

## Chi tiết

**1. Intake**: đọc data room (text đã OCR) và trích ra `StartupProfile` theo schema. Số liệu nào không có trong tài liệu thì để 0, và liệt kê các tài liệu còn thiếu (BCTC kiểm toán, điều lệ, IP assignment…).

**2. Research (Brave)**: xem ARCHITECTURE §3. Kết quả là `MarketAnalysis` gồm tăng trưởng thị trường, bội số doanh thu (low/median/high) và các nhận định kèm URL nguồn.

**3. Valuation (SVI)**: 7 trụ cột với trọng số Founder 20%, Product 15%, Market 20%, Revenue 20%, Growth 10%, Investment Readiness 10%, Trust 5%.
- Revenue và Growth: **code tính** từ số liệu.
- 5 trụ cột định tính: LLM **đề xuất** (gắn nhãn `ai_suggested`), người duyệt xác nhận hoặc sửa ở Cổng 1 (chuyển thành `human`).
- Định giá = doanh thu × bội số (có trích nguồn) × hệ số SVI (0.5 + index/100). Nếu chưa có doanh thu hoặc chưa có bội số, dùng khoảng theo giai đoạn (**placeholder, cần hiệu chỉnh bằng dữ liệu nghiên cứu SVI**).
- Báo cáo được băm SHA-256, và hash này được neo lên token qua `anchorValuation`.

**4. Contract Builder**: đề xuất `TokenParams` (JSON), chạy `forge test` + deploy dry-run + Slither, rồi nhờ Sonnet 5 review tham số. Agent không viết Solidity và không deploy.

**5. Registry**: từ cap table đã được HĐQT duyệt, tạo **Safe Transaction Builder batch** gồm KYC register, issue và anchor valuation. Người ký import batch vào Safe{Wallet} để kiểm tra và ký.

**6. Dividend**: từ số dư tại `record_block`, chia pro-rata làm tròn xuống (phần dư giữ lại cho issuer), dựng Merkle tree tương thích OpenZeppelin, rồi tạo batch `approve` + `createRound`. Cổ đông tự claim; relayer có thể trả gas thay.

## API (async)

| Method | Path | Mô tả |
|---|---|---|
| POST | `/v1/onboarding` | `{dataroom:{file:text}, issuance_inputs:{issuer_safe, transfer_agent, kyc_agent, legal_doc_hash, board_resolution_id, share_class}}` → `workflow_id` |
| POST | `/v1/dividends` | `{dividend:{record_block, balances, total_amount, pay_token, distributor, board_resolution_id}}` |
| GET | `/v1/workflows/{id}` | trạng thái, cổng đang chờ (`gate`), kết quả (data room không bao giờ được trả về) |
| POST | `/v1/workflows/{id}/decision` | `{decision:{approved, reviewer, ...}}`. Cổng 1: `overrides`. Cổng 2: `deployment`, `cap_table`, `kyc` |
| GET | `/v1/workflows/{id}/safe-batch` | JSON để import vào Safe |

Header `X-API-Key`. Với giao diện dành cho nhân viên, nên đặt Google IAP hoặc Cloudflare Access phía trước.

## Thêm agent mới

1. Tạo `agents/src/blockid_agents/agents/<ten>.py` với hàm `run(state, deps) -> dict`.
2. Khai báo quyền trong `policy.POLICIES`.
3. Thêm node và edge vào `graph.py`. Nếu agent có tác động on-chain hoặc tài chính, đặt một cổng `interrupt()` phía trước.
4. Viết test với `FakeLLM` (xem `tests/test_platform.py`).
