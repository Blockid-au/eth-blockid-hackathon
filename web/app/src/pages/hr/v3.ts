/* Pure helpers for the hr-2 report parts (docs/PLAN-HR-V3.md §1–3, §9): claim ledger, trust, fit lenses, decision.
   No React here so they can be unit-tested on their own. Everything tolerates hr-1 reports (fields missing). */
import type { FitLens, FitVerdict, PersonCard, PersonFit } from "../../api";
import { CLAIM_STATUSES, type ClaimStatus, type CvRoleR, type Ledger, type LedgerClaim } from "./cvTypes";

export const LENSES: FitLens[] = ["business", "jd", "current_role"];

/** Counts per status: the server's block when present, else counted from the claims. */
export function ledgerCounts(l: Ledger | null | undefined): Record<ClaimStatus, number> {
  const out = Object.fromEntries(CLAIM_STATUSES.map((s) => [s, 0])) as Record<ClaimStatus, number>;
  if (!l) return out;
  const server = l.counts ?? {};
  const hasServer = CLAIM_STATUSES.some((s) => typeof server[s] === "number");
  if (hasServer) { for (const s of CLAIM_STATUSES) out[s] = Number(server[s]) || 0; return out; }
  for (const c of l.claims ?? []) if ((CLAIM_STATUSES as string[]).includes(c.status)) out[c.status as ClaimStatus]++;
  return out;
}

export type ClaimFilter = "all" | "contradicted" | "not_found" | "unverifiable" | "verified";
export const CLAIM_FILTERS: ClaimFilter[] = ["all", "contradicted", "not_found", "unverifiable", "verified"];
/** "Verified" also lists the partly verified claims; the other filters are one status each. */
export function filterClaims(claims: LedgerClaim[], f: ClaimFilter): LedgerClaim[] {
  if (f === "all") return claims;
  if (f === "verified") return claims.filter((c) => c.status === "verified" || c.status === "partly_verified");
  return claims.filter((c) => c.status === f);
}
export function filterCount(counts: Record<ClaimStatus, number>, total: number, f: ClaimFilter): number {
  if (f === "all") return total;
  if (f === "verified") return counts.verified + counts.partly_verified;
  return counts[f];
}

/** Lower-case letters and digits only, so "Acme Pty Ltd." and "acme pty ltd" match. */
export const normKey = (s: string | null | undefined) => (s ?? "").toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, " ").trim();

/** The role claim for a CV timeline role: same org and title; else the only role claim at that org. */
export function matchRoleClaim(role: Pick<CvRoleR, "org" | "title">, claims: LedgerClaim[]): LedgerClaim | null {
  const org = normKey(role.org), title = normKey(role.title);
  if (!org) return null;
  const roleClaims = claims.filter((c) => (c.kind === "role" || c.kind === "venture") && normKey(c.org) === org);
  if (!roleClaims.length) return null;
  const exact = roleClaims.find((c) => normKey(c.title) === title);
  if (exact) return exact;
  const loose = title ? roleClaims.find((c) => { const ct = normKey(c.title); return !!ct && (ct.includes(title) || title.includes(ct)); }) : undefined;
  if (loose) return loose;
  return roleClaims.length === 1 ? roleClaims[0] : null;
}

/** Colour group of a claim status on the career timeline: teal verified, amber unverified, red conflict. */
export function timelineTone(status: string | null | undefined): "ok" | "part" | "unv" | "bad" {
  if (status === "verified") return "ok";
  if (status === "partly_verified") return "part";
  if (status === "contradicted") return "bad";
  return "unv";
}

/** Verdict bands (§2.4): Strong ≥ 75 · With conditions 55–74 (or capped by a knockout) · Weak 35–54 · Not suitable < 35. */
export function verdictOf(score: number, cap?: number | null): FitVerdict {
  const v: FitVerdict = score >= 75 ? "strong" : score >= 55 ? "conditional" : score >= 35 ? "weak" : "not_suitable";
  return cap != null && v === "strong" ? "conditional" : v;
}
const VERDICTS: FitVerdict[] = ["strong", "conditional", "weak", "not_suitable"];
export function fitVerdict(fit: PersonFit): FitVerdict {
  return (VERDICTS as string[]).includes(String(fit.verdict)) ? (fit.verdict as FitVerdict) : verdictOf(fit.score, fit.cap);
}
export const asVerdict = (v: string | null | undefined, score?: number | null): FitVerdict | null =>
  (VERDICTS as string[]).includes(String(v)) ? (v as FitVerdict) : score != null ? verdictOf(score) : null;

/** The fit lenses present on a card, in display order. hr-1 cards: the single `fit`, lens from its target type. */
export function fitsOf(card: Pick<PersonCard, "fit" | "fits">): [FitLens, PersonFit][] {
  const fits = card.fits ?? {};
  const out = LENSES.filter((l) => fits[l]).map((l) => [l, fits[l]!] as [FitLens, PersonFit]);
  if (out.length) return out;
  if (card.fit) return [[card.fit.lens && (LENSES as string[]).includes(card.fit.lens) ? card.fit.lens : card.fit.target_type === "role" ? "jd" : "business", card.fit]];
  return [];
}
/** Lens to open first: the decision's lens, else JD, business, current role. */
export function primaryLens(card: Pick<PersonCard, "fit" | "fits" | "decision">): FitLens | null {
  const ls = fitsOf(card).map(([l]) => l);
  const d = card.decision?.fit_lens as FitLens | undefined;
  if (d && ls.includes(d)) return d;
  return (["jd", "business", "current_role"] as FitLens[]).find((l) => ls.includes(l)) ?? null;
}

/** Points of the fit that rest on unverified CV claims (claimed − verified), 0 when not shown. */
export function claimGap(fit: Pick<PersonFit, "claimed_score" | "verified_score" | "score">): number {
  const c = fit.claimed_score, v = fit.verified_score ?? fit.score;
  if (c == null || v == null) return 0;
  return Math.max(0, Math.round(c - v));
}

export const TRUST_BANDS = ["high", "medium", "low"] as const;
export const asBand = (b: string | null | undefined): (typeof TRUST_BANDS)[number] | null => ((TRUST_BANDS as readonly string[]).includes(String(b)) ? (b as (typeof TRUST_BANDS)[number]) : null);

export const QUADRANTS = ["proceed", "verify_first", "other_role", "stop"] as const;
export type Quadrant = (typeof QUADRANTS)[number];
/** 2×2 cell of a quadrant: [row, col] with row 0 = trust high, col 1 = fit high. */
export function quadrantCell(q: Quadrant): [0 | 1, 0 | 1] {
  return q === "proceed" ? [0, 1] : q === "other_role" ? [0, 0] : q === "verify_first" ? [1, 1] : [1, 0];
}

/** Requirement evidence level, derived for hr-1 rows that carry no `evidence`. */
export function reqEvidence(r: { evidence?: string; status: string; fact_ids?: string[]; self_reported?: boolean }): "verified" | "cv_only" | "contradicted" | "none" {
  if (r.evidence === "verified" || r.evidence === "cv_only" || r.evidence === "contradicted" || r.evidence === "none") return r.evidence;
  if (r.status === "missing") return "none";
  if (r.fact_ids?.length) return "verified";
  return r.self_reported ? "cv_only" : "none";
}

/** Share of a relevant-years gauge: [person, min] as % of a scale that holds both with some head room. */
export function yearsGauge(years: number, min: number | null | undefined): { scale: number; you: number; need: number | null } {
  const scale = Math.max(5, Math.ceil(Math.max(years, min ?? 0) * 1.25));
  return { scale, you: Math.min(100, (Math.max(0, years) / scale) * 100), need: min != null ? Math.min(100, (min / scale) * 100) : null };
}
