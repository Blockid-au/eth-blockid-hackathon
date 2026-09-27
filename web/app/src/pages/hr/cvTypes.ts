/* CV review shapes (agents/cv_review.py): card.cv_review in the report, partial.people[].cv while it runs. */
export interface CvReadStats { words: number; chars: number; sections: string[]; years: [number, number] | null; links: string[]; redacted: number }
export interface CvRoleR { org: string; title: string; start: string; end: string; location?: string; kind: string; team_size?: number | null; highlights: string[]; months?: number }
export interface CvEduR { institution: string; degree?: string; field?: string; start?: string; end?: string }
export interface CvGap { from: string; to: string; months: number }
export interface CvTimelineStats { years: number; roles: number; avg_tenure_months: number | null; longest_months: number | null; gaps: CvGap[]; overlaps: number; first: string | null; current: string | null; short_stints: number }
export interface CvTimeline { headline: string; location: string; roles: CvRoleR[]; education: CvEduR[]; certifications: string[]; languages: string[]; stats: CvTimelineStats }
export interface CvSkillR { name: string; level: "expert" | "strong" | "working"; years?: number | null; evidence?: string }
export interface CvAchR { text: string; metric?: string; org?: string }
export interface CvClaimR { text: string; org?: string; kind: string; status?: "confirmed" | "unconfirmed"; fact_ids?: string[] }
export interface CvInsights { summary: string; seniority: "entry" | "mid" | "senior" | "lead" | "executive"; skills: CvSkillR[]; achievements: CvAchR[]; leadership: string[]; strengths: string[]; concerns: string[]; questions: string[]; claims: CvClaimR[] }
export interface CvReview { read: CvReadStats; timeline: CvTimeline | null; insights: CvInsights | null; claims: CvClaimR[]; models?: Record<string, string> }
export type CvLive = Partial<{ read: CvReadStats; timeline: CvTimeline; insights: CvInsights; claims: CvClaimR[] }>;

/** "2019-03" / "2019" / "present" -> months since year 0. */
export function monthOf(s: string | undefined, end = false): number | null {
  const v = (s || "").trim().toLowerCase();
  if (!v) return null;
  if (/present|current|now|nay|hiện tại/.test(v)) { const d = new Date(); return d.getFullYear() * 12 + d.getMonth(); }
  const y = v.match(/\b(19|20)\d\d\b/);
  if (!y) return null;
  const rest = v.replace(y[0], " ");
  const m = rest.match(/(?:^|[-/.\s])(0?[1-9]|1[0-2])(?:$|[-/.\s])/);
  const names = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
  const nm = names.findIndex((n) => rest.includes(n));
  return +y[0] * 12 + (m ? +m[1] - 1 : nm >= 0 ? nm : end ? 11 : 0);
}
