/* Mock of the founding-team / person review API (studio/hr.py) for ?mock=1. In memory; shapes follow the hr.py docstring. */
import { ApiError } from "./api";
import type {
  CvProfile, FitRequirement, HrTarget, HrTargetView, PersonCard, PersonFact, PersonIn, PersonKind, PersonSubScore, Team, TeamFunction,
  TeamListItem, TeamReport, TeamStep, TeamSummary, Valuation,
} from "./api";

export const NO_MATCH = Symbol("no-match");
interface Ctx { actor: () => string; needUser: () => void; isAdmin: () => boolean }
let ctx: Ctx = { actor: () => "anon", needUser: () => undefined, isAdmin: () => false };
export function hrInit(c: Ctx) { ctx = c; }

const DAY = 864e5;
const iso = (t: number) => new Date(t).toISOString();
const STEP_MS = 1100;

interface Rec { t: Team; t0: number | null; by: string; input: PersonIn[]; targetIn: HrTarget | null; demo?: boolean }
const recs = new Map<string, Rec>();
let pid = 100;

/* ---------- deterministic "research" ---------- */
function hash(s: string): number { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
const rnd = (seed: string, lo: number, hi: number) => lo + (hash(seed) % (hi - lo + 1));
const grade = (x: number) => (x >= 80 ? "A" : x >= 65 ? "B" : x >= 50 ? "C" : x >= 35 ? "D" : "E");
const host = (u: string) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } };
const r1 = (x: number) => Math.round(x * 10) / 10;

const PW: Record<string, number> = { domain_fit: 0.25, track_record: 0.25, leadership: 0.15, functional_depth: 0.15, verifiability: 0.1, commitment: 0.1 };
const FW: Record<string, number> = { skills_match: 0.25, domain_match: 0.2, stage_scale_match: 0.15, seniority_match: 0.15, track_record_relevance: 0.15, gaps: 0.1 };
const TW: Record<string, number> = { complementarity: 0.35, key_roles: 0.25, worked_together: 0.15, advisors_board: 0.1, concentration: 0.15 };
const MULT: Record<PersonKind, number> = { founder: 1.5, cofounder: 1.2, executive: 1, employee: 0.8, advisor: 0.4 };

function functionsOf(p: PersonIn): TeamFunction[] {
  const r = (p.role + " " + (p.headline ?? "") + " " + (p.bio ?? "")).toLowerCase();
  const f = new Set<TeamFunction>();
  if (/cto|engineer|tech|product|data|software|developer|ml|ai\b/.test(r)) f.add("tech");
  if (/ceo|sales|growth|market|commercial|revenue|partnership|bd/.test(r)) f.add("commercial");
  if (/cfo|finance|account|capital|investment|banker/.test(r)) f.add("finance");
  if (p.kind === "founder" || /logistic|freight|health|agri|industry|operations|coo/.test(r)) f.add("domain");
  if (!f.size) f.add("commercial");
  return [...f];
}

interface Built { card: PersonCard; sources: TeamReport["sources"] }
function buildCard(p: PersonIn, personId: number, org: string, target: HrTargetView | null, sN: { n: number }): Built {
  const seed = p.full_name + "|" + p.role;
  const urls = p.urls ?? [];
  const hasEvidence = urls.length > 0;
  const sources: TeamReport["sources"] = [];
  const facts: PersonFact[] = [];
  const addSrc = (url: string, title: string, kind = "page") => { const id = "s" + ++sN.n; sources.push({ id, url, title, sha256: hash(url + id).toString(16).padStart(8, "0") + "e3b0c44298fc1c149afbf4c8996fb924", kind, fetched_at: iso(Date.now() - 3600e3), person_id: personId }); return id; };
  const addFact = (text: string, quote: string, url: string, category: string, sid: string) => { const id = `p${personId}f${facts.length + 1}`; facts.push({ id, text, quote, source_id: sid, url, category }); return id; };
  const first = p.full_name.split(/\s+/)[0];
  // provided links: company bio pages are read, LinkedIn is not
  const readable = urls.filter((u) => !/linkedin\.com/i.test(u));
  const fid: string[] = [];
  readable.slice(0, 3).forEach((u, i) => {
    const sid = addSrc(u, `${host(u)} – ${i ? "Profile" : "Team"}`);
    fid.push(addFact(`${p.role || "Team member"} at ${org}`, `${p.full_name} — ${p.role || "team"}, ${org}`, u, "role", sid));
  });
  if (hasEvidence) {
    const press = `https://www.smartcompany.com.au/startupsmart/${first.toLowerCase()}-${hash(seed) % 1000}`;
    const sid = addSrc(press, `SmartCompany – ${org} raises seed round`, "snippet");
    fid.push(addFact(`Named in press coverage of ${org}'s seed round`, `${org}, led by ${p.full_name}, closed its seed round…`, press, "achievement", sid));
  }
  const verifiedN = fid.length;
  const sub: Record<string, PersonSubScore> = {};
  for (const [k, w] of Object.entries(PW)) {
    const sug = rnd(seed + k, 52, 91);
    const selfRep = !!p.bio && !verifiedN;
    const capped = !verifiedN && !p.bio && sug > 50;
    const score = k === "commitment" ? Math.min(100, (p.full_time ? 60 : 35) + (p.equity_pct ? Math.min(30, p.equity_pct) : 0) + (p.start_year ? Math.min(10, new Date().getFullYear() - p.start_year) : 0))
      : k === "verifiability" ? Math.min(95, 30 + verifiedN * 16) : capped ? 50 : sug;
    sub[k] = { score, suggested: sug, capped, weight: w, rationale: `${k.replace(/_/g, " ")}: ${verifiedN ? "backed by " + verifiedN + " cited source(s)" : p.bio ? "from the self-reported bio" : "no source — capped"}.`, fact_ids: verifiedN ? fid.slice(0, 2) : [], self_reported: selfRep };
  }
  const quality = r1(Object.values(sub).reduce((a, s) => a + s.score * s.weight, 0));

  let fit: PersonCard["fit"] = null;
  if (target) {
    const comps: Record<string, PersonSubScore> = {};
    for (const [k, w] of Object.entries(FW)) { const s = rnd(seed + target.type + k, 48, 92); comps[k] = { score: s, suggested: s, capped: false, weight: w, rationale: `${k.replace(/_/g, " ")} against the ${target.type === "role" ? "role" : "business"}.`, fact_ids: fid.slice(0, 1) }; }
    const reqs = target.type === "role" && target.requirements?.length ? target.requirements
      : [`Experience in ${target.type === "business" ? target.sector || "the sector" : "the industry"}`, "Has led a team of 10+ people", "Commercial or sales experience", "Raised capital before", "Built and shipped a product"];
    const ST: FitRequirement["status"][] = ["matched", "matched", "partial", "missing", "unverified"];
    const requirements: FitRequirement[] = reqs.slice(0, 8).map((q, i) => {
      const st = ST[(hash(seed + q) + i) % ST.length];
      return { requirement: q, must_have: i < 3, status: st, fact_ids: st === "matched" || st === "partial" ? fid.slice(i % Math.max(1, fid.length), (i % Math.max(1, fid.length)) + 1) : [], self_reported: st === "partial" && !!p.bio, note: st === "missing" ? "No evidence found in the sources or the CV." : st === "unverified" ? "Claimed in the bio, no source names it." : st === "partial" ? "Some evidence; scale or depth unclear." : "Confirmed by a cited source." };
    });
    fit = {
      target_type: target.type, label: target.type === "role" ? "role fit" : "founder–business fit",
      score: r1(Object.values(comps).reduce((a, s) => a + s.score * s.weight, 0)), components: comps, requirements,
      matched: requirements.filter((r) => r.status === "matched").map((r) => r.requirement),
      missing: requirements.filter((r) => r.status === "missing").map((r) => r.requirement),
      risks: [`Little public record of ${first} managing a budget above A$5M.`, "Key relationships appear to be personal rather than with the company."],
      interview_questions: [`Walk us through the largest team ${first} has hired and led.`, `Which result from the last three years is ${first} proudest of, and who can confirm it?`, "What would you need in the first 90 days to succeed in this role?"],
    };
  }

  const src = (ids: string[]) => (ids.length ? { type: "verified", fact_ids: ids, urls: facts.filter((f) => ids.includes(f.id)).map((f) => f.url!) } : { type: "self_reported", fact_ids: [], urls: [] });
  const startY = p.start_year ?? new Date().getFullYear() - rnd(seed + "y", 1, 5);
  const PRIOR = ["Atlassian", "Canva", "Toll Group", "Deloitte", "Afterpay", "Linfox", "CSIRO", "Macquarie Group"];
  const pr1 = PRIOR[hash(seed + "o1") % PRIOR.length], pr2 = PRIOR[(hash(seed + "o2") + 3) % PRIOR.length];
  const profile: CvProfile = {
    headline: { text: p.headline || `${p.role || "Team member"} at ${org}`, source: p.headline ? { type: "self_reported" } : src(fid.slice(0, 1)) },
    location: { text: "Sydney, Australia", source: src(fid.slice(0, 1)) },
    summary: `${p.full_name} is ${p.role ? "the " + p.role : "a team member"} of ${org}${p.bio ? ". " + p.bio.slice(0, 220) : "."}`,
    experience: [
      { org, title: p.role || "Team member", start: String(startY), end: null, achievements: verifiedN ? [`Led ${org} through its seed round`, "Grew the customer base to 120 businesses"] : [], source: src(fid.slice(0, 1)) },
      { org: pr1, title: /cto|engineer/i.test(p.role) ? "Senior Engineering Manager" : /cfo|finance/i.test(p.role) ? "Finance Manager" : "Head of Operations", start: String(startY - 5), end: String(startY), achievements: ["Managed a team of 14", "Launched two new product lines"], source: src(fid.slice(1, 2)) },
      { org: pr2, title: /cto|engineer/i.test(p.role) ? "Software Engineer" : "Analyst", start: String(startY - 9), end: String(startY - 5), achievements: [], source: { type: "self_reported" } },
    ],
    education: [{ institution: hash(seed) % 2 ? "University of New South Wales" : "University of Melbourne", degree: hash(seed) % 3 ? "Bachelor" : "Master", field: /cto|engineer|tech/i.test(p.role) ? "Computer Science" : "Commerce", start: String(startY - 14), end: String(startY - 10), source: src(fid.slice(0, 1)) }],
    skills: [
      { group: "Leadership", items: ["Hiring", "Team building", "Board reporting"], source: src(fid.slice(0, 1)) },
      { group: /cto|engineer|tech/i.test(p.role) ? "Technology" : "Commercial", items: /cto|engineer|tech/i.test(p.role) ? ["Cloud architecture", "Data platforms", "Security"] : ["Enterprise sales", "Pricing", "Partnerships"], source: { type: "self_reported" } },
    ],
    ventures: p.kind === "founder" || p.kind === "cofounder" ? [{ name: org, role: "Co-founder", outcome: "active", year: startY, source: src(fid.slice(0, 1)) }, ...(hash(seed) % 2 ? [{ name: `${first}Labs`, role: "Founder", outcome: "acquired", year: startY - 4, source: { type: "self_reported" } }] : [])] : [],
    publications: hash(seed + "pub") % 3 === 0 ? [{ title: "Last-mile logistics in regional Australia", kind: "talk", venue: "CeBIT Australia", year: startY - 1, source: { type: "self_reported" } }] : [],
    awards: hash(seed + "aw") % 2 ? [{ title: "AFR Young Rich list – nominee", year: startY - 1, source: src(fid.slice(-1)) }] : [],
    links: urls.map((u) => ({ url: u, label: /linkedin/i.test(u) ? "LinkedIn" : host(u) })),
    completeness_pct: Math.min(100, 35 + verifiedN * 12 + (p.bio ? 10 : 0) + (p.cv ? 15 : 0) + (p.start_year ? 5 : 0)),
  };
  const unconfirmed: PersonCard["unconfirmed"] = p.bio ? [{ text: `Claim from the bio: "${p.bio.slice(0, 80)}${p.bio.length > 80 ? "…" : ""}"`, quote: null, url: null, reason: "No public page names the person with this claim." }] : [];
  if (urls.some((u) => /linkedin\.com/i.test(u))) unconfirmed.push({ text: "LinkedIn profile", quote: null, url: urls.find((u) => /linkedin\.com/i.test(u)) ?? null, reason: "LinkedIn pages cannot be read; details from it are not confirmed." });
  const functions = functionsOf(p);
  const card: PersonCard = {
    person_id: personId, full_name: p.full_name, role: p.role, kind: p.kind, multiplier: MULT[p.kind], score: quality, subscores: sub, fit,
    contribution: r1(fit ? 0.5 * quality + 0.5 * fit.score : quality), profile, facts,
    self_reported: { headline: p.headline ?? null, bio: p.bio ?? null, full_time: p.full_time ?? null, equity_pct: p.equity_pct ?? null, start_year: p.start_year ?? null, has_cv: !!p.cv },
    unconfirmed,
    strengths: [verifiedN ? `Role at ${org} confirmed by ${verifiedN} source(s)` : "Clear account of past roles", functions.includes("tech") ? "Hands-on technical depth" : "Commercial and customer experience"],
    gaps: [verifiedN < 2 ? "Few public sources name this person" : "No prior exit on the public record", p.full_time === false ? "Not full-time in the business" : "Limited board experience"],
    questions: [`Who can confirm ${first}'s results at ${pr1}?`, p.equity_pct == null ? "How is equity split, and is there vesting?" : `Is ${first}'s ${p.equity_pct}% subject to vesting?`],
    functions, model: "mock",
  };
  return { card, sources };
}

function buildReport(rec: Rec): TeamReport {
  const t = rec.t, sN = { n: 0 };
  const target: HrTargetView | null = t.target ?? (t.mode === "team" ? { type: "business", valuation_id: t.valuation_id ?? null, website: t.website ?? null, company: t.name, sector: "Logistics software", stage: "seed" } : null);
  const built = t.people.map((p) => buildCard(p, p.id, t.target?.type === "role" ? t.target.company || t.name : t.name, target, sN));
  const people = built.map((b) => b.card), sources = built.flatMap((b) => b.sources);
  const verified = people.reduce((a, c) => a + c.facts.length, 0), unconf = people.reduce((a, c) => a + c.unconfirmed.length, 0);
  let team: TeamReport["team"] = null;
  if (t.mode !== "person") {
    const wsum = people.reduce((a, c) => a + (c.multiplier ?? 1), 0) || 1;
    const pc = r1(people.reduce((a, c) => a + (c.contribution ?? c.score) * (c.multiplier ?? 1), 0) / wsum);
    const cov = { tech: false, commercial: false, domain: false, finance: false } as Record<TeamFunction, boolean>;
    people.forEach((c) => c.functions.forEach((f) => { cov[f] = true; }));
    const nCov = Object.values(cov).filter(Boolean).length;
    const components = {
      complementarity: 40 + nCov * 14, key_roles: Math.min(95, 35 + people.filter((c) => c.kind !== "advisor").length * 18),
      worked_together: rnd(t.name + "wt", 40, 85), advisors_board: people.some((c) => c.kind === "advisor") ? 72 : 30,
      concentration: people.length > 2 ? 74 : people.length === 2 ? 58 : 32,
    };
    const tc = r1(Object.entries(components).reduce((a, [k, s]) => a + s * TW[k], 0));
    const score = r1(0.6 * pc + 0.4 * tc);
    const missing = (Object.keys(cov) as TeamFunction[]).filter((k) => !cov[k]);
    team = {
      score, grade: grade(score), people_component: pc, team_component: tc, red_flag_penalty: 0, components,
      component_detail: Object.fromEntries(Object.entries(components).map(([k, s]) => [k, { score: s, rationale: `${k.replace(/_/g, " ")}: ${s}/100.`, fact_ids: [], computed: k !== "worked_together" }])),
      coverage: cov,
      strengths: ["Founders cover product and customers between them", "CEO's role and prior operating experience are confirmed by public sources", "Equity is concentrated with full-time founders"],
      gaps: [...missing.map((m) => `No one covers ${m === "finance" ? "finance" : m === "tech" ? "technology" : m === "domain" ? "industry know-how" : "sales"} yet`), "No independent board member"].slice(0, 3),
      risks: ["Key-person risk: most customer relationships sit with the CEO", "Short shared history between the founders"],
      questions: ["Who owns the three largest customer relationships, and are they contracted to the company?", "What is the vesting schedule for founder equity?", "Which senior hire is planned next, and when?"],
      red_flags: [],
    };
  }
  return {
    version: "hr-1", mode: t.mode ?? "team", team, people,
    method: { person_weights: PW, fit_weights: FW, team_weights: TW, role_multipliers: MULT, contribution: "0.5 x quality + 0.5 x fit (quality alone when there is no fit)", cap_without_evidence: 50,
      notes: ["LinkedIn pages are not read; LinkedIn details are shown as unconfirmed.", "Sub-scores without a cited or provided source are capped at 50.", "Emails and phone numbers are removed before any search."], search_providers: ["mock"] },
    sources, counters: { searches: Math.min(12, people.length * 3), search_budget: 12, pages_fetched: sources.length, facts_verified: verified, facts_unconfirmed: unconf, facts_dropped_sensitive: 0, llm_calls: people.length + 1 },
    created_at: iso(Date.now()),
  };
}

/* ---------- lifecycle ---------- */
function stepsFor(rec: Rec): { key: string; person: string | null }[] {
  const out: { key: string; person: string | null }[] = [{ key: "queued", person: null }];
  for (const p of rec.t.people) for (const k of ["fetch", "search", "extract", "score"]) out.push({ key: k, person: p.full_name });
  if (rec.t.mode !== "person") out.push({ key: "team", person: null });
  out.push({ key: "done", person: null });
  return out;
}
const MSG: Record<string, (p: string | null) => string> = {
  queued: () => "Queued", fetch: (p) => `Read the links provided for ${p}`, search: (p) => `Searched public sources for ${p} (3 queries)`,
  extract: (p) => `Matched facts to sources for ${p}`, score: (p) => `Scored ${p}`, team: () => "Scored the team as a whole", done: () => "Report written",
};
function tick(rec: Rec) {
  if (rec.t0 == null || rec.t.status === "done" || rec.t.status === "failed" || rec.t.status === "draft") return;
  const el = Date.now() - rec.t0;
  if (el < 0) { rec.t.status = "queued"; rec.t.steps = []; return; }
  const all = stepsFor(rec);
  const n = Math.min(all.length, Math.floor(el / STEP_MS) + 1);
  rec.t.steps = all.slice(0, n).map((s, i) => ({ at: iso(rec.t0! + i * STEP_MS), step: s.key, person: s.person, msg: MSG[s.key](s.person) }) as TeamStep);
  rec.t.status = n >= all.length ? "done" : n > 1 ? "running" : "queued";
  if (rec.t.status === "done" && !rec.t.result) rec.t.result = buildReport(rec);
  rec.t.updated_at = iso(Date.now());
}

function newRec(o: { id?: string; mode: "team" | "person"; name: string; website?: string | null; valuation_id?: string | null; people: PersonIn[]; target: HrTarget | null; by: string; at?: number; demo?: boolean }): Rec {
  const id = o.id ?? (o.mode === "person" ? "p_" : "t_") + Math.random().toString(36).slice(2, 12);
  const at = o.at ?? Date.now();
  const tv: HrTargetView | null = o.target?.type === "business"
    ? { type: "business", valuation_id: o.target.valuation_id ?? null, ticker: o.target.ticker ?? null, website: o.target.website ?? null, company: o.target.ticker === "HBL" || o.target.valuation_id === "demo" ? "Harbourline Logistics" : o.target.website ? host(o.target.website) : o.target.ticker ?? "Business", sector: "Logistics software", stage: "seed", description: "B2B freight booking and tracking for regional carriers." }
    : o.target ?? null;
  const t: Team = {
    id, mode: o.mode, name: o.name, website: o.website ?? null, valuation_id: o.valuation_id ?? (o.target?.type === "business" ? o.target.valuation_id ?? null : null), company_id: null, target: tv,
    status: "draft", error: null, consent: true, consented_at: iso(at), is_demo: !!o.demo, created_at: iso(at), updated_at: iso(at),
    mine: false, can_edit: false, share_token: null, report_url: `https://hr.blockid.au/${o.mode === "person" ? "p" : "r"}/${id}`, steps: [],
    people: o.people.map((p, i) => ({ ...p, id: ++pid, position: i, has_cv: !!p.cv })), result: null,
  };
  const rec: Rec = { t, t0: null, by: o.by, input: o.people, targetIn: o.target, demo: o.demo };
  recs.set(id, rec);
  return rec;
}
function run(rec: Rec, delay = 0) { rec.t.status = "queued"; rec.t.result = null; rec.t.error = null; rec.t0 = Date.now() + delay; rec.t.steps = []; }

const view = (rec: Rec): Team => {
  tick(rec);
  const me = ctx.actor();
  const own = rec.by === me, adm = ctx.isAdmin();
  return structuredClone({ ...rec.t, mine: own, can_edit: own || adm, share_token: own || adm ? rec.t.share_token : null });
};
function summary(rec: Rec): TeamSummary {
  tick(rec);
  const r = rec.t.result;
  return {
    id: rec.t.id, mode: rec.t.mode, name: rec.t.name, status: rec.t.status, valuation_id: rec.t.valuation_id ?? null,
    score: r ? (r.team?.score ?? r.people[0]?.fit?.score ?? r.people[0]?.score ?? null) : null, grade: r?.team?.grade ?? (r ? grade(r.people[0]?.score ?? 0) : null),
    people: rec.t.people.map((p, i) => ({ full_name: p.full_name, role: p.role, kind: p.kind, score: r?.people[i]?.score ?? null, fit: r?.people[i]?.fit?.score ?? null })),
    strengths: r?.team?.strengths.slice(0, 3) ?? r?.people[0]?.strengths.slice(0, 3) ?? [], gaps: r?.team?.gaps.slice(0, 3) ?? r?.people[0]?.gaps.slice(0, 3) ?? [],
    url: rec.t.report_url,
  };
}
const get = (id: string) => { const r = recs.get(decodeURIComponent(id)); if (!r) throw new ApiError(404, "Report not found"); return r; };
const needEdit = (rec: Rec) => { ctx.needUser(); if (rec.by !== ctx.actor() && !ctx.isAdmin()) throw new ApiError(403, "Only the requester or an admin can change this report"); };

function cleanPeople(b: unknown, max = 20): PersonIn[] {
  const arr = Array.isArray(b) ? b : [];
  if (!arr.length || arr.length > max) throw new ApiError(422, `people: 1..${max} required`);
  return arr.map((x) => {
    const p = x as PersonIn;
    if (!p?.full_name || !String(p.full_name).trim()) throw new ApiError(422, "full_name required");
    return { ...p, full_name: String(p.full_name).trim(), role: String(p.role ?? ""), kind: p.kind ?? "employee" };
  });
}

/* ---------- valuation link (called from mock.ts) ---------- */
export function hrForValuation(valId: string, url: string, people: PersonIn[], by: string): string {
  const name = host(url).split(".")[0].replace(/^\w/, (c) => c.toUpperCase());
  const rec = newRec({ mode: "team", name, website: url, valuation_id: valId, people: cleanPeople(people), target: { type: "business", valuation_id: valId, website: url }, by });
  run(rec, 9000); // after the valuation research
  return rec.t.id;
}
/** Blend a finished team report into the valuation (founder_quality ← team score, basis team_report). */
export function hrApplyToVal(v: Valuation) {
  if (!v.team_id) return;
  const rec = recs.get(v.team_id);
  if (!rec) return;
  v.team = summary(rec);
  const s = rec.t.result?.team?.score;
  const svi = v.svi;
  if (s == null || !svi?.dimensions?.founder_quality) return;
  svi.dimensions.founder_quality = { score: s, basis: "team_report", rationale: `Founding team report ${rec.t.id}: team score ${s} (grade ${rec.t.result!.team!.grade}).` };
  const idx = Object.entries(svi.dimensions).reduce((a, [k, d]) => a + Number(d.score) * Number(svi.weights[k] ?? 0), 0);
  svi.index = r1(idx);
  svi.band = grade(idx);
}

/* ---------- demo data ---------- */
{
  const DEMO_BY = "demo";
  const team = newRec({
    id: "t_demo", mode: "team", name: "Harbourline Logistics", website: "https://harbourline.com.au", valuation_id: "demo", by: DEMO_BY, at: Date.now() - 44 * DAY, demo: true,
    target: { type: "business", valuation_id: "demo", website: "https://harbourline.com.au" },
    people: [
      { full_name: "Maya Chen", role: "CEO", kind: "founder", headline: "Freight operator, ex-Toll Group", full_time: true, start_year: 2019, equity_pct: 42, urls: ["https://harbourline.com.au/team", "https://www.linkedin.com/in/mayachen"], bio: "Ran regional operations at Toll Group for 6 years; founded Harbourline in 2019." },
      { full_name: "Tom Nguyen", role: "CTO", kind: "cofounder", headline: "Platform engineer", full_time: true, start_year: 2019, equity_pct: 30, urls: ["https://harbourline.com.au/team", "https://github.com/tomnguyen"], bio: "Built routing software at Atlassian and a logistics start-up that was acquired in 2018." },
      { full_name: "Priya Shah", role: "Head of Sales", kind: "executive", full_time: true, start_year: 2022, equity_pct: 3, urls: ["https://harbourline.com.au/team"], bio: "Enterprise sales at Linfox." },
      { full_name: "Liam O'Brien", role: "Advisor", kind: "advisor", full_time: false, start_year: 2021, equity_pct: 1, urls: [], bio: "Former CFO of a listed transport company." },
    ],
  });
  run(team); team.t0 = Date.now() - 44 * DAY; tick(team);
  const person = newRec({
    id: "p_demo", mode: "person", name: "Maya Chen", by: DEMO_BY, at: Date.now() - 3 * DAY, demo: true,
    target: { type: "role", company: "Southern Cross Freight", title: "Chief Operating Officer", description: "Lead operations across 14 depots and a 300-person workforce.", requirements: ["10+ years in freight or logistics operations", "Has run a P&L above A$20M", "Led teams of 100+ people", "Experience with routing or fleet software", "Board reporting experience"] },
    people: [{ full_name: "Maya Chen", role: "CEO", kind: "founder", headline: "Freight operator, ex-Toll Group", full_time: true, start_year: 2019, urls: ["https://harbourline.com.au/team", "https://www.linkedin.com/in/mayachen"], bio: "Ran regional operations at Toll Group for 6 years; founded Harbourline in 2019.", cv: "Toll Group — Regional Operations Manager 2013–2019 …" }],
  });
  run(person); person.t0 = Date.now() - 3 * DAY; tick(person);
}

/* ---------- router ---------- */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type H = (m: RegExpMatchArray, b: any) => unknown;
const routes: [string, RegExp, H][] = [
  ["POST", /^\/v1\/hr\/teams$/, (_m, b) => {
    ctx.needUser();
    if (b?.consent !== true) throw new ApiError(422, "consent must be true");
    if (!String(b?.name ?? "").trim()) throw new ApiError(422, "name required");
    const rec = newRec({ mode: "team", name: String(b.name).trim(), website: b.website ?? null, valuation_id: b.valuation_id ?? null, people: cleanPeople(b.people), target: b.valuation_id || b.website ? { type: "business", valuation_id: b.valuation_id ?? null, website: b.website ?? null } : null, by: ctx.actor() });
    if (b.run) run(rec);
    return view(rec);
  }],
  ["POST", /^\/v1\/hr\/people-reports$/, (_m, b) => {
    ctx.needUser();
    if (b?.consent !== true) throw new ApiError(422, "consent must be true");
    const [p] = cleanPeople([b?.person], 1);
    const rec = newRec({ mode: "person", name: p.full_name, people: [p], target: b?.target ?? null, by: ctx.actor() });
    if (b?.run !== false) run(rec);
    return view(rec);
  }],
  ["GET", /^\/v1\/hr\/teams$/, (): { teams: TeamListItem[] } => {
    ctx.needUser();
    const me = ctx.actor();
    const teams = [...recs.values()].filter((r) => r.by === me || r.demo).map((r) => {
      const s = summary(r);
      return { id: r.t.id, mode: r.t.mode, name: r.t.name, status: r.t.status, valuation_id: r.t.valuation_id ?? null, company_id: null, score: s.score, grade: s.grade, people_count: r.t.people.length, target_type: r.t.target?.type ?? null, created_at: r.t.created_at, updated_at: r.t.updated_at };
    });
    return { teams: teams.sort((a, b) => +new Date(b.created_at!) - +new Date(a.created_at!)) };
  }],
  ["GET", /^\/v1\/hr\/(?:teams|people-reports)\/([^/]+)$/, (m) => view(get(m[1]))],
  ["GET", /^\/v1\/hr\/teams\/([^/]+)\/summary$/, (m) => summary(get(m[1]))],
  ["PUT", /^\/v1\/hr\/teams\/([^/]+)\/people$/, (m, b) => { const r = get(m[1]); needEdit(r); if (r.t.status === "running") throw new ApiError(409, "running"); r.t.people = cleanPeople(b?.people).map((p, i) => ({ ...p, id: ++pid, position: i })); r.t.status = "draft"; r.t.result = null; r.t0 = null; return view(r); }],
  ["PUT", /^\/v1\/hr\/teams\/([^/]+)\/target$/, (m, b) => { const r = get(m[1]); needEdit(r); r.t.target = b?.target ?? null; r.t.status = "draft"; r.t.result = null; r.t0 = null; return view(r); }],
  ["POST", /^\/v1\/hr\/teams\/([^/]+)\/run$/, (m) => { const r = get(m[1]); needEdit(r); tick(r); if (r.t.status === "queued" || r.t.status === "running") throw new ApiError(409, "already running"); run(r); return view(r); }],
  ["POST", /^\/v1\/hr\/teams\/([^/]+)\/share$/, (m) => { const r = get(m[1]); needEdit(r); r.t.share_token = Math.random().toString(36).slice(2, 14); return { share_token: r.t.share_token }; }],
  ["DELETE", /^\/v1\/hr\/teams\/([^/]+)\/share$/, (m) => { const r = get(m[1]); needEdit(r); r.t.share_token = null; return { ok: true }; }],
  ["POST", /^\/v1\/hr\/teams\/([^/]+)\/apply-to-valuation$/, (m) => { const r = get(m[1]); needEdit(r); return { applied: r.t.status === "done" && !!r.t.valuation_id, reason: r.t.valuation_id ? null : "no linked valuation" }; }],
  ["DELETE", /^\/v1\/hr\/teams\/([^/]+)$/, (m) => { const r = get(m[1]); needEdit(r); recs.delete(r.t.id); return { ok: true }; }],
  ["DELETE", /^\/v1\/hr\/people\/(\d+)$/, (m) => {
    for (const r of recs.values()) {
      const i = r.t.people.findIndex((p) => p.id === +m[1]);
      if (i < 0) continue;
      needEdit(r);
      r.t.people.splice(i, 1);
      if (r.t.result) { r.t.result.people = r.t.result.people.filter((c) => c.person_id !== +m[1]); }
      return { ok: true, team_id: r.t.id };
    }
    throw new ApiError(404, "Person not found");
  }],
];

/** Returns NO_MATCH when the path is not an HR route. */
export function hrHandle(method: string, path: string, body: unknown): unknown {
  if (!path.startsWith("/v1/hr/")) return NO_MATCH;
  for (const [m, re, h] of routes) {
    if (m !== method) continue;
    const mm = path.match(re);
    if (mm) return h(mm, body);
  }
  return NO_MATCH;
}
