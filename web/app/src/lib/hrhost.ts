/**
 * Host switch for the one SPA build served on two hosts:
 *   eth.blockid.au → the business passport app, hr.blockid.au → the founding-team review app ("BlockID HR").
 * Local testing: `?host=hr` (kept for this tab until `?host=eth`) or VITE_HOST=hr at build/dev time.
 */
const KEY = "blockid-host";

export const HR_HOST: boolean = (() => {
  if (typeof location === "undefined") return false;
  if (/^hr\./i.test(location.hostname)) return true;
  if (/^eth\./i.test(location.hostname)) return false;
  try {
    const q = new URLSearchParams(location.search).get("host");
    if (q === "hr") sessionStorage.setItem(KEY, "hr");
    if (q === "eth") sessionStorage.removeItem(KEY);
    return import.meta.env.VITE_HOST === "hr" || sessionStorage.getItem(KEY) === "hr";
  } catch {
    return import.meta.env.VITE_HOST === "hr";
  }
})();

/** A link to `path` on the other app: real sibling host in production, same origin + ?host= elsewhere. */
function onHost(target: "hr" | "eth", path: string): string {
  const m = /^(eth|hr)\.(.+)$/i.exec(location.hostname);
  if (m) return `${location.protocol}//${target}.${m[2]}${location.port ? ":" + location.port : ""}${path}`;
  const u = new URL(path, location.origin);
  u.searchParams.set("host", target);
  return u.pathname + u.search + u.hash;
}

/** URL of a page of the HR app (relative when we are already on it). */
export function hrUrl(path: string): string {
  return HR_HOST ? path : onHost("hr", path);
}

/** URL of a page of the eth (business passport) app (relative when we are already on it). */
export function ethUrl(path: string): string {
  return HR_HOST ? onHost("eth", path) : path;
}

/* ---------- eth → hr links (docs/PLAN-HR-V2.md §3) ---------- */

/** A link returned by the API (absolute https://hr.blockid.au/…) mapped onto the current environment. */
export function hrLink(u: string | null | undefined, fallbackPath: string): string {
  if (!u) return hrUrl(fallbackPath);
  try {
    const x = new URL(u, "https://hr.blockid.au");
    if (/^hr\./i.test(x.hostname)) return hrUrl(x.pathname + x.search + x.hash);
  } catch { /* fall through */ }
  return hrUrl(fallbackPath);
}

/** hr team report of a valuation's founding team. */
export const hrTeamUrl = (teamId: string) => hrUrl(`/r/${encodeURIComponent(teamId)}`);

/** One person inside a team report: by person id when known, else by position (n1, n2, …). */
export const hrPersonUrl = (teamId: string, personId: number | null | undefined, index: number) =>
  hrUrl(`/r/${encodeURIComponent(teamId)}/p/${personId != null ? personId : "n" + (index + 1)}`);

/**
 * "Assess the founders": hr /new with the business pre-selected (?valuation=) and, optionally, people to pre-fill
 * as repeated `person=<full name>|<role>` parameters (hr ignores what it does not read).
 */
export function hrAssessUrl(opts: { valuationId?: string | null; website?: string | null; people?: { full_name: string; role?: string | null }[] }): string {
  const q = new URLSearchParams();
  if (opts.valuationId) q.set("valuation", opts.valuationId);
  else if (opts.website) q.set("website", opts.website);
  for (const p of (opts.people ?? []).slice(0, 20)) q.append("person", `${p.full_name}|${p.role ?? ""}`);
  const s = q.toString();
  return hrUrl("/new" + (s ? "?" + s : ""));
}
