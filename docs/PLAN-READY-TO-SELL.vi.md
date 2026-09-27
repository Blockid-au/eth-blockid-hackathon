# BlockID sẵn sàng bán hàng — tóm tắt cho chủ sở hữu (28/09/2026)

Kế hoạch đã được duyệt ngày 28/09/2026. Các file chi tiết (tiếng Anh):

| File | Nội dung |
|---|---|
| `PLAN-BILLING.md` | Thanh toán |
| `STRIPE-SETUP.md` / `STRIPE-SETUP.vi.md` | Hướng dẫn cấu hình Stripe |
| `PLAN-REVENUE-MODEL.md` | Mô hình doanh thu dài hạn |
| `SELF-VALUATION.md` | Case BlockID tự định giá |
| `TEAM.md` | Đội ngũ |
| `GATES.md` | Các cổng chuyển giai đoạn |

## 1. Quyết định đã chốt

- **Pháp nhân:** lập **BlockID Pty Ltd**, cổ phần Long 80% và Tuấn 20% (co-founder). Auschain cấp phép nhãn hiệu BlockID™ và IP cho công ty mới.
- **Thời điểm thu tiền:** sau khi cuộc thi EAG **công bố kết quả**, cộng thêm 7 ngày. Mục tiêu là 01/11/2026 nếu có kết quả trước 25/10.
  - Cuộc thi kết thúc 01/10/2026 00:00 UTC và chưa công bố ngày có kết quả.
  - Luồng demo, báo cáo mẫu, tài khoản giám khảo và case tự định giá luôn miễn phí.
- **Dùng thử:**
  - Mọi gói thuê bao được **dùng thử 7 ngày**, kèm 1 báo cáo miễn phí.
  - **Bắt buộc nhập thẻ.** Ngày thứ 8 tự động trừ tiền.
  - Hệ thống nhắc qua email 3 ngày trước khi hết dùng thử.
  - **Huỷ bằng 1 click** trong trang tài khoản hoặc cổng Stripe. Huỷ trong lúc dùng thử thì không bị trừ tiền.
  - Báo cáo lẻ trả tiền ngay khi mua.
- **Bảng giá v1:**
  - Báo cáo ứng viên A$49
  - Passport check A$59
  - Báo cáo đội ngũ A$199
  - Định giá A$299, bản có chuyên gia duyệt A$890
  - Gói Founder A$49/tháng, Growth A$149/tháng, nhóm Angel A$199/tháng, Recruiter A$299/tháng
  - Bảng giá nằm trong code và **tự đồng bộ lên Stripe** theo lookup key. Muốn đổi giá chỉ cần sửa file rồi sync lại.

## 2. Cơ chế bán hàng B2B và B2C do nhà đầu tư dẫn dắt

- **Nhà đầu tư** dùng miễn phí (B2C).
- **Nhóm angel hoặc quỹ** mua gói nhóm (B2B): 3 suất Founder được tài trợ và 10 lượt kiểm tra mỗi tháng.
- Nhà đầu tư **mời các startup trong danh mục** của họ. Startup cần passport, định giá, sổ cổ đông và cập nhật cho nhà đầu tư, nên sẽ trả tiền hoặc dùng suất được tài trợ.
  - Startup được mời có 14 ngày dùng thử.
  - Nhà đầu tư theo dõi qua trang danh mục (portfolio).
- Founder lại mời cổ đông của mình vào cổng nhà đầu tư. Mạng lưới nhà đầu tư lớn dần, tạo thành vòng lặp.
- Mọi lời mời đều được ghi nhận để biết doanh thu đến từ nhà đầu tư nào.
- **Kênh tìm khách đầu tiên** (hiện chưa có khách VBC):
  - Cộng đồng Fintech Australia, Blockchain Australia, Sydney Ethereum, Stone & Chalk
  - Các cuộc thi và hackathon
  - Accelerator: Startmate, Antler, Blackbird Giants
  - Nhóm angel: Sydney Angels, Scale Investors
  - Mục tiêu: 4 sự kiện mỗi tháng, 20 cuộc trò chuyện mỗi sự kiện.

## 3. BlockID tự định giá — case thật đầu tiên

- Chạy đúng quy trình và tiêu chí chấm điểm của app. Kết quả **giữ nguyên như máy tính ra**.
  - Dự kiến BlockID ở giai đoạn pre-seed, độ tin cậy thấp đến trung bình, vì chưa có doanh thu và chưa gọi vốn.
- Người duyệt phải **độc lập**, không phải Long hay Tuấn. Xung đột lợi ích được ghi rõ trong báo cáo.
- Trang chủ có thẻ "Chúng tôi tự định giá mình trước". 14 công ty còn lại được gắn nhãn "Sample listing".
- Sau khi BlockID Pty Ltd được đăng ký: phát hành token cổ phần BLKID cho Long và Tuấn trên BlockID EVM, neo lên Hoodi và HSK. Đây là ghi nhận cổ phần hiện có, không phải chào bán.
- **Cần bạn cung cấp:**
  - Số vốn đã góp, tiền mặt hiện có, chi phí hàng tháng
  - Số waitlist, LOI hoặc pilot (ghi đúng thực tế, 0 cũng được)
  - Nội dung LinkedIn hoặc CV của Long và Tuấn (vì LinkedIn chặn đọc tự động)
  - Ví của một người duyệt độc lập

## 4. Mô hình thu phí dài hạn (đề xuất)

| Tầng | Nội dung | Khi nào |
|---|---|---|
| 1 | Báo cáo tính theo lượt | Ngay sau cuộc thi |
| 2 | Gói thuê bao | Ngay sau cuộc thi |
| 3 | Quản lý sổ cổ đông: A$2/cổ đông/năm, quản trị cổ tức | Ngay sau cuộc thi |
| 4 | Phí giao dịch: phát hành, chuyển nhượng, % cổ tức, phí gọi vốn thành công | Sau 9/4/2027, qua đối tác có giấy phép và sau audit |
| 5 | White label | Năm 2027 |
| 6 | Venture Track (lấy cổ phần, tuỳ chọn) | Chọn lọc từng deal |

**Lấy 5% cổ phần của mọi công ty — không nên làm mặc định**, vì:
- Kém cạnh tranh: Startmate lấy 7% nhưng đổi lại A$120k tiền mặt.
- Phải đóng thuế trên giá trị cổ phần nhận được dù chưa có tiền mặt.
- Xung đột với vai trò định giá độc lập.
- Rủi ro cần giấy phép AFSL.
- Cổ phần khó bán, và công ty Pty bị giới hạn 50 cổ đông.

Thay vào đó, đề xuất **Venture Track**:
- Tối đa 5 deal mỗi năm, áp dụng cho startup mà BlockID/Auschain xây nền tảng blockchain cho họ.
- Lấy 1–3% qua warrant hoặc SAFE, kèm phí tiền mặt thấp hơn.
- Công khai trên passport của startup đó.
- Việc gọi vốn hoặc niêm yết chỉ làm qua đối tác có giấy phép.

## 5. Chuyển lên mainnet phí gas thấp

- **Điều kiện trước khi chuyển:**
  - Audit hợp đồng thông minh
  - Ví Safe 2-of-3 làm admin (hiện một hot key giữ mọi quyền)
  - Có đối tác AFSL hoặc tokenised custody
  - Quyết định có dùng chuẩn ERC-3643 hay không
- **Thời điểm:** sớm nhất quý 2–3/2027.
- **Chain ứng viên:** Base hoặc HashKey Chain mainnet. Cả hai đều chạy được cùng bộ hợp đồng hiện tại; Ethereum mainnet chỉ dùng để neo dữ liệu.
- **Cách chuyển:**
  1. Chụp snapshot sổ cổ đông.
  2. Phát hành lại token cho từng cổ đông trên chain mới, kèm tham chiếu tới snapshot.
  3. Tạm dừng token cũ và neo root cuối cùng.
  4. Kiểm tra lại qua trang `/verify`.
- **Phí:** lúc đầu thu ngoài chuỗi qua Stripe. Chỉ đưa lên on-chain sau khi có ý kiến pháp lý và audit mới.

## 6. Tiến độ triển khai

1. **Hôm nay:** hoàn tất tài liệu và hướng dẫn Stripe.
2. **Đang làm song song:** backend billing (Stripe, dùng thử, credits, webhook, lời mời) và web (trang /pricing, trang tài khoản billing, tab Revenue cho admin, nhãn "mẫu/thật"). Mọi thứ nằm sau cờ `BILLING_ENABLED=0`, nên **không ảnh hưởng tới cuộc thi**.
3. Chạy thử toàn bộ bằng Stripe test mode → review bảo mật → merge.
4. **Việc của chủ sở hữu:** mở Stripe (test), đăng ký BlockID Pty Ltd, cung cấp dữ liệu cho case tự định giá, rồi ghi kết quả cuộc thi vào `GATES.md`.
5. Bật live ở mốc G0 + 7 ngày.
