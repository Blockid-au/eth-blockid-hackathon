# Kế hoạch kinh doanh thực, theo dõi người dùng và thu phí — tóm tắt cho chủ sở hữu (2026-09-27)

Bản đầy đủ (tiếng Anh): `docs/PLAN-BUSINESS.md`. **Đây là kế hoạch, chưa code, chưa deploy.**
Mọi mức giá đều là giả thuyết để kiểm chứng. 14 công ty trên site là dữ liệu mẫu, hiện chưa có người dùng thật.

## 1. Kết quả review dự án

**Sản phẩm đã có thể bán:** báo cáo đánh giá/định giá doanh nghiệp, báo cáo HR/CV (hr.blockid.au), sổ cổ đông +
cập nhật cho nhà đầu tư, cổng nhà đầu tư. Chuyển nhượng, cổ tức, chào bán vẫn chỉ chạy trên testnet (chào bán là mô phỏng).

**Theo dõi người dùng hiện tại còn thiếu:**
- Không có bảng user chung. Một người đăng nhập bằng ví, khách, Google hay demo sẽ thành nhiều "người" khác nhau.
- Đăng nhập bằng ví thường, khách và demo không được ghi audit. Session bị xoá sau 45 ngày.
- Không có số "đang online", không có lịch sử thao tác từng người, không có phễu chuyển đổi và tỷ lệ quay lại.
- Không phân biệt người thật với demo/nội bộ/mẫu, nên chưa báo cáo trung thực được "bao nhiêu người dùng thật".
- Chi phí AI chỉ cộng tổng, không tính được theo từng khách hàng.

**Phải sửa trước khi thu tiền:**
1. Bỏ `admin/admin`. Hiện ai cũng vào được quyền admin.
2. Sao lưu database, vì hiện chưa có backup nào.
3. Tách key của issuer khỏi file mật khẩu trên cùng máy.
4. Tách môi trường demo khỏi production.
5. Thêm trang Điều khoản, Chính sách riêng tư và thông báo cookie.
6. Tự động xoá CV sau N ngày.
7. Chuyển Claude bridge (đang chạy bằng gói subscription cá nhân) sang API trả theo lượng dùng.
8. Thêm kiểm tra uptime từ bên ngoài và cấu hình SMTP.
9. Bổ sung CI.

## 2. Các giai đoạn và cổng chấm điểm

Mỗi lần chuyển giai đoạn đều phải chấm điểm và ghi vào `docs/GATES.md` (ngày, điểm, bằng chứng, quyết định, người duyệt).

| Giai đoạn | Nội dung | Tiền | Kết thúc bằng cổng |
|---|---|---|---|
| S0 Hackathon (hiện tại) | Demo cho giám khảo | 0 | **G0: có kết quả chấm, trả lại giới hạn thường, chụp số liệu nền** |
| S1 Nền tảng (~4 tuần) | Tracking, bảo mật, pháp lý, tách demo | 0 | **G1: sẵn sàng đón người dùng thật** (11 tiêu chí) |
| S2 Pilot miễn phí (8–12 tuần) | 10–20 công ty thật và recruiter; tính "hoá đơn ảo"; phỏng vấn mức sẵn lòng trả | chưa thu | **G2: sẵn sàng thu phí** |
| S3 Beta trả phí (~3 tháng) | Bật Stripe cho HR và gói founder; ký LOI white label | subscription + theo lượt | **G3: sẵn sàng mở rộng** |
| S4 Mở rộng / white label | Multi-tenant; phí giao dịch chứng khoán chỉ thu qua đối tác có AFSL | đầy đủ | xét hàng quý |

Cổng G2 tính trên người dùng thật và cần đạt các chỉ tiêu sau:
- ≥ 10 công ty pilot
- MAU ≥ 50
- Kích hoạt ≥ 40%
- Giữ chân tuần 4 ≥ 25%
- ≥ 5 người nói sẽ trả tiền
- Doanh thu ảo ≥ A$1.500/tháng
- Biết chi phí trên mỗi khách

Mỗi dòng chấm 0/1/2 điểm, đạt khi tổng ≥ 80%.

## 3. Tính năng tracking và báo cáo admin (làm ở S1, khoảng 2 tuần)

**Bảng mới:**
- `users` gồm cờ phân loại người thật / nội bộ / demo / test / giám khảo và vai trò (founder, nhà đầu tư, recruiter).
- `user_identities` để gộp ví, khách, Google, mật khẩu về một người.
- `auth_events` ghi mọi lần đăng nhập, kể cả đăng nhập lỗi.
- `events` ghi thao tác.
- `usage_ledger` ghi từng đơn vị tính phí kèm chi phí AI.
- `daily_metrics` lưu số liệu tổng hợp.

**Ghi nhận:**
- Phía server ghi mọi thao tác quan trọng. Đây là nguồn dữ liệu chuẩn để tính tiền.
- Phía trình duyệt ghi lượt xem trang và nút bấm, và gửi heartbeat mỗi 60 giây để đếm số người **đang online** (trong 5 phút gần nhất).
- Dữ liệu chỉ lưu trong Postgres của mình, không dùng tracker bên thứ ba. Không lưu IP thô và không ghi nội dung CV.

**Trang `/admin/analytics`** (mặc định chỉ hiện **người dùng thật**) có các tab:
- Tổng quan: online, DAU/WAU/MAU
- Danh sách người dùng và timeline từng người
- Phễu chuyển đổi
- Cohort giữ chân
- Mức dùng theo tính năng
- Theo công ty (chi phí AI, doanh thu ảo)
- Doanh thu
- Xuất CSV
- **Báo cáo "người dùng thật" hàng tháng**, gửi qua email và dùng được cho nhà đầu tư

## 4. Cơ chế thu phí (giả thuyết, AUD, chưa gồm GST)

Cách làm: **đo trước, tính giá ảo, rồi mới thu.** Bảng giá có phiên bản và áp lên sổ usage để ra hoá đơn ảo trong pilot. Khi qua G2 thì bật chính bảng giá đó trên Stripe.

- **Nhà đầu tư:** miễn phí, vì họ là mạng lưới. Gói Pro khoảng A$15/tháng sẽ tính sau.
- **Founder** (subscription cộng phí theo lượt vượt hạn mức):

  | Gói | Giá/tháng | Bao gồm | Vượt hạn mức |
  |---|---|---|---|
  | Free | A$0 | 1 báo cáo/tháng, sổ cổ đông ≤ 10 người | — |
  | Starter | A$49 | 3 báo cáo, sổ cổ đông ≤ 50 người, cập nhật cho nhà đầu tư | A$19/báo cáo |
  | Growth | A$199 | Báo cáo không giới hạn, 1 định giá chốt/quý | A$99/lần định giá chốt |
  | Scale | A$499 | Nhiều công ty, API | tuỳ thoả thuận |

- **HR:** A$19/báo cáo người, A$9/phân tích CV, gói 20 báo cáo A$299, gói Team A$149/tháng. Đây là **nguồn thu nhanh nhất và không vướng luật chứng khoán**.
- **Phí giao dịch** (chỉ thu ở S4, khi đã có đối tác AFSL/CSF):
  - Phát hành cổ phần: A$490/đợt
  - Chuyển nhượng: A$15–25/lần
  - Cổ tức: 0,5–1%, tối đa A$2.000
  - Chào bán thành công: 1–3%, chia với đơn vị được cấp phép
  - KYC: giá gốc + 30%
- **White label** (cho accelerator, sàn gọi vốn cộng đồng, công ty kế toán/luật, công ty chứng khoán VN):
  - Setup A$5–15k
  - A$1.500–5.000/tháng
  - Phí theo lượng dùng
  - Chia 20–30% phí giao dịch trên tenant của đối tác

**Tích hợp thanh toán (xây ở S2, bật khi qua G2):**
- Dùng Stripe dưới tên Auschain Pty Ltd, tính bằng AUD: Billing, Meters cho phí theo lượt, Checkout, Customer Portal, Stripe Tax cho GST 10%, hoá đơn chuyển khoản cho đối tác white label.
- Có lớp trừu tượng `billing/provider.py` để sau này thêm PayOS, VNPay, MoMo (VND) hoặc stablecoin.
- Webhook được xác thực chữ ký và idempotent. Khi thanh toán lỗi, cho gia hạn 7 ngày rồi hạ về Free; dữ liệu vẫn giữ.
- **Không giữ tiền đầu tư của khách.** Tiền đầu tư đi qua đơn vị được cấp phép hoặc escrow.

## 5. Đối tượng khách hàng theo thứ tự

1. Recruiter và founder đang tuyển người (HR).
2. Founder/SME ở Úc giai đoạn pre-seed đến Series A, tiếp cận **qua accelerator và nhóm angel**.
3. Nhà đầu tư: miễn phí, được công ty mời vào.
4. Đối tác white label.
5. Các dòng giao dịch chứng khoán: chỉ làm cùng đối tác có giấy phép.

Ở Việt Nam chỉ bán phần mềm và HR, vì Nghị quyết 05/2025 loại trừ token gắn với chứng khoán.

Doanh thu mục tiêu sau G2 (sẽ thay bằng số liệu pilot):

| Thời điểm | MRR mục tiêu |
|---|---|
| Tháng 3 | ~A$3,5k |
| Tháng 6 | ~A$11k (có 1 white label) |
| Tháng 12 | ~A$35k |

## 5b. Pháp nhân vận hành

Pháp nhân vận hành là **Auschain Pty Ltd**: ABN 79 659 615 111, ACN 659 615 111, đăng ký GST từ 26/03/2025, trụ sở NSW. Công ty đang dùng BlockID™ như nhãn hiệu **chưa đăng ký**: chỉ dùng ™, không dùng ® cho tới khi đăng ký xong. Hồ sơ đầy đủ nằm ở `docs/COMPANY.md`, gồm:
- Thông tin đã xác minh trên ABR
- Chân trang pháp lý EN/VI
- Quy tắc hoá đơn GST
- Danh sách 15 thông tin còn thiếu (số TM, trích lục ASIC, business name, ngân hàng, bảo hiểm, luật sư, thoả thuận IP với Vietnam Blockchain Corporation, R&D Tax Incentive hạn 30/04/2027...)

## 6. Lộ trình

| Khi nào | Việc |
|---|---|
| Từ nay đến khi có kết quả chấm | Giữ demo ổn định, ghi kết quả, duyệt kế hoạch này |
| G0 + 0–2 tuần | Tracking, định danh, admin analytics; bỏ admin/admin; backup |
| G0 + 2–4 tuần | Pháp lý; tách demo; API AI trả theo lượt; uptime + SMTP; xoá CV tự động; sổ usage; bảng giá v0 → **chấm G1** |
| G1 + 0–12 tuần | Pilot, hoá đơn ảo, phỏng vấn, trang /pricing, Stripe chạy chế độ test, memo pháp lý, chọn nhà cung cấp KYC → **chấm G2** |
| G2 + 0–3 tháng | Bật Stripe, báo cáo người dùng thật hàng tháng, thiết kế tenant, LOI white label, đàm phán đối tác AFSL → **chấm G3** |
| Sau G3 | White label theo domain, phí giao dịch qua đối tác, lộ trình mainnet (Safe multisig, validator, ERC-3643, audit) trước ngày 9/4/2027 |

## 7. Cần chủ sở hữu quyết định

1. Tracking tự lưu trong Postgres (đề xuất) hay dùng PostHog/Plausible?
2. Sản phẩm thu tiền đầu tiên là HR + gói founder (đề xuất) hay chờ phí giao dịch?
3. Có chấp nhận bảng giá giả thuyết ở mục 4 để thử trong pilot không?
4. Đã rõ về GST: Auschain Pty Ltd đăng ký GST từ 26/03/2025. Còn cần quyết định: mở Stripe đứng tên Auschain, đăng ký business name BLOCKID, và bổ sung các mục còn thiếu ở `docs/COMPANY.md` §6.
5. Demo có chuyển sang demo.blockid.au không (đề xuất là chuyển)?
6. Ai chấm các cổng, và kết quả công bố ở đâu?
