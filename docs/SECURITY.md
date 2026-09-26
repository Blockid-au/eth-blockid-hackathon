# Bảo mật & pháp lý

## Mô hình bảo mật

| Rủi ro | Biện pháp trong khung |
|---|---|
| Agent tự ký/chuyển tài sản | Không có key trong runtime. Registry/Dividend chỉ tạo **unsigned** Safe batch. Tool ký/gửi/deploy bị cấm ở `policy.py` |
| Prompt injection từ tài liệu/web | Nội dung luôn được bọc `<data>` và đánh dấu là untrusted. Quyền enforce bằng code, không bằng prompt. Output phải qua schema Pydantic. Research tự loại nhận định trích URL không có thật |
| PII rời máy chủ | Agent chứa PII chỉ được dùng tier `local` (code chặn). Gateway không fallback sang cloud. Tên founder bị ẩn trước khi valuation gọi model. Query Brave được lọc email/số điện thoại |
| AI bịa số | Chỉ số SVI và định giá do code tính (tất định, có hash). LLM chỉ đề xuất điểm định tính và phải qua người duyệt |
| Contract lỗi | Template cố định + 20 test/fuzz + dry-run + Slither. Cổng 2 từ chối cứng khi có lỗi. Deploy do người chạy với keystore riêng |
| Sửa lịch sử | Audit log chuỗi hash (`verify-audit`). Nên neo head hash lên chain hằng ngày |
| Lộ máy chủ | VM AI không có IP public, chỉ mở :4000 cho VM app. SSH chỉ qua IAP. Secret nằm trong Secret Manager. Service account quyền tối thiểu (app chỉ được *start* VM AI) |
| Mất dữ liệu | Snapshot ổ dữ liệu hằng ngày, giữ 14 ngày. Postgres/evmd nằm trên ổ riêng |

## Việc bắt buộc trước khi có khách hàng thật

1. **Contract:**
   - Thay `IdentityRegistry` và compliance bằng bộ **ERC-3643 (T-REX) chính thức + ONCHAINID**. Token hiện tại giữ cùng giao diện `isVerified()` để chuyển đổi dễ dàng.
   - Thuê **audit độc lập**.
   - Đặt ngưỡng Safe tối thiểu 2/3.
2. **Chain:**
   - Chạy tối thiểu **4 validator độc lập**. Một node chỉ đủ cho demo.
   - Pin phiên bản `cosmos/evm`.
   - Rà soát genesis.
   - Không mở `26657` công khai nếu không cần explorer.
3. **Pháp lý (Úc)** *(không phải tư vấn pháp lý)*:
   - ASIC coi tokenised securities là sản phẩm tài chính.
   - Digital Assets Framework Act 2026 có hiệu lực từ **9/4/2027**, yêu cầu giấy phép AFSL cho digital asset platform và tokenised custody platform.
   - Các dịch vụ lưu ký, quản lý chuyển nhượng và chia cổ tức có thu phí cần luật sư fintech đánh giá.
   - Nghĩa vụ AML/CTF với AUSTRAC có thể áp dụng song song.
4. **Dữ liệu cá nhân:**
   - Privacy Act 1988 (APP 8) áp dụng khi xử lý dữ liệu ở nước ngoài, và VM AI đặt tại Singapore.
   - Nếu hồ sơ KYC phải nằm hoàn toàn tại Úc, hãy chạy intake trên máy AI tại Úc (T4 ở Sydney, hoặc nhà cung cấp GPU của Úc).
5. **Vận hành:**
   - Pin tag image (`vllm`, `litellm`).
   - Bật Cloud Monitoring alert.
   - Diễn tập khôi phục từ snapshot.

## Issuance Studio (single-host deployment, 2026-09)

Controls added after the internal security review (all verified on the live site):

| Area | Control |
|---|---|
| Keys | Only the `issuer` container holds keys (`/opt/blockid/keys`, read-only, uid 10001). It is on internal networks `issuer` (agents-api only) and `issuer-backend` (postgres, evmd) plus an egress-only network; `agents-worker`, which processes untrusted websites, cannot reach it and does not receive `ISSUER_INTERNAL_TOKEN` (`/opt/blockid/issuer.env`). |
| Approvals | Company issue/anchor and mint/dividend execution are claimed atomically from admin-approved states; retries check on-chain results first. |
| Auth | SIWE (EIP-4361, single-use nonces, domain/URI/chain checks) or admin password (bcrypt, lockout keyed by real client IP via Cloudflare `CF-Connecting-IP`). Cookie `__Host-bid_session` (HttpOnly, Secure, SameSite=Lax). |
| CSRF | Origin/Referer allowlist (`ALLOWED_ORIGINS`) on every state-changing request. |
| SSRF | All crawling goes through `tools/safefetch.py`: public addresses only, redirects re-checked per hop, DNS pinned to the validated IP, 2 MB and 20 s per page, 120 s per crawl, robots.txt respected. |
| Abuse | Valuations: 3/wallet/day, 60/day globally, max 5 active. |
| Public RPC | `/rpc` goes through `POST /v1/rpc` (eth_/net_/web3_ only). `/cometbft/` only exposes read routes. |
| Web | CSP (self + hashed inline bootstrap, Google Fonts, Hoodi RPC), X-Frame-Options DENY, HSTS, nosniff; API docs disabled in production. |

Known testnet-only choices: admin/admin password kept at the owner's request (change it before any real use); the issuer
key is a hot key on the server (production must move issuance to a Safe multisig — see above).
