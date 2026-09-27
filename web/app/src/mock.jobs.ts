/* Mock of GET /v1/me/active-jobs (studio/active_jobs.py) for ?mock=1: built from the mock valuation and HR routes, so
   the tray follows the same simulated runs the pages show (a valuation takes ~13 s, an HR report ~20 s). */
import type { Team, TeamListItem, Valuation } from "./api";

type Call = (method: string, path: string, body?: unknown) => Promise<unknown>;
type Route = [string, RegExp, (m: RegExpMatchArray, body: unknown) => unknown];

const WINDOW_MS = 30 * 60e3;
const VAL_TOTAL_S = 13; // mock.ts progress(): 1 s queued + 6 steps x 2 s
const ETH = "https://eth.blockid.au", HR = "https://hr.blockid.au";
const host = (u: string) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } };

function valuationJob(v: Valuation) {
  const steps = v.steps ?? [];
  const done = steps.filter((s) => s.status === "done").length;
  const running = steps.find((s) => s.status === "running");
  const live = v.status === "queued" || v.status === "running";
  const lastAt = steps.map((s) => (s.at ? +new Date(s.at) : 0)).reduce((a, b) => Math.max(a, b), 0);
  const created = v.created_at ? +new Date(v.created_at) : Date.now();
  const finished = live ? null : new Date(lastAt || created).toISOString();
  const name = typeof v.profile?.name === "string" && v.profile.name ? v.profile.name : host(v.url);
  const status = live ? v.status : v.status === "failed" ? "failed" : "done";
  return {
    kind: "valuation", id: v.id, title: name, status, raw_status: v.status,
    phase: v.status === "queued" ? "queued" : live ? running?.key ?? "read_site" : status,
    pct: status === "done" ? 100 : Math.min(99, Math.round((100 * (done + (running ? 0.5 : 0))) / Math.max(1, steps.length))),
    eta_s: live ? Math.max(1, Math.round(VAL_TOTAL_S - (Date.now() - created) / 1000)) : status === "done" ? 0 : null,
    url: `${ETH}/v/${encodeURIComponent(v.id)}/${status === "done" ? "report" : "research"}`,
    started_at: v.created_at ?? null, updated_at: finished ?? new Date().toISOString(), finished_at: finished,
  };
}

function hrJob(t: Team) {
  const live = t.status === "queued" || t.status === "running";
  const p = t.progress;
  const person = t.mode === "person";
  const finished = live ? null : p?.updated_at ?? t.updated_at ?? null;
  return {
    kind: person ? "hr_person" : "hr_team", id: t.id, title: t.name, status: t.status, raw_status: t.status,
    phase: p?.phase ?? t.status, pct: t.status === "done" ? 100 : Math.round(p?.pct ?? 0), eta_s: t.status === "done" ? 0 : p?.eta_s ?? null,
    url: `${HR}/${person ? "p" : "r"}/${encodeURIComponent(t.id)}`,
    started_at: p?.started_at ?? t.created_at ?? null, updated_at: t.updated_at ?? null, finished_at: finished,
  };
}

async function activeJobs(call: Call) {
  const [vals, list] = await Promise.all([
    call("GET", "/v1/studio/valuations") as Promise<Valuation[]>,
    (call("GET", "/v1/hr/teams?mine=1") as Promise<{ teams: TeamListItem[] }>).catch(() => ({ teams: [] as TeamListItem[] })),
  ]);
  const recent = (iso: string | null | undefined) => !!iso && Date.now() - +new Date(iso) < WINDOW_MS;
  const vj = vals.map(valuationJob).filter((j) => j.status === "queued" || j.status === "running" || recent(j.finished_at));
  const cand = list.teams.filter((t) => t.status !== "draft" && (t.status === "queued" || t.status === "running" || recent(t.updated_at) || recent(t.created_at)));
  const teams = (await Promise.all(cand.map((t) => (call("GET", `/v1/hr/teams/${encodeURIComponent(t.id)}`) as Promise<Team>).catch(() => null))))
    .filter((t): t is Team => !!t && !!t.mine && t.status !== "draft");
  const hj = teams.map(hrJob).filter((j) => j.status === "queued" || j.status === "running" || recent(j.finished_at));
  const all = [...vj, ...hj];
  const live = all.filter((j) => j.status === "queued" || j.status === "running").sort((a, b) => (b.started_at ?? "").localeCompare(a.started_at ?? ""));
  const done = all.filter((j) => !(j.status === "queued" || j.status === "running")).sort((a, b) => (b.finished_at ?? "").localeCompare(a.finished_at ?? ""));
  return { jobs: [...live, ...done].slice(0, 20), server_time: new Date().toISOString() };
}

/** Routes for mock.ts; `call` is mock.ts handle (session, valuations and HR state live there). */
export function jobsRoutes(call: Call): Route[] {
  return [["GET", /^\/v1\/me\/active-jobs$/, () => activeJobs(call)]];
}
