/* People rows for the founding-team review (hr.blockid.au /new and the eth /start panel) and the person report form.
   Validation mirrors studio/hr.py PersonIn: a bad value is flagged at the field where it is typed and blocks submit. */
import type { DictKey } from "../dict";
import type { PersonIn, PersonKind } from "../api";

export interface PersonRow {
  key: string;
  full_name: string;
  role: string;
  kind: PersonKind;
  full_time: "" | "yes" | "no";
  start_year: string;
  equity_pct: string;
  linkedin: string;
  links: string;
  bio: string;
}

export interface FieldErr { k: DictKey; v?: Record<string, string | number> }
export type Errs = Record<string, FieldErr>;

let seq = 0;
export function emptyRow(kind: PersonKind = "founder"): PersonRow {
  seq += 1;
  return { key: "p" + Date.now().toString(36) + seq, full_name: "", role: "", kind, full_time: "", start_year: "", equity_pct: "", linkedin: "", links: "", bio: "" };
}

export const MAX_PEOPLE = 20;
export const MAX_URLS = 6;
export const THIS_YEAR = new Date().getFullYear();

/** A public http(s) link. A bare "linkedin.com/in/x" gets https:// added; any other scheme is rejected. */
export function normUrl(raw: string): string | null {
  const s = raw.trim();
  if (!s || /\s/.test(s)) return null;
  const hasScheme = /^[a-z][a-z0-9+.-]*:/i.test(s);
  if (hasScheme && !/^https?:\/\//i.test(s)) return null;
  let u: URL;
  try { u = new URL(hasScheme ? s : "https://" + s); } catch { return null; }
  if (u.protocol !== "http:" && u.protocol !== "https:") return null;
  const h = u.hostname.toLowerCase();
  if (!/^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})$/.test(h)) return null;
  if (u.username || u.password) return null;
  return u.toString();
}

export const splitLinks = (s: string) => s.split(/[\n,]+/).map((x) => x.trim()).filter(Boolean);

export function rowUsed(r: PersonRow): boolean {
  return !!(r.full_name.trim() || r.role.trim() || r.start_year.trim() || r.equity_pct.trim() || r.linkedin.trim() || r.links.trim() || r.bio.trim());
}

const num = (s: string) => Number(s.trim().replace(",", "."));

/** Errors of one text field (used by the person form too). */
export function checkName(v: string, required: boolean): FieldErr | null {
  const s = v.trim();
  if (!s) return required ? { k: "hr.e.name" } : null;
  if (s.length > 120) return { k: "hr.e.name.long" };
  return null;
}
export function checkLinks(list: string[]): FieldErr | null {
  const bad = list.find((u) => !normUrl(u));
  if (bad) return { k: "hr.e.url", v: { u: bad.length > 48 ? bad.slice(0, 45) + "…" : bad } };
  return null;
}

/**
 * Validate the rows. `used` rows only (a fully empty row is ignored) unless none is used, then the first row must
 * be filled. Keys: `<rowKey>.<field>`, plus `team.founder`, `team.equity`, `team.max`.
 */
export function validateRows(rows: PersonRow[], opts: { requireOne: boolean }): Errs {
  const e: Errs = {};
  const used = rows.filter(rowUsed);
  const check = used.length ? used : opts.requireOne && rows[0] ? [rows[0]] : [];
  let eq = 0;
  for (const r of check) {
    const n = checkName(r.full_name, true);
    if (n) e[r.key + ".full_name"] = n;
    if (r.role.trim().length > 80) e[r.key + ".role"] = { k: "hr.e.role" };
    if (r.start_year.trim()) {
      const y = num(r.start_year);
      if (!/^\d{4}$/.test(r.start_year.trim()) || y < 1950 || y > THIS_YEAR) e[r.key + ".start_year"] = { k: "hr.e.year", v: { y: THIS_YEAR } };
    }
    if (r.equity_pct.trim()) {
      const p = num(r.equity_pct);
      if (!Number.isFinite(p) || p < 0 || p > 100) e[r.key + ".equity_pct"] = { k: "hr.e.equity" };
      else eq += p;
    }
    if (r.linkedin.trim() && !normUrl(r.linkedin)) e[r.key + ".linkedin"] = { k: "hr.e.url", v: { u: r.linkedin.trim().slice(0, 48) } };
    const links = splitLinks(r.links);
    const le = checkLinks(links);
    if (le) e[r.key + ".links"] = le;
    else if (links.length + (r.linkedin.trim() ? 1 : 0) > MAX_URLS) e[r.key + ".links"] = { k: "hr.e.urls.max" };
    if (r.bio.length > 1500) e[r.key + ".bio"] = { k: "hr.e.bio" };
  }
  if (eq > 100.0001) e["team.equity"] = { k: "hr.e.equity.total", v: { p: +eq.toFixed(2) } };
  if (check.length && !check.some((r) => r.kind === "founder" || r.kind === "cofounder")) e["team.founder"] = { k: "hr.e.founder" };
  if (used.length > MAX_PEOPLE) e["team.max"] = { k: "hr.e.max" };
  return e;
}

export function equityTotal(rows: PersonRow[]): number {
  return rows.filter(rowUsed).reduce((a, r) => { const p = num(r.equity_pct); return a + (r.equity_pct.trim() && Number.isFinite(p) ? p : 0); }, 0);
}

export function toPersonIn(r: PersonRow): PersonIn {
  const urls = [r.linkedin, ...splitLinks(r.links)].map((u) => (u.trim() ? normUrl(u) : null)).filter((u): u is string => !!u);
  return {
    full_name: r.full_name.trim(),
    role: r.role.trim(),
    kind: r.kind,
    full_time: r.full_time === "" ? null : r.full_time === "yes",
    start_year: r.start_year.trim() ? num(r.start_year) : null,
    equity_pct: r.equity_pct.trim() ? num(r.equity_pct) : null,
    urls: [...new Set(urls)].slice(0, MAX_URLS),
    bio: r.bio.trim() || null,
  };
}

/** A valuation id from an id, a /v/<id> path or a full eth.blockid.au link. */
export function parseValuationRef(raw: string): string | null {
  const s = raw.trim();
  if (!s) return null;
  const m = /\/v\/([A-Za-z0-9_-]{1,64})(?:[/?#]|$)/.exec(s);
  if (m) return m[1];
  return /^[A-Za-z0-9_-]{1,64}$/.test(s) ? s : null;
}
