# Cơ cấu cổ phần cho BlockID Business Passport — tóm tắt cho chủ sở hữu

Bản đầy đủ (tiếng Anh): `docs/EQUITY-STRUCTURE-PLAN.md`. Đây là đề xuất thiết kế, chưa code, chưa deploy.
Testnet demo. Không phải chào bán chứng khoán hay tư vấn tài chính.

## 1. Kết quả nghiên cứu — 3 mô hình mẫu

| Mô hình | Vì sao chọn | Bài học chính |
|---|---|---|
| **Facebook 2004–2012** (bản cáo bạch IPO trên SEC) + số liệu Carta/Index 2025–26 | Dữ liệu gốc đầy đủ nhất cho con đường startup gọi vốn VC | Founder ~56% sau seed, ~36% sau Series A; mỗi vòng pha loãng ~18–20%; quỹ ESOP 10–15% ở seed, ~17% về sau; vesting 4 năm, cliff 1 năm; lock-up sau IPO chia nhiều đợt; cổ phần 2 lớp (A 1 phiếu, B 10 phiếu); không trả cổ tức giai đoạn tăng trưởng |
| **Arbitrum ARB** (+ Uniswap UNI) | Công bố rõ tỷ lệ + lịch vesting có ngày cụ thể cho từng nhóm | Team ~27%, nhà đầu tư ~18%, quỹ chung/dự trữ ~35–43%; cliff 1 năm rồi mở hàng tháng 3 năm; phát hành thêm tối đa 2%/năm và phải bỏ phiếu. Sai lầm: mở khóa 87% lượng lưu hành trong 1 ngày; Foundation chuyển/bán token trước khi xin phê duyệt (AIP-1) → phải phê duyệt trước, không "hợp thức hóa" sau |
| **John Lewis Partnership** (+ Exodus/Securitize, chuẩn ERC-3643) | Mô hình doanh nghiệp do nhân viên sở hữu có báo cáo kiểm toán 2025/26 | 100% cổ phần do quỹ tín thác giữ cho ~63.800 nhân viên; thưởng lợi nhuận cùng % lương cho mọi người (2% năm 2026) thay cho cổ tức; hội đồng do nhân viên bầu. Exodus: cổ phần thật dạng token, mọi chuyển nhượng qua đại lý chuyển nhượng được cấp phép |

Luật (mức tổng quan, không phải tư vấn pháp lý):
- **Úc:** ưu đãi thuế ESS cho startup (chưa niêm yết, dưới 10 năm, doanh thu ≤ 50 triệu AUD, giữ ≥ 3 năm, giảm giá ≤ 15%). Chào bán có thu tiền bị giới hạn 30.000 AUD/người/12 tháng. Công ty Pty tối đa 50 cổ đông không phải nhân viên. Muốn trả cổ tức phải qua kiểm tra khả năng thanh toán (s254T); có franking 25%/30%.
- **Việt Nam:** ESOP của công ty đại chúng tối đa 5% cổ phần/12 tháng và phải có ĐHĐCĐ phê duyệt. Công ty cổ phần chưa đại chúng làm ESOP theo hình thức chào bán riêng lẻ (dưới 100 người). Cổ tức trả trong 6 tháng sau ĐHĐCĐ, khấu trừ 5% thuế TNCN với cá nhân. Thời hạn khóa chuyển nhượng 1 năm của ESOP **chưa được xác minh**, cần luật sư VN kiểm tra.

## 2. Hệ thống đã có (tái sử dụng)

- Token cổ phần: 1 token = 1 cổ phần, chỉ ví đã KYC mới nhận được; có đóng băng, tạm dừng và chuyển nhượng bắt buộc.
- Phát hành thêm (mint) có xem trước mức pha loãng. Chào bán mô phỏng có thời gian cân nhắc 5 ngày.
- Chính sách cổ tức tự động, trả qua Merkle bằng `claimFor` (người nhận không trả gas).
- Vai trò trong công ty: owner/manager. Hàng đợi phê duyệt của admin.
- **Thiếu:** nhiều loại cổ phần, nhóm/quỹ, cấp cổ phần có vesting, đợt phát hành, mua lại cổ phần, cổ tức theo loại, và quy tắc "bốn mắt" trong công ty. Hiện manager có thể tự tạo rồi tự duyệt mint của chính mình.

## 3. Thiết kế đề xuất

- **Kế hoạch lưu ngoài chuỗi, cổ phần ghi trên chuỗi.** Mỗi công ty có một "Cơ cấu cổ phần" có phiên bản và phải được duyệt: loại cổ phần, nhóm, % mục tiêu, hạn mức. Mã hash của tài liệu được ghi on-chain.
- **3 mẫu có sẵn** (sửa được mọi con số):

| Nhóm | Startup sớm | Tăng trưởng có VC | Doanh nghiệp nhân viên sở hữu |
|---|---|---|---|
| Sáng lập & lãnh đạo | 60% | 40% | 40% |
| HĐQT | 1% | 1% | 1% |
| Quỹ nhân viên (Kỹ thuật/Marketing/Vận hành) | 12% | 15% | 15% cấp cá nhân + 30% quỹ tín thác chung |
| Cố vấn | 1% | 1% | — |
| Nhà đầu tư seed / Series A / bên ngoài | 20% / — / — | 16% / 20% / — | — / — / 10% |
| Dự trữ (chưa phát hành) | 6% | 7% | 4% |

- **Cấp cổ phần & vesting:** hỗ trợ cliff + tuyến tính, theo mốc (milestone) và kết hợp cả hai. Mặc định **mint khi đến hạn nhận**: phần chưa nhận chỉ là cam kết lưu trong DB, đến ngày thì tạo dòng `studio.mints` và issuer mint vào ví. Cách này **không cần đổi hợp đồng**, và phần chưa nhận không nhận cổ tức.
- **Đợt phát hành:** chọn loại vòng và giá (mặc định bằng giá trị hợp lý đã duyệt). Chia cổ phần theo nhóm, xem trước pha loãng cho từng người và từng nhóm. Có thể bật quyền ưu tiên mua cho cổ đông hiện hữu, và liên kết với chào bán đã có.
- **Mỗi loại cổ phần là 1 token riêng** (theo cách của ERC-3643), mỗi token có DividendDistributor riêng. Cổ tức tính theo loại: cổ phần ưu đãi được trả trước, sau đó đến cổ phần phổ thông.
- **Mua lại cổ phần:** cần người nắm giữ đồng ý, HĐQT và admin duyệt, sau đó gọi `cancel`. Không có ví "cổ phiếu quỹ".
- **Phê duyệt:** người đề xuất và người duyệt phải là 2 ví khác nhau. Thứ tự duyệt là HĐQT (1 hoặc 2 người) rồi đến admin nền tảng. Đề xuất do trợ lý AI soạn chỉ là bản nháp và được ghi vào AgentProvenance.
- **Hợp đồng (giai đoạn sau):** token v2 có đóng băng một phần và khóa theo từng người; `VestingVault` là tùy chọn; về lâu dài chuyển sang ERC-3643 + ONCHAINID và ví đa chữ ký Safe.

## 4. Màn hình mới

- **Workspace công ty:** thêm 3 mục ★ vào thanh bên. **Cơ cấu cổ phần** gồm ô KPI, bảng nhóm, biểu đồ donut và chọn mẫu. **Đợt phát hành** gồm các bước và bảng pha loãng. **Cấp cổ phần & lộ trình nhận** gồm danh sách người, thanh % đã nhận, ngày nhận tiếp theo và ngăn chi tiết.
- **Nhà đầu tư/nhân viên** (`/i/grants`): ô "Đã nhận / Chưa nhận / Lần nhận tiếp theo", biểu đồ bậc thang, ngày hết khóa, cổ tức đã nhận, nút chấp nhận cổ phần được cấp.
- **Admin:** thêm các hàng đợi structure / rounds / grants / buybacks. Mỗi mục hiển thị phần thay đổi, bảng pha loãng, kết quả kiểm tra tự động và người đề xuất/người duyệt.
- **Chung:** song ngữ EN/VI, sáng/tối. Trên điện thoại, bảng chuyển thành thẻ, không cuộn ngang. Chữ đơn giản theo FACTS.md và luôn có dòng pháp lý.

## 5. Các giai đoạn

| GĐ | Nội dung | Công sức |
|---|---|---|
| **P0 — demo hackathon** | 3 mẫu, màn Cơ cấu (1 loại ORD), Cấp cổ phần + vesting tự mint, quy tắc bốn mắt, "Cổ phần của tôi", hàng đợi admin, dữ liệu demo CNV | 5–7 ngày |
| P1 | Đợt phát hành, xem trước pha loãng, quyền ưu tiên mua, vai trò HĐQT, hash kế hoạch on-chain | 1,5–2 tuần |
| P2 | Nhiều loại cổ phần (PREF), cổ tức theo loại, mua lại, nghỉ việc, vesting theo mốc KPI, nhập danh sách từ HR | 2–3 tuần |
| P3 | Token v2 / Vault / ERC-3643, SAFE, Safe multisig, kiểm toán, hồ sơ ESS, franking thật | 4–6 tuần + kiểm toán |

## 6. Anh cần quyết định

1. Chọn cách mint: mint khi đến hạn nhận (khuyến nghị) hay mint trước rồi khóa?
2. Duyệt 3 mẫu và các con số trên? Có cần thêm mẫu "cộng đồng/khách hàng sở hữu" không?
3. Công ty nhỏ cần 1 người HĐQT + admin nền tảng là đủ, hay luôn cần 2 người trong công ty duyệt?
4. Demo hackathon chỉ dùng ORD (khuyến nghị) hay trình diễn thêm PREF-A?
5. Cổ phần nhân viên dùng chung loại ORD hay tạo loại không biểu quyết (NV-EMP)?
6. Quyền ưu tiên mua mặc định bật hay tắt?
7. Khóa cổ phần nhân viên sau khi nhận: 0, 12 tháng hay 3 năm (khớp ưu đãi ESS Úc)?
8. Vesting theo mốc: bằng chứng là KPI trong bản cập nhật đã công bố, hay thêm xác nhận của HĐQT?
9. Làm token v2 / ERC-3643 ở P3 như kế hoạch, hay làm sớm hơn cho công ty mới?
10. Việt Nam: thuê luật sư xác minh khóa ESOP và các sửa đổi 2024–25 trước khi hiển thị nội dung riêng cho VN?
