/* Typed client for the agents-api (spec: docs/IMPLEMENTATION.md). Base path /api. */

export const API_BASE = "/api";

export type Role = "user" | "admin";
export interface Me {
  address?: string | null;
  username?: string | null;
  role: Role;
  must_change?: boolean;
  /** admin or active issuer wallet: may submit companies */
  issuer?: boolean;
  /** wallet (MetaMask) | guest (key in this browser) | google | password */
  auth_method?: "wallet" | "guest" | "google" | "password" | "demo";
  account?: { provider: string; email?: string | null; name?: string | null; picture?: string | null; wallets: string[] };
}

export interface Position {
  ticker: string;
  name: string;
  website?: string | null;
  grade?: string | null;
  shares: number;
  pct: number;
  supply: number;
  mark_aud: number;
  value_aud: number;
  issue_price_aud: number;
  change_30d: number;
  spark_30d: number[];
  holders: number;
  dividends_maud: number;
  dividends: { at: string; tx_hash?: string | null; amount_maud: number }[];
  /** dividends announced under the company's dividend policy, not paid yet (this wallet's share) */
  upcoming?: UpcomingDividend[];
  last_update_at?: string | null;
  names: string[];
}
export interface Holdings {
  wallets: string[];
  positions: Position[];
  total_value_aud: number;
  dividends_total_maud: number;
  demo?: boolean;
}
export interface AuthConfig {
  google_client_id: string | null;
  open_issue: boolean;
  mail: boolean;
}

export type ValStatus = "queued" | "running" | "waiting_approval" | "approved" | "rejected" | "failed";
export interface ValStep {
  key: string;
  status: string; // pending | running | done | failed (backend free-form)
  detail?: string | null;
  at?: string | null;
}
/** Optional founder-provided figures (POST /v1/studio/valuations `metrics`; echoed as `self_reported`). */
export interface SelfReported {
  revenue_ttm_aud?: number;
  revenue_growth_yoy_pct?: number;
  gross_margin_pct?: number;
  customers?: number;
  raised_to_date_aud?: number;
  runway_months?: number;
  employees?: number;
}
export interface Dimension {
  score: number;
  /** computed | ai_suggested | human | self_reported */
  basis?: string;
  rationale?: string;
}
export interface Svi {
  index: number;
  band: string;
  dimensions: Record<string, Dimension>;
  weights: Record<string, number>;
  valuation_low_aud: number;
  valuation_mid_aud: number;
  valuation_high_aud: number;
  method?: string;
  narrative?: string;
}
export interface Competitor {
  name: string;
  url?: string | null;
  raised_aud: number | null;
  note?: string | null;
  sources?: number | string[] | null;
  /** "search" | "model_suggested_verified" */
  basis?: string | null;
}
export interface Valuation {
  id: string;
  url: string;
  status: ValStatus;
  steps: ValStep[];
  counters?: { pages?: number; competitors?: number; sources?: number };
  profile?: { name?: string; [k: string]: unknown } | null;
  competitors?: Competitor[] | null;
  market?: unknown;
  svi?: Svi | null;
  error?: string | null;
  warnings?: string[] | null;
  self_reported?: SelfReported | null;
  requested_by?: string | null;
  created_at?: string;
  updated_at?: string;
}
export interface Evidence {
  url: string;
  title?: string | null;
  snippet?: string | null;
  retrieved_at?: string | null;
  kind?: "site" | "web" | string;
}
export interface TickerCandidate {
  ticker: string;
  available: boolean;
  rule?: string;
}
export interface HolderIn {
  name: string;
  wallet: string;
  pct: number;
}
export type CoStatus =
  | "draft" | "pending_issue" | "issuing" | "issued" | "pending_anchor" | "anchoring" | "anchored" | "partially_anchored" | "rejected" | "failed";

export type SyncState = "pending" | "running" | "done" | "failed" | "skipped";
/** Per-chain issuance/sync state (studio.companies.sync, derived for older rows). */
export interface SyncInfo {
  blockid: SyncState;
  hoodi: SyncState;
  hsk: SyncState;
  errors?: Partial<Record<"blockid" | "hoodi" | "hsk", string>>;
  step?: { chain: string; action: string; n?: number | null; of?: number | null; at?: string } | null;
  started_at?: string | null;
  updated_at?: string | null;
  finished_at?: string | null;
}
export interface ChainDeploy { chain_id?: number; registry?: string | null; token?: string | null; anchor_tx?: string | null; merkle_root?: string | null; block?: number | null; anchored_at?: string | null }

/** Server classification of an issuer error (studio/errors.py): what happened, what fixes it, where to look. */
export interface ErrorInfo {
  code: string;
  action: "refresh" | "top_up" | "configure" | "retry_item" | "approve_issue" | "resync";
  target: "cap-table" | "issuer-wallets" | "sync" | "approvals" | "tracker";
  detail?: { on_chain_in_table?: number; total_supply?: number; missing?: number };
  chains?: Record<string, ErrorInfo>;
}

export interface CompanySummary {
  id?: number;
  ticker: string;
  name: string;
  website?: string | null;
  grade?: string | null;
  svi?: number | null;
  valuation_aud: number;
  total_shares: number;
  share_price_aud?: number | null;
  mark_aud: number;
  change_7d?: number | null;
  change_30d?: number | null;
  spark_30d?: number[] | null;
  holders?: number | null;
  status: CoStatus;
  local_token?: string | null;
  hoodi_token?: string | null;
  hsk_token?: string | null;
  anchored?: boolean | null;
  sync?: SyncInfo | null;
  created_at?: string;
  error?: string | null;
  error_info?: ErrorInfo | null;
  valuation_id?: string | null;
  /** an open share offering of this business (simulated on testnet) */
  offering?: OfferingBadge | null;
}
export interface CapRow {
  name: string;
  wallet: string;
  shares: number;
  pct: number;
}
export interface CoEvent {
  id?: number;
  kind: string;
  at: string;
  chain?: string | number | null;
  tx_hash?: string | null;
  block?: number | null;
  data?: Record<string, unknown> | null;
  text?: string | null;
}
export interface Mark {
  at: string;
  mark_aud: number;
  source: string;
  valuation_aud?: number | null;
}
export interface CompanyDetail extends CompanySummary {
  cap_table: CapRow[];
  events: CoEvent[];
  marks: Mark[];
  local?: { chain_id?: number; registry?: string | null; token?: string | null; distributor?: string | null; block?: number | null } | null;
  hoodi?: ChainDeploy | null;
  hsk?: ChainDeploy | null;
  valuation_report_hash?: string | null;
  updated_at?: string;
  created_by?: string | null;
  cap_table_source?: "chain" | "db" | string;
  cap_table_block?: number | null;
}
export interface Stats {
  as_of: string;
  block?: number | null;
  kpis: {
    companies: number;
    tokens: number;
    shares: number;
    tx_value_aud: number;
    total_valuation_aud: number;
    avg_valuation_aud: number;
    median_valuation_aud: number;
    avg_mark: number;
    anchored: number;
    anchored_total: number;
  };
  series: { days: string[]; value_aud: number[]; companies: number[] };
  grades: Record<string, number>;
  movers: { ticker: string; name: string; change_30d: number }[];
  activity: { at: string; ticker?: string | null; kind: string; text?: string | null; tx_hash?: string | null; chain?: string | number | null }[];
}
export interface ApprovalCompany extends Omit<Partial<CompanySummary>, "holders"> {
  id: number;
  ticker: string;
  name: string;
  status: CoStatus;
  total_shares: number;
  valuation_aud: number;
  /** Backend may send a count or the holder rows; rows let the admin see every transaction. */
  holders?: number | { name: string; wallet: string; pct?: number; shares?: number }[] | null;
  created_by?: string | null;
}
export interface MintReq {
  id: number;
  ticker?: string;
  company_name?: string;
  company_id?: number;
  to_wallet: string;
  holder_name: string;
  shares: number;
  reason?: string | null;
  status: string; // pending | approved | minting | minted | failed | rejected
  requested_by?: string | null;
  tx_hash?: string | null;
  created_at?: string;
}
export interface DividendReq {
  id: number;
  ticker?: string;
  company_name?: string;
  company_id?: number;
  total_units: number;
  total_maud?: number;
  holders?: number;
  record_block?: number | null;
  balances_source?: string;
  tx_hash?: string | null;
  merkle_root?: string | null;
  status: string;
  requested_by?: string | null;
  created_at?: string;
}
export interface Approvals {
  valuations: Valuation[];
  companies: ApprovalCompany[];
  mints: MintReq[];
  dividends: DividendReq[];
  /** business updates waiting for a platform admin (empty for company admins) */
  updates?: BizUpdate[];
  /** dividend policies waiting for a platform admin (empty for company admins) */
  policies?: DividendPolicy[];
  /** share offerings waiting for a platform admin: to open, or to settle (empty for company admins) */
  offerings?: Offering[];
}

/* ---------- simulated share offering (studio/offerings.py) ---------- */
export type OfferingStatus = "draft" | "pending_approval" | "rejected" | "cancelled" | "open" | "awaiting_settlement" | "settling" | "settled" | "released" | "failed";
export interface OfferingBadge { id: number; status: OfferingStatus; closes_at: string }
export interface OfferingTerms {
  price_aud: number; shares_offered: number; min_raise_aud: number; max_per_investor_shares: number;
  closes_at: string; use_of_funds: string; max_holders?: number | null;
}
export interface OfferingProgress {
  reserved_shares: number; investors: number; remaining_shares: number; reserved_aud: number;
  pct_of_offer: number; pct_of_min: number; min_reached: boolean;
}
export interface PackHolder { name: string; shares: number; pct: number }
export interface OfferingPack {
  version: number;
  company: { ticker: string; name: string; website?: string | null };
  terms: OfferingTerms & { max_raise_aud: number; cooling_off_days: number; max_holders: number; price_vs_mark_pct: number | null };
  valuation: { value_aud: number; price_aud: number; as_of?: string | null; grade?: string | null; low_aud?: number | null; mid_aud?: number | null; high_aud?: number | null; confidence?: "high" | "medium" | "low" | null; report_date?: string | null; report_hash?: string | null; valuation_id?: string | null };
  updates: { id: string; title: string; cadence: string; period_label: string; published_at?: string | null; summary: string; content_hash?: string | null }[];
  cap_table: { before: { total_shares: number; holders: number; top: PackHolder[] }; after: { total_shares: number; new_shares: number; new_pct: number; top: PackHolder[] } };
  risks: string[];
  notices: string[];
  simulated: boolean;
  assembled_at: string;
}
export type ReservationStatus = "reserved" | "withdrawn" | "released" | "allocated";
export interface Reservation {
  id: number; offering_id: number; company_id: number; wallet: string; name: string; shares: number; amount_aud: number;
  status: ReservationStatus; risk_ack_at: string; cooling_off_until: string; withdrawn_at?: string | null; mint_id?: number | null;
  created_at: string; can_withdraw?: boolean;
  // /v1/me/reservations
  ticker?: string; company_name?: string; offering_status?: OfferingStatus; closes_at?: string; price_aud?: number;
}
export interface Offering extends OfferingTerms {
  id: number; company_id: number; status: OfferingStatus; cooling_off_days: number; max_raise_aud: number;
  pack?: OfferingPack | null; pack_hash?: string | null; reason?: string | null; close_reason?: string | null;
  submitted_at?: string | null; approved_at?: string | null; opened_at?: string | null; closed_at?: string | null;
  settle_approved_at?: string | null; settled_at?: string | null; error?: string | null; created_by?: string | null;
  created_at?: string; updated_at?: string;
  // public / queue views
  ticker?: string; company_name?: string; website?: string | null; grade?: string | null; holder_limit?: number;
  progress?: OfferingProgress; mine?: Reservation[]; mine_reserved_shares?: number; you_hold?: boolean;
}
export interface CompanyOfferingView {
  ticker: string; company_id: number; name: string; you: string; live: boolean;
  defaults: { price_aud: number; cooling_off_days: number; holders: number; max_holders: number; total_shares: number };
  offering: Offering | null; pack: OfferingPack | null; progress: OfferingProgress | null; reservations: Reservation[];
  history: (Offering & { progress: OfferingProgress })[];
}

/* ---------- automatic dividends (studio/dividend_policy.py) ---------- */
export interface UpcomingDividend { dividend_id: number; amount_maud: number; total_maud: number; pay_after: string; declared_at?: string; period_label?: string | null; ticker?: string; company?: string }
export type PolicyStatus = "draft" | "pending_approval" | "active" | "paused" | "rejected";
export type PolicyKind = "payout_ratio" | "fixed";
export type PolicyFrequency = "monthly" | "quarterly";
export interface DividendPolicy {
  id: number;
  company_id: number;
  kind: PolicyKind;
  ratio_pct?: number | null;
  fixed_maud?: number | null;
  max_maud_per_round: number;
  frequency: PolicyFrequency;
  veto_hours: number;
  status: PolicyStatus;
  reason?: string | null;
  active_since?: string | null;
  created_by?: string | null;
  approved_by?: string | null;
  approved_at?: string | null;
  created_at?: string;
  updated_at?: string;
  ticker?: string;
  company_name?: string;
}
export interface PolicyIn { kind: PolicyKind; ratio_pct?: number | null; fixed_maud?: number | null; max_maud_per_round: number; frequency: PolicyFrequency; veto_hours: number }
export type CoDividendStatus = "pending" | "scheduled" | "approved" | "paying" | "paid" | "failed" | "rejected" | "vetoed" | "skipped";
export interface CoDividend {
  id: number;
  company_id: number;
  total_units: number;
  total_maud: number;
  status: CoDividendStatus | string;
  source: "manual" | "policy";
  policy_id?: number | null;
  update_id?: string | null;
  pay_after?: string | null;
  approved_by?: string | null;
  requested_by?: string | null;
  note?: string | null;
  tx_hash?: string | null;
  round_id?: number | null;
  created_at: string;
  holders: number;
  period_label?: string | null;
}
export interface DividendPolicyView {
  ticker: string;
  company_id: number;
  you: string;
  live: boolean;
  policy: DividendPolicy | null;
  next: { period_end: string; period_label: string; cadence: PolicyFrequency; veto_hours: number; max_maud: number } | null;
  dividends: CoDividend[];
}
export interface PaidDividend { at: string; ticker: string; company: string; tx_hash?: string | null; wallet?: string | null; dividend_id?: number | null; amount_maud: number }
export interface DividendLedger { wallets: string[]; paid: PaidDividend[]; upcoming: UpcomingDividend[]; total_maud: number; demo?: boolean }

/* ---------- business updates (studio/updates.py) ---------- */
export type Cadence = "weekly" | "monthly" | "quarterly" | "annual";
export type UpdateStatus = "draft" | "pending_approval" | "publishing" | "published" | "rejected" | "failed";
export const METRICS = ["revenue", "gross_profit", "net_profit", "cash", "customers", "headcount"] as const;
export type Metric = (typeof METRICS)[number];
export interface UpdateKpi { metric: Metric | string; value: number; prev: number | null; change_pct: number | null; unit: "AUD" | "count" | string }
export interface UpdateBody { summary: string; highlights: string[]; risks: string[]; kpis: UpdateKpi[]; note: string }
export interface BizUpdate {
  id: string;
  ticker: string;
  company: string;
  company_id: number;
  cadence: Cadence;
  period_start: string;
  period_end: string;
  period_label: string;
  status: UpdateStatus;
  title: string;
  body: UpdateBody;
  content_hash?: string | null;
  anchor?: { chain: string; chain_id: number; tx_hash: string; block?: number | null; to?: string; content_hash?: string } | null;
  published_at?: string | null;
  created_at?: string;
  updated_at?: string;
  created_by?: string | null;
  approved_by?: string | null;
  error?: string | null;
  reason?: string | null;
  /** GET /v1/updates/{id} only: the exact canonical JSON text whose sha256 is content_hash */
  canonical?: string;
  recorded?: { chain_id: number; tag: string; calldata: string | null };
}
export interface CompanyUpdates { ticker: string; name: string; can_manage: boolean; updates: BizUpdate[] }
export interface KpiPeriods { ticker: string; metrics: { metric: Metric; unit: string }[]; periods: { period_end: string; values: Partial<Record<Metric, number>> }[] }
export interface IssuerWallet {
  address: string;
  label: string;
  status: string;
  granted_by?: string | null;
  granted_at?: string | null;
  revoked_at?: string | null;
}
export interface AuditRow {
  id: number;
  at: string;
  actor: string;
  action: string;
  target?: string | null;
  detail?: Record<string, unknown> | null;
}
export interface SvcWallet { address: string | null; local_balance?: number | string | null; hoodi_balance?: number | string | null; hsk_balance?: number | string | null }
export interface AdminWallets {
  admins: string[];
  issuer?: SvcWallet | null;
  relayer?: SvcWallet | null;
  issuer_health?: Record<string, unknown> | null;
}

/** Raw studio.companies row + holders (GET /admin/companies, /studio/companies, approvals). */
export type AdminCompany = ApprovalCompany & { local_token?: string | null; hoodi_token?: string | null; hsk_token?: string | null; error?: string | null; error_info?: ErrorInfo | null; created_at?: string; updated_at?: string };
type Val = Valuation;

/** POST /v1/studio/check-url (studio/urlcheck.py). `reason` maps to the url.<reason> dictionary keys. */
export interface UrlCheckResult { ok: boolean; url: string | null; title: string | null; reason: string | null; message: string | null; suggestion: string | null }

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/* ---------- mock switch ---------- */
const MOCK_KEY = "blockid-mock";
export const isMock: boolean = (() => {
  try {
    const q = new URLSearchParams(location.search).get("mock");
    if (q === "1") sessionStorage.setItem(MOCK_KEY, "1");
    if (q === "0") sessionStorage.removeItem(MOCK_KEY);
    return import.meta.env.VITE_MOCK === "1" || sessionStorage.getItem(MOCK_KEY) === "1";
  } catch {
    return import.meta.env.VITE_MOCK === "1";
  }
})();

type MockHandler = (method: string, path: string, body: unknown) => Promise<unknown>;
let mockHandler: Promise<MockHandler> | null = null;

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  if (isMock) {
    mockHandler ??= import("./mock").then((m) => m.handle);
    const h = await mockHandler;
    return (await h(method, path, body)) as T;
  }
  let res: Response;
  try {
    res = await fetch(API_BASE + path, {
      method,
      credentials: "same-origin",
      headers: body !== undefined ? { "Content-Type": "application/json", Accept: "application/json" } : { Accept: "application/json" },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "network");
  }
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    let msg = res.statusText || "HTTP " + res.status;
    if (data && typeof data === "object" && "detail" in data) {
      const d = (data as { detail: unknown }).detail;
      msg = typeof d === "string" ? d : Array.isArray(d) ? d.map((x) => (x && typeof x === "object" && "msg" in x ? String((x as { msg: unknown }).msg) : String(x))).join("; ") : JSON.stringify(d);
    }
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

const enc = encodeURIComponent;

export const api = {
  // auth
  nonce: () => request<{ nonce: string }>("GET", "/v1/auth/nonce"),
  siwe: (message: string, signature: string) => request<{ address: string; role: Role }>("POST", "/v1/auth/siwe", { message, signature }),
  login: (username: string, password: string) => request<{ role: Role; must_change: boolean }>("POST", "/v1/auth/login", { username, password }),
  changePassword: (current: string, next: string) => request<{ ok: boolean }>("POST", "/v1/auth/change-password", { current, new: next }),
  logout: () => request<{ ok: boolean }>("POST", "/v1/auth/logout"),
  me: () => request<Me>("GET", "/v1/auth/me"),
  demoLogin: () => request<{ address: string; role: Role }>("POST", "/v1/auth/demo"),
  authConfig: () => request<AuthConfig>("GET", "/v1/auth/config"),
  holdings: () => request<Holdings>("GET", "/v1/me/holdings"),
  demoHoldings: () => request<Holdings>("GET", "/v1/demo/holdings"),
  mailTest: (to: string) => request<{ ok: boolean }>("POST", "/v1/admin/mail/test", { to }),
  // studio
  checkUrl: (url: string) => request<UrlCheckResult>("POST", "/v1/studio/check-url", { url }),
  createValuation: (url: string, metrics?: SelfReported) =>
    request<{ id: string }>("POST", "/v1/studio/valuations", metrics && Object.keys(metrics).length ? { url, metrics } : { url }),
  valuation: (id: string) => request<Valuation>("GET", `/v1/studio/valuations/${enc(id)}`),
  evidence: (id: string) => request<Evidence[]>("GET", `/v1/studio/valuations/${enc(id)}/evidence`),
  decide: (id: string, approved: boolean, overrides?: Record<string, number>) =>
    request<Valuation>("POST", `/v1/studio/valuations/${enc(id)}/decision`, overrides ? { approved, overrides } : { approved }),
  suggestTickers: (name: string) => request<{ candidates: TickerCandidate[] }>("GET", `/v1/studio/tickers/suggest?name=${enc(name)}`),
  checkTicker: (ticker: string, name = "") =>
    request<{ ticker: string; ok: boolean; reason: "format" | "reserved" | "taken" | null; suggestions: string[] }>("GET", `/v1/studio/tickers/check?ticker=${enc(ticker)}&name=${enc(name)}`),
  createCompany: (body: { valuation_id: string; name: string; ticker: string; share_price_aud?: number; total_shares?: number; holders: HolderIn[] }) =>
    request<CompanyDetail & { id: number }>("POST", "/v1/studio/companies", body),
  submitCompany: (id: number) => request<CompanySummary>("POST", `/v1/studio/companies/${id}/submit`),
  myValuations: () => request<Val[]>("GET", "/v1/studio/valuations"),
  myCompanies: () => request<AdminCompany[]>("GET", "/v1/studio/companies"),
  // public
  companies: () => request<CompanySummary[]>("GET", "/v1/companies"),
  company: (ticker: string) => request<CompanyDetail>("GET", `/v1/companies/${enc(ticker)}`),
  requestMint: (ticker: string, body: { to_wallet: string; holder_name: string; shares: number; reason: string }) =>
    request<MintReq>("POST", `/v1/companies/${enc(ticker)}/mints`, body),
  requestDividend: (ticker: string, total_maud: number) => request<DividendReq>("POST", `/v1/companies/${enc(ticker)}/dividends`, { total_maud }),
  stats: () => request<Stats>("GET", "/v1/platform/stats"),
  // admin
  approvals: () => request<Approvals>("GET", "/v1/admin/approvals"),
  adminCompanies: () => request<AdminCompany[]>("GET", "/v1/admin/companies"),
  rejectMint: (id: number, reason: string) => request<unknown>("POST", `/v1/admin/mints/${id}/reject`, { reason }),
  rejectDividend: (id: number, reason: string) => request<unknown>("POST", `/v1/admin/dividends/${id}/reject`, { reason }),
  approveIssue: (id: number) => request<unknown>("POST", `/v1/admin/companies/${id}/approve-issue`),
  approveAnchor: (id: number) => request<unknown>("POST", `/v1/admin/companies/${id}/approve-anchor`),
  /** Clear the error, rebuild the cap table from BlockID Chain balances, re-sync Hoodi + HSK. */
  refreshCompany: (id: number) => request<unknown>("POST", `/v1/admin/companies/${id}/refresh`),
  rejectCompany: (id: number, reason: string) => request<unknown>("POST", `/v1/admin/companies/${id}/reject`, { reason }),
  revalue: (id: number, valuation_aud: number, note: string) => request<{ mark_aud: number; issuer?: string; valuation_aud?: number }>("POST", `/v1/admin/companies/${id}/revalue`, { valuation_aud, note }),
  approveMint: (id: number) => request<unknown>("POST", `/v1/admin/mints/${id}/approve`),
  approveDividend: (id: number) => request<unknown>("POST", `/v1/admin/dividends/${id}/approve`),
  issuerWallets: () => request<IssuerWallet[]>("GET", "/v1/admin/issuer-wallets"),
  addIssuerWallet: (address: string, label: string) => request<IssuerWallet>("POST", "/v1/admin/issuer-wallets", { address, label }),
  revokeIssuerWallet: (address: string) => request<unknown>("POST", `/v1/admin/issuer-wallets/${enc(address)}/revoke`),
  audit: () => request<AuditRow[]>("GET", "/v1/admin/audit"),
  adminWallets: () => request<AdminWallets>("GET", "/v1/admin/wallets"),
  // business updates
  companyUpdates: (ticker: string) => request<CompanyUpdates>("GET", `/v1/companies/${enc(ticker)}/updates`),
  update: (id: string) => request<BizUpdate>("GET", `/v1/updates/${enc(id)}`),
  myUpdates: () => request<{ updates: BizUpdate[] }>("GET", "/v1/me/updates"),
  demoUpdates: () => request<{ updates: BizUpdate[] }>("GET", "/v1/demo/updates"),
  kpis: (ticker: string) => request<KpiPeriods>("GET", `/v1/companies/${enc(ticker)}/kpis`),
  putKpis: (ticker: string, period_end: string, values: Partial<Record<Metric, number | null>>) =>
    request<KpiPeriods>("PUT", `/v1/companies/${enc(ticker)}/kpis`, { period_end, values }),
  prepareUpdate: (ticker: string, body: { cadence: Cadence; period_end: string; kpis?: Partial<Record<Metric, number | null>>; note?: string }) =>
    request<BizUpdate>("POST", `/v1/companies/${enc(ticker)}/updates`, body),
  editUpdate: (id: string, body: { title?: string; summary?: string; note?: string; highlights?: string[]; risks?: string[] }) =>
    request<BizUpdate>("PATCH", `/v1/updates/${enc(id)}`, body),
  submitUpdate: (id: string) => request<BizUpdate>("POST", `/v1/updates/${enc(id)}/submit`),
  approveUpdate: (id: string) => request<{ id: string; status: string; content_hash: string }>("POST", `/v1/admin/updates/${enc(id)}/approve`),
  rejectUpdate: (id: string, reason: string) => request<BizUpdate>("POST", `/v1/admin/updates/${enc(id)}/reject`, { reason }),
  // automatic dividends
  dividendPolicy: (ticker: string) => request<DividendPolicyView>("GET", `/v1/companies/${enc(ticker)}/dividend-policy`),
  saveDividendPolicy: (ticker: string, body: PolicyIn) => request<DividendPolicyView>("PUT", `/v1/companies/${enc(ticker)}/dividend-policy`, body),
  policyAction: (ticker: string, action: "submit" | "pause" | "resume") => request<DividendPolicyView>("POST", `/v1/companies/${enc(ticker)}/dividend-policy/${action}`),
  vetoDividend: (ticker: string, id: number, reason = "") => request<DividendPolicyView>("POST", `/v1/companies/${enc(ticker)}/dividends/${id}/veto`, { reason }),
  approvePolicy: (id: number) => request<DividendPolicy>("POST", `/v1/admin/dividend-policies/${id}/approve`),
  rejectPolicy: (id: number, reason: string) => request<DividendPolicy>("POST", `/v1/admin/dividend-policies/${id}/reject`, { reason }),
  myDividends: () => request<DividendLedger>("GET", "/v1/me/dividends"),
  // simulated share offering
  companyOffering: (ticker: string) => request<CompanyOfferingView>("GET", `/v1/companies/${enc(ticker)}/offering`),
  saveOffering: (ticker: string, body: OfferingTerms) => request<CompanyOfferingView>("PUT", `/v1/companies/${enc(ticker)}/offering`, body),
  offeringAction: (ticker: string, action: "submit" | "cancel" | "close") => request<CompanyOfferingView>("POST", `/v1/companies/${enc(ticker)}/offering/${action}`),
  offerings: () => request<{ offerings: Offering[]; simulated: boolean }>("GET", "/v1/offerings"),
  offering: (id: number | string) => request<Offering>("GET", `/v1/offerings/${enc(String(id))}`),
  reserve: (id: number, body: { shares?: number; amount_aud?: number; risk_ack: boolean; name?: string }) =>
    request<{ reservation: Reservation; offering: Offering }>("POST", `/v1/offerings/${id}/reservations`, body),
  withdrawReservation: (id: number, rid: number) => request<{ reservation: Reservation }>("POST", `/v1/offerings/${id}/reservations/${rid}/withdraw`),
  myReservations: () => request<{ reservations: Reservation[] }>("GET", "/v1/me/reservations"),
  approveOffering: (id: number) => request<Offering>("POST", `/v1/admin/offerings/${id}/approve`),
  rejectOffering: (id: number, reason: string) => request<Offering>("POST", `/v1/admin/offerings/${id}/reject`, { reason }),
  closeOfferingAdmin: (id: number) => request<unknown>("POST", `/v1/admin/offerings/${id}/close`),
  settleOffering: (id: number) => request<{ id: number; status: string; investors: number; shares: number }>("POST", `/v1/admin/offerings/${id}/settle`),
  releaseOffering: (id: number, reason: string) => request<unknown>("POST", `/v1/admin/offerings/${id}/release`, { reason }),
  demoDividends: () => request<DividendLedger>("GET", "/v1/demo/dividends"),
};
