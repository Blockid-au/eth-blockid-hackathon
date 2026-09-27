/** Input checks shown where the value is typed (fixes batch 1): addresses, keys, transfers, company admins, admin
 * password, shareholder rows. Plain words. The server enforces the same rules. VI must cover every EN key. */
export const fx1En = {
  // addresses (wallet.ts addressProblem)
  "fx.addr.format": "Not a wallet address: it starts with 0x followed by 40 letters and digits.",
  "fx.addr.checksum": "Checksum mismatch — check for a typo. Paste the address again, or type it all in lowercase.",
  "fx.addr.zero": "The zero address (0x000…0) is not a wallet.",
  "fx.addr.need": "Enter the receiver's wallet address.",

  // private key restore (devicewallet.ts)
  "fx.key.seed": "Seed phrases (12 or 24 words) are not supported here — paste the 64-character private key instead.",
  "fx.key.format": "This is not a private key: paste 64 characters (0-9 and a-f), with or without 0x in front.",
  "fx.key.range": "This key is not usable (it is zero or too large). Check that you copied the whole key.",
  "fx.key.confirm": "This browser already holds wallet {a}. Confirm to replace it with wallet {b}.",
  "fx.key.replace": "This browser already holds a different wallet: {a}. Restoring replaces it with wallet {b}.",
  "fx.key.backupFirst": "Back up the current key first: without it, wallet {a} cannot be used again from this browser.",
  "fx.key.showOld": "Show the current key",
  "fx.key.replaceBtn": "Replace it and sign in",

  // Google sign-in
  "fx.g.taken": "This browser's key already belongs to another account. Sign out of that account, or use another browser.",
  "fx.g.newkey": "This browser has a new key. Restore your backup to use your wallet {a}.",
  "fx.g.restore": "Restore my backup",
  "fx.g.keepNew": "Continue with the new wallet",

  // transfers
  "fx.tr.whole": "Whole shares only (no decimals, signs or spaces).",
  "fx.tr.sharesNeed": "Enter how many shares to send (at least 1).",
  "fx.tr.max": "You hold {n} shares; you cannot send more.",
  "fx.tr.self": "This is your own wallet. Enter the receiver's wallet.",
  "fx.tr.nameNeed": "Enter the receiver's name.",
  "fx.tr.pending": "Transaction {h} was sent ({n} shares to {a}) but is not recorded yet. Record it before starting a new transfer.",
  "fx.tr.recordBtn": "Record transaction {h}",
  "fx.tr.waitingBtn": "Still waiting…",
  "fx.tr.stillWaiting": "Transaction {h} is not confirmed yet. Do not send it again: wait a little and press \"Record transaction\".",
  "fx.tr.reverted": "Transaction {h} failed on chain; no shares moved. You can start a new transfer.",
  "fx.tr.recordFail": "The transaction went through, but recording it failed: {e}. Do not send it again: press \"Record transaction\" to retry.",
  "fx.tr.blocked": "Cannot be approved now: {r}",
  "fx.r.self": "Sender and receiver are the same wallet",
  "fx.r.balance": "Not enough shares (pending requests included)",
  "fx.r.frozen": "A wallet in this transfer is frozen by the transfer agent",
  "fx.r.lockup": "The lock-up period is still active",
  "fx.r.not_verified": "The sender or the receiver is not KYC-verified",
  "fx.r.cap": "The company has reached its maximum number of shareholders",

  // company admins
  "fx.ca.update": "Update",
  "fx.ca.listed": "This wallet is already an admin ({r}). Saving updates it.",
  "fx.ca.willChange": "Its role will change from {from} to {to}.",
  "fx.ca.updated": "{a} updated.",
  "fx.ca.roleChanged": "{a}: role changed from {from} to {to}.",
  "fx.ca.self": "This is your own wallet: you will lose access to this company's admin tools.",

  // admin password
  "fx.pw.spaces": "The password cannot be only spaces.",
  "fx.pw.long": "Too long: {n} bytes, at most 72 (about 72 plain letters or digits).",
  "fx.pw.same": "The new password must differ from the current one.",
  "fx.pw.cur": "Enter your current password.",

  // shareholder rows
  "fx.sh.dec": "Use at most 2 decimals (for example 33.33).",
  "fx.sh.pctNeed": "Enter a percentage above 0.",
  "fx.sh.pctMax": "At most 100%.",
  "fx.sh.supply": "Enter a whole number of shares (at least 1).",
  "fx.sh.few": "There must be at least one share per holder ({n} holders).",
  "fx.sh.zero": "This holder would get 0 of the {n} shares. Raise the number of shares or the percentage.",
};

export const fx1Vi: Record<keyof typeof fx1En, string> = {
  "fx.addr.format": "Không phải địa chỉ ví: địa chỉ bắt đầu bằng 0x và theo sau là 40 chữ cái và chữ số.",
  "fx.addr.checksum": "Sai checksum — hãy kiểm tra lỗi gõ. Dán lại địa chỉ, hoặc gõ toàn bộ bằng chữ thường.",
  "fx.addr.zero": "Địa chỉ số không (0x000…0) không phải là ví.",
  "fx.addr.need": "Nhập địa chỉ ví người nhận.",

  "fx.key.seed": "Không hỗ trợ cụm từ khôi phục (12 hoặc 24 từ) — hãy dán khoá riêng gồm 64 ký tự.",
  "fx.key.format": "Đây không phải khoá riêng: hãy dán 64 ký tự (0-9 và a-f), có hoặc không có 0x ở đầu.",
  "fx.key.range": "Khoá này không dùng được (bằng 0 hoặc quá lớn). Hãy kiểm tra bạn đã chép đủ cả khoá.",
  "fx.key.confirm": "Trình duyệt này đang giữ ví {a}. Hãy xác nhận để thay bằng ví {b}.",
  "fx.key.replace": "Trình duyệt này đang giữ một ví khác: {a}. Khôi phục sẽ thay ví đó bằng ví {b}.",
  "fx.key.backupFirst": "Hãy sao lưu khoá hiện tại trước: nếu không, ví {a} sẽ không dùng lại được từ trình duyệt này.",
  "fx.key.showOld": "Hiện khoá hiện tại",
  "fx.key.replaceBtn": "Thay và đăng nhập",

  "fx.g.taken": "Khoá của trình duyệt này đã thuộc về một tài khoản khác. Hãy đăng xuất tài khoản đó, hoặc dùng trình duyệt khác.",
  "fx.g.newkey": "Trình duyệt này có một khoá mới. Hãy khôi phục bản sao lưu để dùng ví {a} của bạn.",
  "fx.g.restore": "Khôi phục bản sao lưu",
  "fx.g.keepNew": "Tiếp tục với ví mới",

  "fx.tr.whole": "Chỉ nhập số cổ phần nguyên (không số thập phân, dấu hay khoảng trắng).",
  "fx.tr.sharesNeed": "Nhập số cổ phần muốn chuyển (ít nhất 1).",
  "fx.tr.max": "Bạn đang nắm {n} cổ phần; không thể chuyển nhiều hơn.",
  "fx.tr.self": "Đây là ví của chính bạn. Hãy nhập ví người nhận.",
  "fx.tr.nameNeed": "Nhập tên người nhận.",
  "fx.tr.pending": "Giao dịch {h} đã được gửi ({n} cổ phần tới {a}) nhưng chưa được ghi nhận. Hãy ghi nhận trước khi bắt đầu lệnh chuyển mới.",
  "fx.tr.recordBtn": "Ghi nhận giao dịch {h}",
  "fx.tr.waitingBtn": "Vẫn đang chờ…",
  "fx.tr.stillWaiting": "Giao dịch {h} chưa được xác nhận. Đừng gửi lại: chờ một chút rồi bấm \"Ghi nhận giao dịch\".",
  "fx.tr.reverted": "Giao dịch {h} thất bại trên chuỗi; không cổ phần nào được chuyển. Bạn có thể bắt đầu lệnh chuyển mới.",
  "fx.tr.recordFail": "Giao dịch đã thành công nhưng ghi nhận bị lỗi: {e}. Đừng gửi lại: bấm \"Ghi nhận giao dịch\" để thử lại.",
  "fx.tr.blocked": "Chưa thể duyệt lúc này: {r}",
  "fx.r.self": "Người gửi và người nhận trùng ví",
  "fx.r.balance": "Không đủ cổ phần (tính cả các yêu cầu đang chờ)",
  "fx.r.frozen": "Một ví trong lệnh chuyển này đang bị transfer agent đóng băng",
  "fx.r.lockup": "Vẫn đang trong thời gian khoá chuyển nhượng",
  "fx.r.not_verified": "Người gửi hoặc người nhận chưa được KYC",
  "fx.r.cap": "Doanh nghiệp đã đạt số cổ đông tối đa",

  "fx.ca.update": "Cập nhật",
  "fx.ca.listed": "Ví này đã là admin ({r}). Lưu sẽ cập nhật ví này.",
  "fx.ca.willChange": "Vai trò sẽ đổi từ {from} sang {to}.",
  "fx.ca.updated": "Đã cập nhật {a}.",
  "fx.ca.roleChanged": "{a}: vai trò đã đổi từ {from} sang {to}.",
  "fx.ca.self": "Đây là ví của chính bạn: bạn sẽ mất quyền dùng công cụ quản trị của doanh nghiệp này.",

  "fx.pw.spaces": "Mật khẩu không thể chỉ gồm khoảng trắng.",
  "fx.pw.long": "Quá dài: {n} byte, tối đa 72 (khoảng 72 chữ cái hoặc chữ số thường).",
  "fx.pw.same": "Mật khẩu mới phải khác mật khẩu hiện tại.",
  "fx.pw.cur": "Nhập mật khẩu hiện tại.",

  "fx.sh.dec": "Dùng tối đa 2 chữ số thập phân (ví dụ 33.33).",
  "fx.sh.pctNeed": "Nhập tỷ lệ lớn hơn 0.",
  "fx.sh.pctMax": "Tối đa 100%.",
  "fx.sh.supply": "Nhập số cổ phần là số nguyên (ít nhất 1).",
  "fx.sh.few": "Mỗi cổ đông cần ít nhất một cổ phần ({n} cổ đông).",
  "fx.sh.zero": "Cổ đông này sẽ nhận 0 trong {n} cổ phần. Hãy tăng số cổ phần hoặc tỷ lệ.",
};
