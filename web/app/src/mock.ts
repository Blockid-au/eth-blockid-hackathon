/* Mock backend for ?mock=1 / VITE_MOCK=1. Mirrors the response shapes in docs/IMPLEMENTATION.md.
   State lives in memory (reset on reload) except the session, kept in sessionStorage. Lazy-loaded. */
import { getAddress, keccak256, toHex } from "viem";
import { ApiError } from "./api";
import type {
  AdminWallets, Approvals, AuditRow, CapRow, CoEvent, CompanyDetail, CompanySummary, DividendReq, Evidence, IssuerWallet, Mark, Me, MintReq, SelfReported, Stats, TickerCandidate, Valuation,
} from "./api";
import { allocate, median } from "./lib/math";
import { hrApplyToVal, hrForValuation, hrHandle, hrInit, NO_MATCH } from "./mock.hr";
import { aiHealth, aiPause, aiResume } from "./mock.ai";

const DAY = 864e5;
const NOW = Date.now();
const iso = (t: number) => new Date(t).toISOString();
const addr = (seed: string) => getAddress(keccak256(toHex(seed)).slice(0, 42) as `0x${string}`);
const txh = (seed: string) => keccak256(toHex("tx:" + seed));
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

const ADMIN_WALLETS = ["0xC40052702B48631C26AD7c88b499bF230faCa21F", "0xc309691C60957A55bB619383A06d3F69A94f4585"];
const ISSUER = "0x2567Bb502ac840cF93957C60A410160a8cCb5ddf";
const RELAYER = "0x1B43f0d3297F79cE6c8BbA12F4FadFBE9112DA4a";
const MOCK_USER = addr("mock-user-wallet");

/* ---------------- session ---------------- */
const SKEY = "blockid-mock-session";
let session: Me | null = (() => { try { return JSON.parse(sessionStorage.getItem(SKEY) || "null"); } catch { return null; } })();
const saveSession = (m: Me | null) => { session = m; try { sessionStorage.setItem(SKEY, JSON.stringify(m)); } catch { /* */ } };
let adminPassword = "admin";
let mustChange = true;
const actor = () => session?.address ?? session?.username ?? "anon";
const needUser = () => { if (!session) throw new ApiError(401, "Not signed in"); };
const needAdmin = () => { needUser(); if (session!.role !== "admin") throw new ApiError(403, "admin only"); if (session!.must_change) throw new ApiError(403, "password change required"); };
hrInit({ actor: () => actor(), needUser: () => needUser(), isAdmin: () => session?.role === "admin", valUrl: (id) => vals.get(id)?.v.url ?? null });

/* ---------------- companies ---------------- */
const NAMES = ["Maya Chen", "Tom Nguyen", "Seed Fund I", "ESOP pool", "Angels", "Priya Shah", "Liam O'Brien", "Hana Sato", "Kiwi Ventures", "Quoc Tran", "Ava Rossi", "Noah Kim", "Southern Cross Capital", "Mai Pham"];
const SEED = [
  { tk: "AGT", n: "Agritrac", g: "A", svi: 82.1, iss: 300, v0: 5.2, rv: [[180, 6.4], [60, 7.1], [12, 7.9]], h: 14, web: "agritrac.com.au" },
  { tk: "VTR", n: "Vetra Robotics", g: "A", svi: 80.4, iss: 280, v0: 6.0, rv: [[150, 7.8], [40, 9.6]], h: 11, web: "vetra.ai" },
  { tk: "MDX", n: "Medinexus", g: "B", svi: 71.4, iss: 250, v0: 4.0, rv: [[120, 4.6], [25, 5.2]], h: 9, web: "medinexus.health" },
  { tk: "FNX", n: "Finnex Pay", g: "B", svi: 68.9, iss: 330, v0: 3.1, rv: [[200, 3.6], [100, 4.0], [5, 4.4]], h: 12, web: "finnex.com.au" },
  { tk: "HBL", n: "Harbourline Logistics", g: "B", svi: 66.7, iss: 40, v0: 3.36, rv: [], h: 5, web: "harbourline.com.au" },
  { tk: "LUM", n: "Lumen Craft", g: "B", svi: 65.5, iss: 140, v0: 2.4, rv: [[35, 2.8]], h: 6, web: "lumencraft.io" },
  { tk: "SLR", n: "Solaris Grid", g: "C", svi: 58.3, iss: 210, v0: 2.6, rv: [[90, 2.3], [20, 2.1]], h: 8, web: "solarisgrid.com.au" },
  { tk: "SAI", n: "Saigon Agritech", g: "C", svi: 55.0, iss: 90, v0: 1.2, rv: [[15, 1.6]], h: 7, web: "saigonagritech.vn" },
  { tk: "KAI", n: "Kairos Edu", g: "C", svi: 52.7, iss: 160, v0: 1.5, rv: [[28, 1.4]], h: 4, web: "kairos.edu.au" },
  { tk: "OCN", n: "Oceanic Bio", g: "D", svi: 41.2, iss: 190, v0: 1.3, rv: [[110, 1.1], [9, 0.9]], h: 5, web: "oceanicbio.com" },
] as const;

interface Co {
  id: number; ticker: string; name: string; website: string; grade: string; svi: number; valuation_aud: number; total_shares: number;
  status: CompanySummary["status"]; created_at: string; created_by: string; valuation_id: string | null;
  holders: CapRow[]; marks: Mark[]; events: CoEvent[]; local: CompanyDetail["local"]; hoodi: CompanyDetail["hoodi"]; error?: string | null;
  until?: number; next?: CompanySummary["status"];
}

let nextId = 1;
const companies: Co[] = [];
function pcts(n: number): number[] {
  const w = Array.from({ length: n }, (_, i) => 1 / (i + 1.4));
  const s = w.reduce((a, b) => a + b, 0);
  const raw = w.map((x) => Math.floor((x / s) * 10000) / 100);
  raw[0] = +(raw[0] + (100 - raw.reduce((a, b) => a + b, 0))).toFixed(2);
  return raw;
}
function capTable(tk: string, total: number, n: number): CapRow[] {
  const p = pcts(n), sh = allocate(total, p);
  return p.map((x, i) => ({ name: NAMES[i % NAMES.length], wallet: i === 0 && tk === "HBL" ? MOCK_USER : addr(tk + "-holder-" + i), shares: sh[i], pct: x }));
}
function deploy(c: Co, block: number) {
  c.local = { chain_id: 262626, registry: addr(c.ticker + "reg"), token: addr(c.ticker + "tok"), distributor: addr(c.ticker + "dist"), block };
}
function anchor(c: Co, block: number, at: number) {
  c.hoodi = { chain_id: 560048, registry: addr(c.ticker + "hreg"), token: addr(c.ticker + "htok"), anchor_tx: txh(c.ticker + "anchor"), merkle_root: keccak256(toHex(c.ticker + "root" + at)), block };
}
SEED.forEach((s, k) => {
  const total = Math.round(s.v0 * 1e6), issT = NOW - s.iss * DAY;
  const c: Co = {
    id: nextId++, ticker: s.tk, name: s.n, website: "https://" + s.web, grade: s.g, svi: s.svi, valuation_aud: total, total_shares: total, status: "anchored",
    created_at: iso(issT - DAY), created_by: k === 4 ? MOCK_USER : addr("owner" + s.tk), valuation_id: "val-" + s.tk.toLowerCase(), holders: capTable(s.tk, total, s.h),
    marks: [{ at: iso(issT), mark_aud: 1, source: "issuance" }], events: [], local: null, hoodi: null,
  };
  deploy(c, 18204 - s.iss * 40);
  anchor(c, 3694512 - s.iss * 7000, issT);
  c.events.push({ kind: "issued", at: iso(issT), chain: "local", tx_hash: txh(s.tk + "iss"), block: c.local!.block, data: { shares: total } });
  c.events.push({ kind: "anchored", at: iso(issT + 3600e3), chain: "hoodi", tx_hash: c.hoodi!.anchor_tx, block: c.hoodi!.block, data: {} });
  s.rv.forEach(([d, v], i) => {
    const at = NOW - d * DAY;
    c.marks.push({ at: iso(at), mark_aud: +(v / s.v0).toFixed(4), source: "revaluation" });
    c.events.push({ kind: "revalued", at: iso(at), chain: "local", tx_hash: txh(s.tk + "rv" + i), block: 18204 - d * 40, data: { from: i ? s.rv[i - 1][1] * 1e6 : total, to: v * 1e6 } });
    c.valuation_aud = Math.round(v * 1e6);
  });
  if (s.tk === "AGT") c.events.push({ kind: "dividend_created", at: iso(NOW - 12 * DAY), chain: "local", tx_hash: txh("agtdiv"), block: 17700, data: { total_units: 120000 } });
  companies.push(c);
});

function markAt(c: Co, t: number): number | null {
  let m: number | null = null;
  for (const x of c.marks) if (+new Date(x.at) <= t) m = x.mark_aud;
  return m;
}
function curMark(c: Co) { return c.marks.length ? c.marks[c.marks.length - 1].mark_aud : 1; }
function tickStatus(c: Co) {
  if (c.until && Date.now() >= c.until && c.next) {
    const nx = c.next;
    c.status = nx; c.until = undefined; c.next = undefined;
    const t = Date.now();
    if (nx === "issued") {
      deploy(c, 18300 + companies.length);
      c.marks = [{ at: iso(t), mark_aud: 1, source: "issuance" }];
      c.events.push({ kind: "kyc", at: iso(t - 3000), chain: "local", tx_hash: txh(c.ticker + "kyc"), block: c.local!.block, data: { wallets: c.holders.length } });
      c.events.push({ kind: "drip", at: iso(t - 2000), chain: "local", tx_hash: txh(c.ticker + "drip"), block: c.local!.block, data: {} });
      c.events.push({ kind: "issued", at: iso(t - 1000), chain: "local", tx_hash: txh(c.ticker + "iss"), block: c.local!.block, data: { shares: c.total_shares } });
      c.events.push({ kind: "valuation_anchored", at: iso(t), chain: "local", tx_hash: txh(c.ticker + "va"), block: c.local!.block, data: {} });
    }
    if (nx === "anchored") {
      anchor(c, 3700000 + companies.length, t);
      c.events.push({ kind: "hoodi_mirrored", at: iso(t - 1000), chain: "hoodi", tx_hash: txh(c.ticker + "mir"), block: c.hoodi!.block, data: {} });
      c.events.push({ kind: "anchored", at: iso(t), chain: "hoodi", tx_hash: c.hoodi!.anchor_tx, block: c.hoodi!.block, data: {} });
    }
  }
}
const LIVE: CompanySummary["status"][] = ["issued", "pending_anchor", "anchoring", "anchored"];
function summary(c: Co): CompanySummary {
  tickStatus(c);
  const m = curMark(c);
  const ch = (d: number) => { const then = markAt(c, Date.now() - d * DAY) ?? c.marks[0]?.mark_aud ?? 1; return (m / then - 1) * 100; };
  return {
    id: c.id, ticker: c.ticker, name: c.name, website: c.website, grade: c.grade, svi: c.svi, valuation_aud: c.valuation_aud, total_shares: c.total_shares,
    mark_aud: m, change_7d: +ch(7).toFixed(4), change_30d: +ch(30).toFixed(4),
    spark_30d: Array.from({ length: 31 }, (_, i) => markAt(c, Date.now() - (30 - i) * DAY) ?? c.marks[0]?.mark_aud ?? 1),
    holders: c.holders.length, status: c.status, local_token: c.local?.token ?? null, hoodi_token: c.hoodi?.token ?? null, anchored: c.status === "anchored",
    created_at: c.created_at, error: c.error ?? null, valuation_id: c.valuation_id,
  };
}
function adminRow(c: Co) {
  tickStatus(c);
  return { id: c.id, ticker: c.ticker, name: c.name, website: c.website, grade: c.grade, svi: c.svi, valuation_aud: c.valuation_aud, share_price_aud: 1, total_shares: c.total_shares, status: c.status, created_by: c.created_by, created_at: c.created_at, local_token: c.local?.token ?? null, hoodi_token: c.hoodi?.token ?? null, error: c.error ?? null, valuation_id: c.valuation_id, holders: c.holders.map((h) => ({ ...h })) };
}
function detail(c: Co): CompanyDetail {
  return {
    ...summary(c), cap_table: c.holders.map((h) => ({ ...h })), cap_table_source: LIVE.includes(c.status) ? "chain" : "db", cap_table_block: c.local?.block ?? null,
    events: c.events.slice().sort((a, b) => +new Date(b.at) - +new Date(a.at)).map((e) => ({ ...e, text: e.text ?? (e.data && "shares" in e.data ? `${Number(e.data.shares).toLocaleString("en-AU")} shares` : null) })),
    marks: LIVE.includes(c.status) ? c.marks : [], local: c.local, hoodi: c.hoodi, created_by: c.created_by,
  };
}
const find = (tk: string) => companies.find((c) => c.ticker === tk.toUpperCase());
const byId = (id: number) => companies.find((c) => c.id === id);

/* ---------------- valuations ---------------- */
interface Val { v: Valuation; t0: number; decided?: boolean }
const vals = new Map<string, Val>();
const STEPS = ["read_site", "profile", "competitors", "market", "svi", "narrative"];
const DIMS = { founder_quality: 72, product_strength: 68, market_attractiveness: 74, revenue_performance: 55, growth_capability: 61, investment_readiness: 70, trust_verification: 64 };
const WEIGHTS = { founder_quality: 0.3, product_strength: 0.15, market_attractiveness: 0.15, revenue_performance: 0.15, growth_capability: 0.1, investment_readiness: 0.1, trust_verification: 0.05 };
function sviFor(host: string, dims: Record<string, number> = DIMS): Valuation["svi"] {
  const index = Object.entries(dims).reduce((a, [k, s]) => a + s * WEIGHTS[k as keyof typeof WEIGHTS], 0);
  const g = index >= 80 ? "A" : index >= 65 ? "B" : index >= 50 ? "C" : index >= 35 ? "D" : "E";
  const f = 0.5 + index / 100;
  const mid = Math.round(2_870_000 * f), low = Math.round(mid * 0.714), high = Math.round(mid * 1.28);
  return {
    index: +index.toFixed(1), band: g,
    dimensions: Object.fromEntries(Object.entries(dims).map(([k, s]) => [k, { score: s, basis: k === "revenue_performance" || k === "growth_capability" ? "computed" : "ai_suggested", rationale: `Evidence-based score for ${k} of ${host}.` }])),
    weights: WEIGHTS, valuation_low_aud: low, valuation_mid_aud: mid, valuation_high_aud: high,
    method: `revenue A$820k × cited sector multiple (2.5 · 3.5 · 4.5) × SVI factor ${f.toFixed(2)}`,
    narrative: `${host} runs a B2B logistics platform with steady recurring revenue. The founding team has prior exits and the market is growing about 9% a year (IBISWorld). Revenue concentration in two customers and a short audited history keep the score in grade ${g}.`,
  };
}
function newVal(id: string, url: string, t0: number, by: string): Val {
  const v: Valuation = { id, url, status: "queued", steps: STEPS.map((k) => ({ key: k, status: "pending", detail: null, at: null })), counters: { pages: 0, competitors: 0, sources: 0 }, profile: null, competitors: null, svi: null, error: null, requested_by: by, created_at: iso(t0) };
  const x = { v, t0 };
  vals.set(id, x);
  return x;
}
function progress(x: Val) {
  if (x.decided) { hrApplyToVal(x.v); return; }
  const el = (Date.now() - x.t0) / 1000;
  const v = x.v;
  const host = v.url.replace(/^https?:\/\//, "").replace(/\/.*$/, "");
  const done = Math.max(0, Math.min(6, Math.floor((el - 1) / 2)));
  v.status = el < 1 ? "queued" : done >= 6 ? "waiting_approval" : "running";
  v.steps = STEPS.map((k, i) => ({ key: k, status: i < done ? "done" : i === done && v.status === "running" ? "running" : "pending", detail: i < done ? ["14 pages", "Harbourline Logistics Pty Ltd", "9 found", "23 sources", "SVI 66.7", "412 words"][i] : null, at: i < done ? iso(x.t0 + (i + 1) * 2000 + 1000) : null }));
  v.counters = { pages: done > 0 ? 14 : 0, competitors: done > 2 ? 9 : 0, sources: done > 3 ? 23 : 0 };
  if (done >= 2) v.profile = { name: host.startsWith("harbourline") ? "Harbourline Logistics" : host.split(".")[0].replace(/^\w/, (c) => c.toUpperCase()), sector: "Logistics software" };
  if (done >= 3) v.competitors = [
    { name: "Shipit Freight", url: "https://shipit.example", raised_aud: 12_000_000, note: "Series B 2024", sources: 4 },
    { name: "Loadlink AU", url: "https://loadlink.example", raised_aud: 5_500_000, note: "Series A", sources: 3 },
    { name: "Freightmate", url: "https://freightmate.example", raised_aud: 3_200_000, note: "Seed + grant", sources: 2 },
    { name: "Cargo Hub", url: "https://cargohub.example", raised_aud: 1_100_000, note: "Pre-seed", sources: 2 },
    { name: "Portside Labs", url: "https://portside.example", raised_aud: null, note: "Private", sources: 1, basis: "model_suggested_verified" },
  ];
  if (done >= 5) v.svi = markSelfReported(sviFor(host), v.self_reported);
  const warn: string[] = [];
  if (v.self_reported) warn.push(SR_WARNING);
  if (done >= 3 && host.includes("nosearch")) warn.push("Search unavailable: competitors suggested by the model and verified by fetching their websites");
  v.warnings = warn.length ? warn : null;
  hrApplyToVal(v);
}
const SR_WARNING = "Includes self-reported figures (not independently verified)";
/** Same labelling as the backend: revenue/growth dimensions fed by founder figures get basis "self_reported". */
function markSelfReported(svi: Valuation["svi"], sr: SelfReported | null | undefined): Valuation["svi"] {
  if (!svi || !sr) return svi;
  const uses: Record<string, (keyof SelfReported)[]> = { revenue_performance: ["revenue_ttm_aud", "gross_margin_pct"], growth_capability: ["revenue_growth_yoy_pct", "runway_months"] };
  for (const [dim, keys] of Object.entries(uses)) {
    const used = keys.filter((k) => sr[k] != null);
    const d = svi.dimensions[dim];
    if (used.length && d) { d.basis = "self_reported"; d.rationale = `${d.rationale} (self-reported by the founder, not independently verified: ${used.join(", ")})`; }
  }
  if (sr.revenue_ttm_aud != null && svi.method) svi.method = "self-reported " + svi.method;
  return svi;
}
{
  const x = newVal("demo", "https://harbourline.com.au", NOW - 45 * DAY, MOCK_USER);
  x.v.self_reported = { revenue_ttm_aud: 820_000, revenue_growth_yoy_pct: 38, gross_margin_pct: 61, customers: 120, employees: 18 };
  x.v.team_id = "t_demo";
  progress(x); x.v.status = "approved"; x.decided = true;
  const y = newVal("val-wait", "https://brightpath.com.au", NOW - 3 * 3600e3, addr("someone"));
  progress(y);
}

/* ---------------- admin data ---------------- */
const issuerWallets: IssuerWallet[] = [
  { address: ISSUER, label: "BlockID issuer service", status: "active", granted_by: "admin", granted_at: iso(NOW - 2 * DAY) },
  { address: RELAYER, label: "Relayer (claims only)", status: "active", granted_by: "admin", granted_at: iso(NOW - 2 * DAY) },
  { address: "0x8aD1E4F0c21b9E7a33C5f6d2B19a7cE04F5b2c19", label: "Agritrac CFO", status: "revoked", granted_by: "admin", granted_at: iso(NOW - 90 * DAY), revoked_at: iso(NOW - 85 * DAY) },
];
const audit: AuditRow[] = [];
let auditId = 1;
const log = (action: string, target: string, detail: Record<string, unknown> = {}) => audit.unshift({ id: auditId++, at: iso(Date.now()), actor: actor(), action, target, detail });
log("grant_issuer", ISSUER); log("grant_issuer", RELAYER);
const mints: (MintReq & { company_id: number })[] = [];
const dividends: (DividendReq & { company_id: number })[] = [];
let reqId = 1;
{
  const f = find("FNX")!;
  mints.push({ id: reqId++, company_id: f.id, ticker: "FNX", company_name: f.name, to_wallet: addr("new-investor"), holder_name: "Blue Harbour Capital", shares: 250000, reason: "Seed extension", status: "pending", requested_by: f.created_by, created_at: iso(NOW - 3600e3) });
}

/* ---------------- stats ---------------- */
function stats(): Stats {
  const live = companies.filter((c) => { tickStatus(c); return LIVE.includes(c.status); });
  const days = Array.from({ length: 366 }, (_, i) => NOW - (365 - i) * DAY);
  const valAt = (c: Co, t: number) => { const m = markAt(c, t); return m == null ? 0 : m * c.total_shares; };
  const vals_ = live.map((c) => c.valuation_aud);
  const activity = companies.flatMap((c) => c.events.map((e) => ({ at: e.at, ticker: c.ticker, kind: e.kind, text: e.data && "shares" in e.data ? `${Number(e.data.shares).toLocaleString("en-AU")} shares` : e.kind === "revalued" ? `revalued to A$${(markAt(c, +new Date(e.at)) ?? 1).toFixed(4)}/share` : null, tx_hash: e.tx_hash ?? null, chain: e.chain ?? null })))
    .sort((a, b) => +new Date(b.at) - +new Date(a.at)).slice(0, 20);
  const movers = live.map((c) => ({ ticker: c.ticker, name: c.name, change_30d: summary(c).change_30d ?? 0 })).sort((a, b) => b.change_30d - a.change_30d);
  const grades: Record<string, number> = { A: 0, B: 0, C: 0, D: 0, E: 0 };
  live.forEach((c) => { grades[c.grade] = (grades[c.grade] ?? 0) + 1; });
  const shares = live.reduce((a, c) => a + c.total_shares, 0);
  return {
    as_of: iso(Date.now()), block: 18204 + Math.floor((Date.now() - NOW) / 6000),
    kpis: {
      companies: live.length, tokens: live.length + live.filter((c) => c.hoodi?.token).length, shares, tx_value_aud: shares * 1.04,
      total_valuation_aud: vals_.reduce((a, b) => a + b, 0), avg_valuation_aud: vals_.length ? vals_.reduce((a, b) => a + b, 0) / vals_.length : 0, median_valuation_aud: median(vals_),
      avg_mark: live.length ? live.reduce((a, c) => a + curMark(c), 0) / live.length : 1, anchored: live.filter((c) => c.status === "anchored").length, anchored_total: live.length,
    },
    series: { days: days.map((d) => iso(d).slice(0, 10)), value_aud: days.map((d) => live.reduce((a, c) => a + valAt(c, d), 0)), companies: days.map((d) => live.filter((c) => markAt(c, d) != null).length) },
    grades, movers: [...movers.slice(0, 3), ...movers.slice(-2)], activity,
  };
}

/* ---------------- router ---------------- */
type H = (m: RegExpMatchArray, body: any) => unknown; // eslint-disable-line @typescript-eslint/no-explicit-any
const routes: [string, RegExp, H][] = [
  ["GET", /^\/v1\/auth\/nonce$/, () => ({ nonce: Math.random().toString(36).slice(2, 12) })],
  ["POST", /^\/v1\/auth\/siwe$/, (_m, b) => {
    const m = /\n(0x[0-9a-fA-F]{40})\n/.exec(String(b?.message ?? ""));
    const a = m ? getAddress(m[1]) : MOCK_USER;
    const role = ADMIN_WALLETS.some((x) => x.toLowerCase() === a.toLowerCase()) ? "admin" : "user";
    saveSession({ address: a, role });
    log("login_siwe", a);
    return { address: a, role };
  }],
  ["POST", /^\/v1\/auth\/login$/, (_m, b) => {
    if (b?.username !== "admin" || b?.password !== adminPassword) throw new ApiError(401, "Wrong username or password.");
    saveSession({ username: "admin", role: "admin", must_change: mustChange });
    log("login_password", "admin");
    return { role: "admin", must_change: mustChange };
  }],
  ["POST", /^\/v1\/auth\/change-password$/, (_m, b) => {
    needUser(); if (session!.role !== "admin" || !session!.username) throw new ApiError(403, "admin password accounts only");
    if (b?.current !== adminPassword) throw new ApiError(400, "Current password is wrong.");
    if (String(b?.new ?? "").length < 10) throw new ApiError(400, "New password must be at least 10 characters.");
    adminPassword = b.new; mustChange = false; saveSession({ ...session!, must_change: false });
    log("change_password", "admin");
    return { ok: true };
  }],
  ["POST", /^\/v1\/auth\/logout$/, () => { saveSession(null); return { ok: true }; }],
  ["GET", /^\/v1\/auth\/me$/, () => {
    if (!session) throw new ApiError(401, "sign in required");
    const issuer = session.role === "admin" || issuerWallets.some((w) => w.status === "active" && w.address.toLowerCase() === String(session!.address).toLowerCase()) || session.address === MOCK_USER;
    return { ...session, issuer };
  }],
  ["GET", /^\/v1\/studio\/valuations$/, () => { needUser(); vals.forEach(progress); return [...vals.values()].filter((x) => session!.role === "admin" || x.v.requested_by === actor()).map((x) => structuredClone(x.v)).sort((a, b) => +new Date(b.created_at!) - +new Date(a.created_at!)); }],
  ["GET", /^\/v1\/studio\/companies$/, () => { needUser(); return companies.filter((c) => c.created_by === actor()).map(adminRow).reverse(); }],
  ["GET", /^\/v1\/admin\/companies$/, () => { needAdmin(); return companies.map(adminRow).reverse(); }],
  ["POST", /^\/v1\/admin\/mints\/(\d+)\/reject$/, (m) => { needAdmin(); const r = mints.find((x) => x.id === +m[1] && x.status === "pending"); if (!r) throw new ApiError(409, "not pending"); r.status = "rejected"; log("mint_rejected", String(r.id)); return { id: r.id, status: "rejected" }; }],
  ["POST", /^\/v1\/admin\/dividends\/(\d+)\/reject$/, (m) => { needAdmin(); const r = dividends.find((x) => x.id === +m[1] && x.status === "pending"); if (!r) throw new ApiError(409, "not pending"); r.status = "rejected"; log("dividend_rejected", String(r.id)); return { id: r.id, status: "rejected" }; }],

  ["POST", /^\/v1\/studio\/check-url$/, (_m, b) => {
    const raw = String(b?.url ?? "").trim();
    const url = /^https?:\/\//i.test(raw) ? raw : "https://" + raw;
    return { ok: true, url, title: "", reason: null, message: null, suggestion: null };
  }],
  ["POST", /^\/v1\/studio\/valuations$/, (_m, b) => {
    needUser();
    const id = Math.random().toString(36).slice(2, 10);
    const x = newVal(id, String(b?.url ?? ""), Date.now(), actor());
    const sr = (b?.metrics ?? null) as SelfReported | null;
    x.v.self_reported = sr && Object.keys(sr).length ? { ...sr } : null;
    if (b?.team?.people?.length) {
      if (b.team.consent !== true) throw new ApiError(422, "team.consent must be true");
      x.v.team_id = hrForValuation(id, x.v.url, b.team.people, actor());
    }
    return { id, team_id: x.v.team_id ?? null };
  }],
  ["GET", /^\/v1\/studio\/valuations\/([^/]+)$/, (m) => {
    const x = vals.get(decodeURIComponent(m[1]));
    if (!x) throw new ApiError(404, "Valuation not found");
    progress(x);
    return structuredClone(x.v);
  }],
  ["GET", /^\/v1\/studio\/valuations\/([^/]+)\/evidence$/, (m) => {
    const x = vals.get(decodeURIComponent(m[1]));
    if (!x) throw new ApiError(404, "Valuation not found");
    const n = x.v.counters?.sources ?? 0;
    const base: Evidence[] = [
      { url: "https://www.ibisworld.com/au/industry/road-freight-transport/", title: "Road Freight Transport in Australia – Market Size", snippet: "Industry revenue is expected to grow at an annualised 2.1% over the five years…", retrieved_at: iso(x.t0 + 7000) },
      { url: "https://asic.gov.au/online-services/search-asic-s-registers/", title: "ASIC Connect – company extract", snippet: "Registered 2019, proprietary company limited by shares.", retrieved_at: iso(x.t0 + 5000) },
      { url: "https://www.afr.com/companies/transport", title: "Freight-tech start-ups draw record funding", snippet: "Shipit Freight closed a A$12 million Series B…", retrieved_at: iso(x.t0 + 7400) },
      { url: x.v.url, title: "Company website – About", snippet: "We move 40,000 pallets a month for 120 customers across Australia.", retrieved_at: iso(x.t0 + 2000) },
    ];
    return n ? base : [];
  }],
  ["POST", /^\/v1\/studio\/valuations\/([^/]+)\/decision$/, (m, b) => {
    needAdmin();
    const x = vals.get(decodeURIComponent(m[1]));
    if (!x) throw new ApiError(404, "Valuation not found");
    progress(x);
    if (x.v.status !== "waiting_approval") throw new ApiError(409, "Valuation is not waiting for approval");
    x.decided = true;
    x.v.status = b?.approved ? "approved" : "rejected";
    if (b?.approved && b?.overrides && x.v.svi) {
      const dims: Record<string, number> = { ...DIMS };
      for (const [k, s] of Object.entries(b.overrides)) dims[k] = Number(s);
      x.v.svi = markSelfReported(sviFor(x.v.url.replace(/^https?:\/\//, ""), dims), x.v.self_reported);
      Object.keys(b.overrides).forEach((k) => { x.v.svi!.dimensions[k].basis = "human"; });
    }
    log(b?.approved ? "approve_valuation" : "reject_valuation", x.v.id, b?.overrides ? { overrides: b.overrides } : {});
    return structuredClone(x.v);
  }],
  ["GET", /^\/v1\/studio\/tickers\/suggest/, (_m, b) => {
    const name = String(b?.name ?? "").toUpperCase().replace(/\b(PTY|LTD|LIMITED|INC)\b/g, "").replace(/[^A-Z ]/g, "").trim() || "NEW";
    const letters = name.replace(/ /g, "");
    const cons = letters.slice(1).replace(/[AEIOU]/g, "");
    const words = name.split(/\s+/);
    const cands = [letters[0] + (cons[0] ?? "X") + (cons[1] ?? "X"), words.length > 1 ? words[0][0] + words[1][0] + (words[1][1] ?? "X") : letters.slice(0, 3), letters.slice(0, 3)];
    const seen = new Set<string>();
    const out: TickerCandidate[] = [];
    cands.forEach((t, i) => { if (!seen.has(t)) { seen.add(t); out.push({ ticker: t, available: !find(t) && t !== "HAR", rule: ["First letter + next consonants", "Initials of the first two words", "First three letters"][i] }); } });
    if (!out.some((c) => c.ticker === "HAR") && letters.startsWith("HAR")) out.push({ ticker: "HAR", available: false, rule: "Taken (Harvest Agri)" });
    return { candidates: out.sort((a, b2) => Number(b2.available) - Number(a.available)) };
  }],
  ["GET", /^\/v1\/studio\/tickers\/check/, (_m, b) => {
    const tk = String(b?.ticker ?? "").toUpperCase();
    const reason = !/^[A-Z]{3}$/.test(tk) ? "format" : ["AUD", "USD", "ASX"].includes(tk) ? "reserved" : find(tk) || tk === "HAR" ? "taken" : null;
    return { ticker: tk, ok: reason === null, reason, suggestions: reason ? ["HBL", "HLG", "HRB"].filter((x) => !find(x)) : [] };
  }],
  ["POST", /^\/v1\/studio\/companies$/, (_m, b) => {
    needUser();
    const v = vals.get(b?.valuation_id);
    if (!v || v.v.status !== "approved") throw new ApiError(400, "Valuation must be approved");
    const tk = String(b?.ticker ?? "").toUpperCase();
    if (!/^[A-Z]{3}$/.test(tk)) throw new ApiError(400, "Ticker must be 3 letters");
    if (find(tk)) throw new ApiError(409, "Ticker already used");
    const hs = (b?.holders ?? []) as { name: string; wallet: string; pct: number }[];
    const sum = hs.reduce((a, h) => a + Number(h.pct), 0);
    if (Math.abs(sum - 100) > 0.001) throw new ApiError(400, "Percentages must sum to 100.00");
    hs.forEach((h) => { if (getAddress(h.wallet) !== h.wallet) throw new ApiError(400, "Address not EIP-55: " + h.wallet); });
    const total = Number(b?.total_shares) || Math.round(v.v.svi!.valuation_mid_aud);
    const sh = allocate(total, hs.map((h) => Number(h.pct)));
    const c: Co = {
      id: nextId++, ticker: tk, name: String(b.name), website: v.v.url, grade: v.v.svi!.band, svi: v.v.svi!.index, valuation_aud: v.v.svi!.valuation_mid_aud, total_shares: total, status: "draft",
      created_at: iso(Date.now()), created_by: actor(), valuation_id: v.v.id, holders: hs.map((h, i) => ({ name: h.name, wallet: h.wallet, pct: Number(h.pct), shares: sh[i] })), marks: [], events: [], local: null, hoodi: null,
    };
    companies.push(c);
    log("create_company", tk);
    return detail(c);
  }],
  ["POST", /^\/v1\/studio\/companies\/(\d+)\/submit$/, (m) => {
    needUser();
    const c = byId(+m[1]);
    if (!c) throw new ApiError(404, "Company not found");
    const ok = session!.role === "admin" || issuerWallets.some((w) => w.status === "active" && w.address.toLowerCase() === String(session!.address).toLowerCase()) || session!.address === MOCK_USER;
    if (!ok) throw new ApiError(403, "Only admins or approved issuer wallets can submit");
    c.status = "pending_issue";
    log("submit_company", c.ticker);
    return summary(c);
  }],

  ["GET", /^\/v1\/companies$/, () => companies.filter((c) => { tickStatus(c); return LIVE.includes(c.status); }).map(summary).sort((a, b) => +new Date(b.created_at!) - +new Date(a.created_at!))],
  ["GET", /^\/v1\/companies\/([A-Za-z]{3})$/, (m) => {
    const c = find(m[1]); if (!c) throw new ApiError(404, "unknown ticker"); tickStatus(c);
    if (!LIVE.includes(c.status) && !(session && (session.role === "admin" || session.address === c.created_by))) throw new ApiError(404, "unknown ticker");
    return detail(c);
  }],
  ["POST", /^\/v1\/companies\/([A-Za-z]{3})\/mints$/, (m, b) => {
    needUser();
    const c = find(m[1]);
    if (!c) throw new ApiError(404, "Company not found");
    if (session!.role !== "admin" && session!.address !== c.created_by) throw new ApiError(403, "Only the owner or an admin can request mints");
    const r = { id: reqId++, company_id: c.id, ticker: c.ticker, company_name: c.name, to_wallet: getAddress(b.to_wallet), holder_name: b.holder_name, shares: Number(b.shares), reason: b.reason, status: "pending", requested_by: actor(), created_at: iso(Date.now()) };
    mints.push(r);
    c.events.push({ kind: "mint_requested", at: r.created_at, chain: null, tx_hash: null, data: { shares: r.shares, to: r.to_wallet } });
    log("request_mint", c.ticker, { shares: r.shares });
    return r;
  }],
  ["POST", /^\/v1\/companies\/([A-Za-z]{3})\/dividends$/, (m, b) => {
    needUser();
    const c = find(m[1]);
    if (!c) throw new ApiError(404, "Company not found");
    if (session!.role !== "admin" && session!.address !== c.created_by) throw new ApiError(403, "Only the owner or an admin can plan dividends");
    const r = { id: reqId++, company_id: c.id, ticker: c.ticker, company_name: c.name, total_units: Number(b.total_maud) * 1e6, total_maud: Number(b.total_maud), holders: c.holders.length, merkle_root: keccak256(toHex(c.ticker + b.total_maud + Date.now())), status: "pending", requested_by: actor(), created_at: iso(Date.now()) };
    dividends.push(r);
    log("request_dividend", c.ticker, { total: r.total_units });
    return r;
  }],
  ["GET", /^\/v1\/platform\/stats$/, () => stats()],

  ["GET", /^\/v1\/admin\/approvals$/, (): Approvals => {
    needAdmin();
    vals.forEach(progress);
    return {
      valuations: [...vals.values()].filter((x) => x.v.status === "waiting_approval").map((x) => structuredClone(x.v)),
      companies: companies.filter((c) => { tickStatus(c); return ["pending_issue", "issued"].includes(c.status); }).map(adminRow),
      mints: mints.filter((x) => x.status === "pending"),
      dividends: dividends.filter((x) => x.status === "pending"),
    };
  }],
  ["POST", /^\/v1\/admin\/companies\/(\d+)\/approve-issue$/, (m) => {
    needAdmin(); const c = byId(+m[1]); if (!c) throw new ApiError(404, "Company not found");
    if (c.status !== "pending_issue") throw new ApiError(409, "Company is not pending_issue");
    c.status = "issuing"; c.until = Date.now() + 5000; c.next = "issued"; log("approve_issue", c.ticker); return { ok: true };
  }],
  ["POST", /^\/v1\/admin\/companies\/(\d+)\/approve-anchor$/, (m) => {
    needAdmin(); const c = byId(+m[1]); if (!c) throw new ApiError(404, "Company not found");
    if (c.status !== "issued" && c.status !== "pending_anchor") throw new ApiError(409, "Company is not issued");
    c.status = "anchoring"; c.until = Date.now() + 5000; c.next = "anchored"; log("approve_anchor", c.ticker); return { ok: true };
  }],
  ["POST", /^\/v1\/admin\/companies\/(\d+)\/reject$/, (m, b) => { needAdmin(); const c = byId(+m[1]); if (!c) throw new ApiError(404, "Company not found"); c.status = "rejected"; c.error = b?.reason; c.events.push({ kind: "rejected", at: iso(Date.now()), data: { reason: b?.reason } }); log("reject_company", c.ticker, { reason: b?.reason }); return { ok: true }; }],
  ["POST", /^\/v1\/admin\/companies\/(\d+)\/revalue$/, (m, b) => {
    needAdmin(); const c = byId(+m[1]); if (!c) throw new ApiError(404, "Company not found");
    const nv = Number(b?.valuation_aud); if (!(nv > 0)) throw new ApiError(400, "valuation_aud must be > 0");
    const t = Date.now(), prev = c.valuation_aud;
    c.valuation_aud = nv; c.marks.push({ at: iso(t), mark_aud: +(nv / c.total_shares).toFixed(4), source: "revaluation" });
    c.events.push({ kind: "revalued", at: iso(t), chain: "local", tx_hash: txh(c.ticker + t), block: 18400, data: { from: prev, to: nv, note: b?.note } });
    log("company_revalued", c.ticker, { from: prev, to: nv, note: b?.note }); return { id: c.id, ticker: c.ticker, valuation_aud: nv, mark_aud: nv / c.total_shares, issuer: "queued" };
  }],
  ["POST", /^\/v1\/admin\/mints\/(\d+)\/approve$/, (m) => {
    needAdmin(); const r = mints.find((x) => x.id === +m[1]); if (!r) throw new ApiError(404, "Mint not found");
    const c = byId(r.company_id)!; r.status = "minted"; r.tx_hash = txh("mint" + r.id);
    const ex = c.holders.find((h) => h.wallet.toLowerCase() === r.to_wallet.toLowerCase());
    if (ex) ex.shares += r.shares; else c.holders.push({ name: r.holder_name, wallet: r.to_wallet, shares: r.shares, pct: 0 });
    c.total_shares += r.shares; c.holders.forEach((h) => { h.pct = +((h.shares / c.total_shares) * 100).toFixed(2); });
    c.marks.push({ at: iso(Date.now()), mark_aud: +(c.valuation_aud / c.total_shares).toFixed(4), source: "revaluation" });
    c.events.push({ kind: "minted", at: iso(Date.now()), chain: "local", tx_hash: r.tx_hash, block: 18410, data: { shares: r.shares, to: r.to_wallet } });
    log("approve_mint", c.ticker, { shares: r.shares }); return { ok: true };
  }],
  ["POST", /^\/v1\/admin\/dividends\/(\d+)\/approve$/, (m) => {
    needAdmin(); const r = dividends.find((x) => x.id === +m[1]); if (!r) throw new ApiError(404, "Dividend not found");
    const c = byId(r.company_id)!; r.status = "paid"; r.tx_hash = txh("div" + r.id);
    c.events.push({ kind: "dividend_created", at: iso(Date.now()), chain: "local", tx_hash: r.tx_hash, block: 18420, data: { total_units: r.total_units } });
    log("approve_dividend", c.ticker, { total: r.total_units }); return { ok: true };
  }],
  ["GET", /^\/v1\/admin\/issuer-wallets$/, () => { needAdmin(); return issuerWallets; }],
  ["POST", /^\/v1\/admin\/issuer-wallets$/, (_m, b) => {
    needAdmin();
    let a: string; try { a = getAddress(String(b?.address)); } catch { throw new ApiError(400, "Invalid address"); }
    if (issuerWallets.some((w) => w.address.toLowerCase() === a.toLowerCase() && w.status === "active")) throw new ApiError(409, "Already active");
    const w = { address: a, label: String(b?.label ?? ""), status: "active", granted_by: actor(), granted_at: iso(Date.now()) };
    issuerWallets.unshift(w); log("grant_issuer", a, { label: w.label }); return w;
  }],
  ["POST", /^\/v1\/admin\/issuer-wallets\/([^/]+)\/revoke$/, (m) => {
    needAdmin(); const a = decodeURIComponent(m[1]).toLowerCase(); const w = issuerWallets.find((x) => x.address.toLowerCase() === a);
    if (!w) throw new ApiError(404, "Not found"); w.status = "revoked"; w.revoked_at = iso(Date.now()); log("revoke_issuer", w.address, { label: w.label }); return { ok: true };
  }],
  ["GET", /^\/v1\/admin\/audit$/, () => { needAdmin(); return audit.slice(0, 200); }],
  ["GET", /^\/v1\/admin\/ai\/health$/, () => { needAdmin(); return aiHealth(); }],
  ["POST", /^\/v1\/admin\/ai\/models\/(.+)\/(pause|resume)$/, (m, b) => {
    needAdmin();
    const id = decodeURIComponent(m[1]);
    const out = m[2] === "pause" ? aiPause(id, actor(), b) : aiResume(id);
    if (!out) throw new ApiError(404, "unknown model");
    return { ok: true, model: out };
  }],
  ["GET", /^\/v1\/admin\/wallets$/, (): AdminWallets => { needAdmin(); return { admins: ADMIN_WALLETS, issuer: { address: ISSUER, local_balance: "9981.42", hoodi_balance: "3.214" }, relayer: { address: RELAYER, local_balance: "498.77", hoodi_balance: "0.412" } }; }],
];

export async function handle(method: string, path: string, body: unknown): Promise<unknown> {
  await sleep(120 + Math.random() * 180);
  const [p, qs] = path.split("?");
  const q = qs ? Object.fromEntries(new URLSearchParams(qs)) : null;
  const hr = hrHandle(method, p, body ?? q);
  if (hr !== NO_MATCH) return hr;
  for (const [m, re, h] of routes) {
    if (m !== method) continue;
    const mm = p.match(re);
    if (mm) return h(mm, body ?? q);
  }
  throw new ApiError(404, "Not found (mock)");
}
