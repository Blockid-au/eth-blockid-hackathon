/**
 * Footer links to the legal pages (/terms, /privacy; text in pages/legal/copy.ts) and the HR "report not found" state.
 * VI must cover every EN key (checked by the type).
 */
export const legalEn = {
  "foot.terms": "Terms",
  "foot.privacy": "Privacy",
  "hr.r.nf.eyebrow": "Report not found",
  "hr.r.nf.h": "We can't find this report",
  "hr.r.nf.p": "The link may be wrong, or the report was deleted. Check the link, or open your reports.",
  "hr.r.nf.id": "Report ID",
  "hr.r.nf.mine": "Open my reports",
  "hr.r.nf.home": "Back to BlockID HR",
  "hr.r.nf.person.eyebrow": "Person not found",
  "hr.r.nf.person.h": "This person is not in the report",
  "hr.r.nf.person.p": "They may have been removed from the report, or the link is wrong. Open the team report to see who is in it.",
};

export const legalVi: Record<keyof typeof legalEn, string> = {
  "foot.terms": "Điều khoản",
  "foot.privacy": "Quyền riêng tư",
  "hr.r.nf.eyebrow": "Không tìm thấy báo cáo",
  "hr.r.nf.h": "Chúng tôi không tìm thấy báo cáo này",
  "hr.r.nf.p": "Liên kết có thể sai, hoặc báo cáo đã bị xóa. Hãy kiểm tra liên kết, hoặc mở danh sách báo cáo của bạn.",
  "hr.r.nf.id": "Mã báo cáo",
  "hr.r.nf.mine": "Mở báo cáo của tôi",
  "hr.r.nf.home": "Về BlockID HR",
  "hr.r.nf.person.eyebrow": "Không tìm thấy người",
  "hr.r.nf.person.h": "Người này không có trong báo cáo",
  "hr.r.nf.person.p": "Người này có thể đã bị gỡ khỏi báo cáo, hoặc liên kết bị sai. Mở báo cáo đội ngũ để xem những ai có trong đó.",
};
