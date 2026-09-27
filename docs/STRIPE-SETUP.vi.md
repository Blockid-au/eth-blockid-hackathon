# Hướng dẫn kết nối Stripe cho BlockID — checklist cho chủ sở hữu

Bản đầy đủ (tiếng Anh, có lệnh cụ thể): `docs/STRIPE-SETUP.md`. Bảng giá nằm trong repo, tại file
`agents/src/blockid_agents/billing/pricebook/v1.yaml`. **Không nhập giá tay trên Stripe.** Script đồng bộ sẽ tự tạo và cập nhật giá.

**Khi nào bắt đầu thu tiền:** sau khi cuộc thi EAG công bố kết quả và kết quả đã được ghi vào `docs/GATES.md`, cộng thêm 7 ngày.
Trước thời điểm đó chỉ dùng **test mode**. Các luồng dành cho giám khảo, demo, báo cáo mẫu và case tự định giá không bao giờ bị thu tiền.

## 1. Tài khoản
- [ ] Đăng ký Stripe bằng admin@blockid.au. Loại hình: **Company**.
  - Hiện tại đứng tên **AUSCHAIN PTY LTD** (ABN 79 659 615 111, ACN 659 615 111).
  - Khi đã có **BlockID Pty Ltd**, mở một tài khoản Stripe thứ hai cho công ty mới và chuyển khách sang khi gia hạn.
- [ ] Khai báo giám đốc/chủ sở hữu (Long, Tuấn), tài khoản ngân hàng AUD đứng tên công ty.
- [ ] Mô tả trên sao kê: `BLOCKID.AU`. Email hỗ trợ: info@blockid.au. Logo BlockID™.

## 2. Thuế
- [ ] Bật **Stripe Tax**, thêm đăng ký **GST Úc** (Auschain đăng ký GST từ 26/03/2025).
- [ ] Không cần chỉnh gì thêm cho từng giá: báo cáo lẻ là giá **đã gồm GST**, gói thuê bao là giá **+GST**. Script tự đặt đúng.

## 3. Cài đặt billing
- [ ] Bật các email gửi khách: biên lai, **nhắc trước khi hết dùng thử** (bắt buộc theo luật thẻ), sắp gia hạn, thẻ hết hạn, thanh toán lỗi.
- [ ] Bật Smart Retries. Khi thử lại hết lần mà vẫn lỗi thì huỷ gói (app còn cho gia hạn thêm 7 ngày).
- [ ] **Customer Portal** (nơi khách tự huỷ gói):
  - Cho phép huỷ vào cuối kỳ, đổi gói, đổi thẻ, xem hoá đơn.
  - Nếu khách đang dùng thử mà huỷ, app huỷ ngay và **không trừ tiền**.
- [ ] Luật Úc từ 1/7/2027 cấm "bẫy thuê bao". Mình tuân thủ ngay từ đầu: huỷ bằng 1 click, dễ như lúc đăng ký.

## 4. Khoá API và webhook
- [ ] Tạo **restricted key** tên "blockid-app" (test trước, live sau). Quyền cần cấp:
  - **Ghi:** Products, Prices, Coupons, Promotion codes, Customers, Checkout, Subscriptions, Customer portal.
  - **Đọc:** Events, Invoices, Refunds.
- [ ] Tạo webhook `https://eth.blockid.au/api/v1/billing/webhook` với 8 sự kiện:
  - `checkout.session.completed`
  - `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `customer.subscription.trial_will_end`
  - `invoice.paid`, `invoice.payment_failed`
  - `charge.refunded`
- [ ] Ghi khoá vào `/opt/blockid/app.env` trên server (không đưa vào git, không dán vào chat): `BILLING_ENABLED`, `STRIPE_MODE`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PUBLISHABLE_KEY`, `BILLING_START_AT` (để trống thì chưa thu tiền). Sau đó khởi động lại `agents-api`. Lệnh cụ thể ở mục 4 bản tiếng Anh.

## 5. Tạo sản phẩm và giá
- [ ] Vào Admin → **Revenue** → **Sync prices**. Bấm "chạy thử" để xem thay đổi, rồi bấm **Apply**. Hoặc chạy lệnh `python -m blockid_agents.billing.sync --apply`.
- [ ] Mã giảm giá được tạo tự động:
  - `FOUNDING30`: giảm 30% trọn đời cho 50 khách đầu tiên.
  - `PULLEY6`: miễn phí 6 tháng cho khách chuyển từ Pulley.
- [ ] Muốn đổi giá: sửa file bảng giá → deploy → sync lại. Trang /pricing tự cập nhật theo.

## 6. Thử toàn bộ luồng bằng test mode
- [ ] Mua 1 báo cáo bằng thẻ `4242 4242 4242 4242` → nhận biên lai và 1 lượt báo cáo.
- [ ] Đăng ký gói Founder → được dùng thử 7 ngày và 1 báo cáo miễn phí.
- [ ] Nhận email nhắc 3 ngày trước khi hết dùng thử.
- [ ] Dùng test clock tua nhanh 7 ngày → tự trừ tiền.
- [ ] Huỷ khi đang dùng thử → không bị trừ tiền.
- [ ] Thẻ lỗi `4000 0000 0000 0341` → có 7 ngày gia hạn, sau đó hạ về gói miễn phí.
- [ ] Dùng lại email hoặc thẻ cũ để xin dùng thử lần 2 → bị từ chối.
- [ ] Tài khoản giám khảo → dùng miễn phí.

## 7. Bật thu tiền thật
- [ ] Ghi kết quả cuộc thi vào `docs/GATES.md` và trả các giới hạn về mức thường (dùng file `app.env.bak-judging`).
- [ ] 14 ngày trước ngày bắt đầu: đặt `BILLING_START_AT` để trang /pricing hiện "Bắt đầu thu phí từ <ngày>".
- [ ] Tạo khoá live và webhook live, đặt `STRIPE_MODE=live`, rồi sync giá sang live.
- [ ] Đánh dấu tài khoản giám khảo. Thêm id của case tự định giá vào `BILLING_FREE_ALLOWLIST`.
- [ ] Theo dõi Admin → Revenue trong 72 giờ đầu. Nếu có sự cố: đặt `BILLING_ENABLED=0` là app quay về như cũ.
