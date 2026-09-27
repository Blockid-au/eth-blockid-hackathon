/* Client-side helpers for the "Analyse a person" wizard: read a pasted LinkedIn/URL/CV and a job description.
   Nothing here leaves the browser; the results are only suggestions the user can apply or ignore. */
import { normUrl } from "../../lib/people";

export interface PasteGuess {
  name?: string;
  headline?: string;
  role?: string;
  urls: string[];
  cv?: string;
  from: "linkedin" | "url" | "text" | "none";
}

const URL_RE = /\b(?:https?:\/\/[^\s<>"'()]+|(?:www\.)?linkedin\.com\/in\/[^\s<>"'()]+|github\.com\/[^\s<>"'()]+)/gi;
const EMAIL_RE = /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g;
const PHONE_RE = /(?:\+?\d[\d\s().-]{7,}\d)/g;
const NOT_NAME = /\b(curriculum|vitae|resume|résumé|profile|cv|contact|summary|experience|education|skills|linkedin|about|hồ sơ|lý lịch)\b/i;

const cap = (w: string) => (w ? w[0].toLocaleUpperCase() + w.slice(1).toLocaleLowerCase() : w);
const titleCase = (s: string) => s.split(/\s+/).filter(Boolean).map(cap).join(" ");

/** "do-van-long-1a2b3c4d" → "Do Van Long"; returns "" when the slug does not look like a name. */
export function nameFromSlug(slug: string): string {
  let s = slug;
  try { s = decodeURIComponent(slug); } catch { /* keep raw */ }
  const words = s.split(/[-_.\s]+/).filter(Boolean).filter((w) => !/\d/.test(w) && /^[\p{L}']+$/u.test(w));
  if (!words.length || words.length > 5) return "";
  if (words.length === 1 && words[0].length < 3) return "";
  return titleCase(words.join(" "));
}

/** Name guessed from a public URL: LinkedIn /in/<slug> or a team page path like /team/maya-chen. */
export function nameFromUrl(u: string): string {
  let url: URL;
  try { url = new URL(u); } catch { return ""; }
  const parts = url.pathname.split("/").filter(Boolean);
  if (/linkedin\.com$/i.test(url.hostname.replace(/^www\./, "")) || /(^|\.)linkedin\.com$/i.test(url.hostname)) {
    const i = parts.indexOf("in");
    return i >= 0 && parts[i + 1] ? nameFromSlug(parts[i + 1]) : "";
  }
  if (/github\.com$/i.test(url.hostname)) return "";
  const last = parts[parts.length - 1] ?? "";
  if (!/[-_]/.test(last)) return "";
  const n = nameFromSlug(last.replace(/\.[a-z]{2,5}$/i, ""));
  return n.split(" ").length >= 2 && n.split(" ").length <= 4 ? n : "";
}

function looksLikeName(line: string): boolean {
  if (line.length < 4 || line.length > 60 || NOT_NAME.test(line) || /\d|@|[|:/]/.test(line)) return false;
  const w = line.split(/\s+/);
  return w.length >= 2 && w.length <= 5 && w.every((x) => /^[\p{Lu}][\p{L}'.-]*$/u.test(x));
}

/** Role from a headline: "CEO at Harbourline", "Founder | BlockID", "CTO @ X", "Giám đốc tại Y". */
export function roleFromHeadline(h: string): string {
  const m = /^(.{2,60}?)\s+(?:at|@|tại|of)\s+\S/i.exec(h);
  if (m) return m[1].trim();
  const seg = h.split(/\s*[|·•,–—-]\s+/)[0]?.trim() ?? "";
  return seg.length >= 2 && seg.length <= 50 && seg !== h ? seg : h.length <= 40 ? h : "";
}

/** Read a pasted LinkedIn URL, any public URL, or CV text. */
export function parsePaste(raw: string): PasteGuess {
  const text = raw.trim();
  if (!text) return { urls: [], from: "none" };
  const found = text.match(URL_RE) ?? [];
  const urls = [...new Set(found.map((u) => normUrl(u.replace(/[.,;]+$/, ""))).filter((u): u is string => !!u))].slice(0, 6);
  const rest = text.replace(URL_RE, " ").replace(EMAIL_RE, " ").replace(PHONE_RE, " ");
  const lines = rest.split(/\r?\n/).map((l) => l.replace(/\s+/g, " ").trim()).filter((l) => l.length > 1);
  const out: PasteGuess = { urls, from: "none" };
  const li = urls.find((u) => /linkedin\.com\/in\//i.test(u));
  if (li) { out.from = "linkedin"; out.name = nameFromUrl(li) || undefined; }
  else if (urls.length) { out.from = "url"; out.name = nameFromUrl(urls[0]) || undefined; }
  if (lines.length) {
    out.from = out.from === "none" ? "text" : out.from;
    const ni = lines.slice(0, 3).findIndex(looksLikeName);
    if (ni >= 0) out.name = lines[ni];
    const h = lines.slice(ni >= 0 ? ni + 1 : 0, (ni >= 0 ? ni + 1 : 0) + 2).find((l) => l.length >= 6 && l.length <= 160 && !NOT_NAME.test(l.split(/\s+/)[0]));
    if (h) { out.headline = h; const r = roleFromHeadline(h); if (r) out.role = r.slice(0, 80); }
    const body = lines.join("\n");
    if (body.length > 160) out.cv = body.slice(0, 20000);
  }
  return out;
}

/* ---------- requirements from a job description ---------- */
const REQ_HINT = /(\d+\s*\+?\s*(?:years?|yrs|năm)|experience|kinh nghiệm|ability to|knowledge of|degree|proven|track record|\bled\b|leading|\blead\b|manag|proficien|familiar|must|required|strong|expert|hands-on|background in|understanding of|thành thạo|am hiểu|có khả năng)/i;
const SKILLS: [RegExp, string][] = [
  [/\bpython\b/i, "Python"], [/\btypescript\b/i, "TypeScript"], [/\breact\b/i, "React"], [/\bnode(?:\.js)?\b/i, "Node.js"], [/\bsql\b|postgres/i, "SQL databases"],
  [/\baws\b|amazon web services/i, "AWS"], [/\bgcp\b|google cloud/i, "Google Cloud"], [/\bazure\b/i, "Azure"], [/kubernetes|\bk8s\b/i, "Kubernetes"],
  [/solidity|smart contract/i, "Smart contracts (Solidity)"], [/blockchain|web3|ethereum/i, "Blockchain / web3"], [/machine learning|\bml\b|deep learning/i, "Machine learning"],
  [/\bai\b|artificial intelligence|llm/i, "AI products"], [/data science|analytics/i, "Data and analytics"], [/product management|product manager|roadmap/i, "Product management"],
  [/b2b sales|enterprise sales|account executive/i, "B2B / enterprise sales"], [/\bsaas\b/i, "SaaS"], [/fundrais|venture capital|investor relations/i, "Fundraising"],
  [/p&l|profit and loss/i, "P&L ownership"], [/board report|board of directors/i, "Board reporting"], [/logistic|freight|supply chain/i, "Logistics / supply chain"],
  [/fintech|payments|banking/i, "Fintech / payments"], [/compliance|regulat/i, "Regulation and compliance"], [/marketing|growth|go-to-market|\bgtm\b/i, "Growth and marketing"],
  [/recruit|hiring|talent/i, "Hiring and building teams"], [/operations|\bops\b/i, "Operations"], [/team of \d+|people management|line management/i, "Managing people"],
];

const clean = (s: string) => s.replace(/^[\s\-*•·–—>]+/, "").replace(/^\(?\d{1,2}[.)]\s+/, "").replace(/[\s.;:,]+$/, "").trim();
const capFirst = (s: string) => (s ? s[0].toLocaleUpperCase() + s.slice(1) : s);

/** Requirement suggestions from a job description (plain keyword rules; shown as chips the user can add or edit). */
export function suggestRequirements(desc: string, max = 10): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  const add = (s: string) => { const c = capFirst(clean(s)).slice(0, 140); const k = c.toLowerCase(); if (c.length >= 6 && !seen.has(k)) { seen.add(k); out.push(c); } };
  const parts = desc.split(/\r?\n|•|·|;|(?<=[.!?])\s+/).map(clean).filter(Boolean);
  for (const p of parts) if (p.length >= 10 && p.length <= 140 && REQ_HINT.test(p)) add(p);
  for (const [re, label] of SKILLS) if (re.test(desc) && ![...seen].some((s) => s.includes(label.toLowerCase().split(" ")[0]))) add(label);
  return out.slice(0, max);
}

/** A short badge for a business without a ticker: the initials of its name. */
export function bizInitials(name: string): string {
  const w = name.replace(/https?:\/\//, "").split(/[\s.-]+/).filter(Boolean);
  return ((w[0]?.[0] ?? "?") + (w[1]?.[0] ?? "")).toUpperCase();
}
/** Stable hue (0..359) for a name, used to tint logo initials. */
export function hueOf(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h % 360;
}

/* ---------- people handed over from eth.blockid.au: ?person=<full name>|<role> (repeated) ---------- */
export interface HandedPerson { full_name: string; role: string; kind: import("../../api").PersonKind }
/** Kind from a role: founder for the first person, cofounder for the rest, unless the role says otherwise. */
export function kindFromRole(role: string, idx: number): HandedPerson["kind"] {
  const r = role.toLowerCase();
  if (/advis|mentor|cố vấn/.test(r)) return "advisor";
  if (/co-?\s?founder|đồng sáng lập/.test(r)) return "cofounder";
  if (/founder|sáng lập/.test(r)) return idx === 0 ? "founder" : "cofounder";
  if (/board|non-exec|chair/.test(r)) return "advisor";
  if (/\b(engineer|developer|designer|analyst|associate|intern|specialist|nhân viên)\b/.test(r)) return "employee";
  if (/\b(head of|vp|vice president|director|manager|chief|cfo|coo|cmo|cto|ceo|giám đốc|trưởng)\b/.test(r)) return idx === 0 ? "founder" : /\b(cto|ceo)\b/.test(r) ? "cofounder" : "executive";
  return idx === 0 ? "founder" : "cofounder";
}
/** Parse the repeated `person` params ("Name|Role"); max 20, names trimmed to 120. */
export function handedPeople(params: URLSearchParams): HandedPerson[] {
  return params.getAll("person").map((raw) => {
    const i = raw.indexOf("|");
    const full_name = (i >= 0 ? raw.slice(0, i) : raw).trim().slice(0, 120);
    const role = (i >= 0 ? raw.slice(i + 1) : "").trim().slice(0, 80);
    return { full_name, role };
  }).filter((p) => p.full_name).slice(0, 20).map((p, idx) => ({ ...p, kind: kindFromRole(p.role, idx) }));
}
