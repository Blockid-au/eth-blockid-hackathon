# Kế hoạch hợp nhất — EAG Global Buildathon Sydney (26/09/2026)

Hợp nhất tài liệu `eth-blockid-hackathon-implementation.md` (bản nâng cấp) với hệ thống **đang chạy** tại
https://eth.blockid.au. Hạn nộp **14:00**, demo 14:00–16:30 (3 phút + 2 phút hỏi đáp), trao giải 17:00.
Track: Sydney Hackathon (bắt buộc) · Real-World Ethereum Applications (Track 6) · HSK Chain (RWA).

> Tài liệu lịch sử (kế hoạch lúc 11:40 ngày 26/09/2026). Kết quả và số liệu hiện tại: [FACTS.md](FACTS.md)
> (10 công ty, 30 hợp đồng token trên 3 chain, A$5.63B, 147 test = 110 pytest + 37 Foundry); kịch bản demo mới
> nhất: [DEMO.md](DEMO.md).

## 0. Quyết định hợp nhất

| Đề xuất trong tài liệu | Hệ thống hiện có | Quyết định |
|---|---|---|
| Next.js 14 + Hardhat + Vercel | Vite/React SPA + FastAPI + Foundry, live trên eth.blockid.au (nginx, Cloudflare, SSL) | **Giữ nguyên.** Viết lại lúc này làm hỏng sản phẩm đang chạy; chấm điểm dựa trên sản phẩm chạy được |
| LLM chấm 7 chỉ số, công thức cố định, hash báo cáo on-chain | Có: 7 tiêu chí SVI, trọng số cố định trong `tools/svi.py`, `anchorValuation` trên token | **Nâng cấp:** hash = keccak256(JSON báo cáo chuẩn hoá), neo trên BlockID + Hoodi + HSK; **thêm trang `/verify`** (đang làm) |
| `BlockIDShareFactory` 1-click, founder ký bằng MetaMask trên HSK | Issuer service ký sau khi admin duyệt (agent không giữ key) | **Giữ mô hình issuer + admin duyệt** (đúng track "AI agent an toàn"); 1-click = một lần admin ký duyệt → tự chạy 3 chain. Factory để roadmap |
| Whitelist KYC trong `_update` | Có: `IdentityRegistry.isVerified` kiểm tra mọi lần nhận/chuyển | Giữ, nhấn mạnh khi pitch |
| Cổ tức native (magnified dividend-per-share) | Cổ tức Merkle (DemoAUD) + relayer `claimFor` trả gas thay cổ đông | Giữ (đã chạy thật). Native HSK dividend để roadmap |
| Neo cap table lên Ethereum **Sepolia** | Neo lên Ethereum **Hoodi** (testnet mới của Ethereum) + **HSK** | Giữ Hoodi, giải thích "Hoodi là testnet hiện hành của Ethereum". Không thêm Sepolia (không có ETH Sepolia, rủi ro thời gian) |
| Chain doanh nghiệp Cosmos EVM gas = 0 | **Đang chạy** (chain id 262626, Blockscout scan.blockid.au) | Điểm mạnh vượt tài liệu — demo trực tiếp |
| Gas sponsor HSK | Issuer drip BLKD cho cổ đông trên BlockID; bản sao Hoodi/HSK bị khoá nên cổ đông không cần gas | Đủ cho demo |
| `DEMO_MODE` khi AI chậm | Định giá thật mất 3–7 phút | **Chuẩn bị sẵn** công ty chờ duyệt để demo bước duyệt → 3 chain; báo cáo mẫu `/v/sample` |
| README, TECHNICAL.md, video, Devfolio | README + docs/HACKATHON.md + docs/DEMO.md đã có | Cập nhật địa chỉ contract + luồng mới; video và form do anh Long làm |

## 1. Lịch làm việc (giờ Sydney)

| Giờ | Việc | Người/agent | Đầu ra |
|---|---|---|---|
| 11:40–12:25 | Tracker phát hành + đồng bộ BlockID → Hoodi → HSK sau 1 lần duyệt; sửa lỗi đứng màn hình; hash báo cáo chuẩn hoá | Agent 1 | Code + test |
| 11:40–12:40 | Trang `/verify` + API `/v1/verify` | Agent 2 | Code + test |
| 12:25–12:55 | Deploy live; chạy E2E thật với công ty `EBA` (duyệt → 3 chain); kiểm tra `/verify` | Lead | Link explorer 3 chain |
| 12:55–13:15 | Chuẩn bị demo: 1 công ty ở trạng thái chờ duyệt, tab trình duyệt, ví MetaMask (BlockID 262626, Hoodi 560048, HSK 133) | Lead + anh Long | Demo sẵn sàng |
| 13:15–13:35 | Cập nhật README (địa chỉ, luồng), DEMO.md (kịch bản 3 phút + Q&A), quét secret, push GitHub (cần anh Long xác nhận) | Lead | Repo public sạch |
| 13:35–13:55 | Quay video 2–3 phút, điền Devfolio, tick 3 track | Anh Long | Bài nộp |
| 13:55–14:00 | Kiểm tra link lần cuối | Cả đội | — |

**Quy tắc cắt giảm:** 12:55 nếu đồng bộ HSK tự động chưa ổn → demo HSK bằng trang `/hsk` (đã có deploy thật) + đồng bộ Hoodi; 13:15 nếu `/verify` chưa xong → demo bằng explorer (`valuationReportHash` trên token).

## 2. Kịch bản demo 3 phút

| Thời điểm | Nói | Làm |
|---|---|---|
| 0:00–0:25 | "Hàng triệu startup quản lý cổ phần bằng Excel. BlockID: AI định giá có kiểm toán, phát hành và quản lý cổ phần on-chain — agent đề xuất, con người duyệt, chain chứng minh." | Trang chủ |
| 0:25–1:05 | "AI đọc website, tìm đối thủ, chấm 7 chỉ số SVI; giá trị do công thức cố định. Hash báo cáo nằm on-chain." | Báo cáo định giá có sẵn (Airwallex / Go1) |
| 1:05–1:45 | "Admin ký duyệt một lần: token cổ phần tạo trên chain doanh nghiệp gas 0, rồi tự đồng bộ sang Ethereum và HashKey." | Bấm duyệt, tracker chạy từng bước, link explorer |
| 1:45–2:20 | "Cổ phần chỉ chuyển cho ví đã KYC; cổ tức chia bằng Merkle, relayer trả gas." | Trang công ty: cap table, contract address 3 chain, Add to MetaMask |
| 2:20–2:45 | "Ai cũng kiểm chứng được: sửa một điểm số là hash không còn khớp." | `/verify` → Tamper test |
| 2:45–3:00 | "Mô hình: phí phát hành, SaaS cap table, transfer agent, % cổ tức, custodian. Pilot Q4/2026 Úc – Việt Nam." | Dashboard admin |

## 3. Hỏi đáp (hợp nhất)

- **Pháp lý ở Úc?** Testnet hôm nay; production qua đối tác AFSL/custodian được cấp phép; KYC nằm sẵn trong luồng chuyển nhượng; tư vấn ASIC trong roadmap Q1/2027.
- **AI định giá có đáng tin?** AI chỉ chấm điểm; công thức công khai; hash on-chain; `/verify` tái tính cùng kết quả. Là công cụ hỗ trợ, không thay định giá độc lập.
- **Agent có giữ key không?** Không. Chỉ issuer service giữ key, nằm trên mạng cô lập, chỉ thực thi dòng đã được admin duyệt; `AgentProvenance` ghi đề xuất → duyệt → thực thi on-chain.
- **Tại sao Cosmos EVM?** Doanh nghiệp cần gas 0 và validator đối tác; Ethereum (Hoodi) là lớp neo công khai; HSK là môi trường RWA công khai.
- **Khác Carta / Cake Equity?** Họ quản lý off-chain; BlockID có cổ phần on-chain, KYC khi chuyển nhượng, cổ tức tự động, định giá AI kiểm chứng được.
- **Bảo mật?** OpenZeppelin v5, 37 test Foundry, 110 test backend, rà soát bảo mật nội bộ (SSRF, CSRF, cô lập issuer), CSP.

## 4. Checklist nộp bài

- [ ] Contract trên HSK Testnet (133) + địa chỉ trong README
- [ ] Ít nhất 1 công ty phát hành qua luồng mới và đồng bộ đủ BlockID + Hoodi + HSK
- [ ] https://eth.blockid.au chạy, MetaMask kết nối được, `/verify` hoạt động
- [ ] Repo public, README đủ: features, install, run, integration, deployed addresses
- [ ] `docs/HACKATHON.md` (TECHNICAL) cập nhật
- [ ] Video 2–3 phút
- [ ] Devfolio: tick Sydney Hackathon, Track 6, HSK Chain
- [x] Không có private key / secret trong repo — đã quét cả lịch sử git lúc 11:45 (chỉ có tham chiếu biến, `.env` bị ignore)

## 5. Rủi ro

| Rủi ro | Phương án |
|---|---|
| Định giá AI mất 3–7 phút | Dùng báo cáo đã có; demo bước duyệt với công ty chờ sẵn |
| RPC HSK lỗi | RPC dự phòng `hashkeychain-testnet.alt.technology` **không phân giải được** (kiểm tra 11:45) → dùng trang `/hsk` (deploy sẵn) + explorer; đồng bộ HSK có nút thử lại |
| Hết HSK/Hoodi gas | Issuer còn 0,08 HSK, 0,46 Hoodi ETH (~15 công ty) |
| Brave hết quota | Claude web search bridge (3 truy vấn/định giá) |
| Wifi hội trường | Quay video dự phòng; tab mở sẵn |
