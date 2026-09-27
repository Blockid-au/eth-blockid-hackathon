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
