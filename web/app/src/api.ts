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
}
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
  // studio
  createValuation: (url: string, metrics?: SelfReported) =>
    request<{ id: string }>("POST", "/v1/studio/valuations", metrics && Object.keys(metrics).length ? { url, metrics } : { url }),
  valuation: (id: string) => request<Valuation>("GET", `/v1/studio/valuations/${enc(id)}`),
  evidence: (id: string) => request<Evidence[]>("GET", `/v1/studio/valuations/${enc(id)}/evidence`),
  decide: (id: string, approved: boolean, overrides?: Record<string, number>) =>
    request<Valuation>("POST", `/v1/studio/valuations/${enc(id)}/decision`, overrides ? { approved, overrides } : { approved }),
  suggestTickers: (name: string) => request<{ candidates: TickerCandidate[] }>("GET", `/v1/studio/tickers/suggest?name=${enc(name)}`),
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
};
