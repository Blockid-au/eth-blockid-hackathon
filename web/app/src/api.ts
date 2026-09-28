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
  /** founding-team review linked to this valuation (studio/hr.py) and its public-safe summary */
  team_id?: string | null;
  team?: TeamSummary | null;
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
  /** POST /v1/companies/{tk}/dividends: mAUD units (6 decimals) that stay with the company after rounding */
  remainder_units?: number;
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
  ticker?: string; company_name?: string; website?: string | null; grade?: string | null; holder_limit?: number | null;
  /** admin queue, offerings to settle: shareholders on BlockID Chain now, the token's cap (null = no limit), after settling */
  register?: { count: number; cap: number | null; new: number; other_pending: number; after: number; fits: boolean } | null;
  progress?: OfferingProgress; mine?: Reservation[]; mine_reserved_shares?: number; you_hold?: boolean;
}
export interface CompanyOfferingView {
  ticker: string; company_id: number; name: string; you: string; live: boolean;
  /** holders / max_holders: read from the share token on BlockID Chain when possible; max_holders null = no limit */
  defaults: { price_aud: number; cooling_off_days: number; holders: number; max_holders: number | null; total_shares: number; max_days_open?: number };
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
  /** announced (scheduled) payments: still paid after a pause or change unless cancelled */
  announced?: { id: number; total_maud: number; pay_after: string | null }[];
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
export interface KpiPeriods { ticker: string; metrics: { metric: Metric; unit: string }[]; periods: { cadence?: Cadence; period_end: string; values: Partial<Record<Metric, number>> }[] }
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

/* ---------- founding team + person review (studio/hr.py, served on hr.blockid.au) ---------- */
export type PersonKind = "founder" | "cofounder" | "executive" | "employee" | "advisor";
export const PERSON_KINDS: PersonKind[] = ["founder", "cofounder", "executive", "employee", "advisor"];
export interface PersonIn {
  full_name: string;
  role: string;
  kind: PersonKind;
  headline?: string | null;
  full_time?: boolean | null;
  start_year?: number | null;
  equity_pct?: number | null;
  urls?: string[];
  bio?: string | null;
  cv?: string | null;
}
export type HrTarget =
  | { type: "business"; valuation_id?: string | null; ticker?: string | null; website?: string | null }
  | { type: "role"; company: string; title: string; description: string; requirements: string[]; min_years?: number | null; seniority?: HrSeniority | null; knockouts?: string[] };
export type HrSeniority = "entry" | "mid" | "senior" | "lead" | "executive";
/** Wording in a JD that touches a protected attribute (AU law): shown as a warning, left out of scoring. */
export interface HrFlagged { text: string; reason: string }
/** POST /v1/hr/jd/parse {text} (docs/PLAN-HR-V3.md §2.2, §9). */
export interface HrJdParse {
  title?: string | null; seniority?: HrSeniority | string | null; min_years?: number | null; domain?: string | null;
  must?: string[]; nice?: string[]; knockouts?: string[]; skills?: string[]; flagged?: HrFlagged[];
}
export type HrTargetView =
  | { type: "business"; valuation_id?: string | null; ticker?: string | null; website?: string | null; company?: string | null; sector?: string | null; stage?: string | null; description?: string | null }
  | { type: "role"; company?: string | null; title?: string | null; description?: string | null; requirements?: string[]; min_years?: number | null; seniority?: string | null; knockouts?: string[]; flagged?: HrFlagged[] };
export type TeamStatus = "draft" | "queued" | "running" | "done" | "failed";
export type HrMode = "team" | "person";
export type TeamFunction = "tech" | "commercial" | "domain" | "finance";
export const SUBSCORE_KEYS = ["domain_fit", "track_record", "leadership", "functional_depth", "verifiability", "commitment"] as const;
export const FIT_KEYS = ["skills_match", "domain_match", "stage_scale_match", "seniority_match", "track_record_relevance", "gaps"] as const;
export const TEAM_COMPONENTS = ["complementarity", "key_roles", "worked_together", "advisors_board", "concentration"] as const;
export interface TeamStep { at: string; step: string; person?: string | null; msg: string }
/** Live progress (docs/PLAN-HR-V2.md §1). Present on GET /v1/hr/teams/{id} and /v1/hr/people-reports/{id}. */
export type HrPhase = "queued" | "reading" | "searching" | "extracting" | "scoring" | "done" | "failed" | "stalled";
export interface HrFeedItem { at: string; level: "info" | "found" | "warn"; msg: string; person?: string | null; source?: string | null }
export interface HrPartialPerson {
  id: number; name: string; status: "waiting" | "working" | "done" | "failed";
  facts: PersonFact[]; score?: number | null; fit?: number | null; grade?: string | null;
}
export interface HrProgress {
  phase: HrPhase;
  pct: number; // 0..100, monotonic
  eta_s: number | null;
  started_at: string | null;
  updated_at: string | null; // heartbeat
  current: { person: string | null; step: string; detail: string };
  feed: HrFeedItem[]; // newest last, <= 60
  counters: { pages_read: number; searches: number; facts_verified: number; facts_unconfirmed: number; people_done: number; people_total: number };
  partial: { people: HrPartialPerson[] };
}
/** GET /v1/hr/suggest-people?valuation_id=… | ?website=… */
export interface HrSuggestedPerson { full_name: string; role: string; kind?: PersonKind; source_url: string | null }
export interface HrSuggestions { website: string | null; source: "site_intake" | "fetched" | "none"; people: HrSuggestedPerson[] }
export interface TeamPerson extends PersonIn { id: number; position: number; has_cv?: boolean }
export interface PersonSubScore { score: number; suggested?: number; capped?: boolean; weight: number; rationale?: string; fact_ids?: string[]; self_reported?: boolean }
export interface PersonFact { id: string; text: string; quote?: string; source_id?: string; url?: string; category?: string }
export interface CvSource { type: "verified" | "self_reported" | string; fact_ids?: string[]; urls?: string[] }
export interface CvProfile {
  headline?: { text: string; source?: CvSource } | null;
  location?: { text: string; source?: CvSource } | null;
  summary?: string | null;
  experience?: { org: string; title?: string | null; start?: string | null; end?: string | null; achievements?: string[]; source?: CvSource }[];
  education?: { institution: string; degree?: string | null; field?: string | null; start?: string | null; end?: string | null; source?: CvSource }[];
  skills?: { group: string; items: string[]; source?: CvSource }[];
  ventures?: { name: string; role?: string | null; outcome?: "exit" | "acquired" | "ipo" | "active" | "closed" | "unknown" | string; year?: number | string | null; source?: CvSource }[];
  publications?: { title: string; kind?: "publication" | "patent" | "talk" | string; venue?: string | null; year?: number | string | null; source?: CvSource }[];
  awards?: { title: string; year?: number | string | null; source?: CvSource }[];
  links?: { url: string; label?: string | null }[];
  completeness_pct?: number | null;
}
/** Evidence level of a requirement row (hr-2): verified facts · the CV only · a source contradicts the CV · nothing. */
export type FitEvidence = "verified" | "cv_only" | "contradicted" | "none";
export interface FitRequirement { requirement: string; must_have?: boolean; status: "matched" | "partial" | "missing" | "unverified" | string; fact_ids?: string[]; self_reported?: boolean; note?: string | null; evidence?: FitEvidence | string; claim_ids?: string[] }
export type FitLens = "business" | "jd" | "current_role";
export type FitVerdict = "strong" | "conditional" | "weak" | "not_suitable";
export interface FitRelevantRole { org: string; title: string; relevance: "high" | "medium" | "low" | string; reason?: string; months?: number | null }
export interface PersonFit {
  target_type: "business" | "role";
  label?: string;
  score: number;
  components: Record<string, PersonSubScore>;
  requirements?: FitRequirement[];
  matched?: string[];
  missing?: string[];
  risks?: string[];
  interview_questions?: string[];
  /* hr-2 (docs/PLAN-HR-V3.md §9); all optional so hr-1 reports still render */
  lens?: FitLens;
  title?: string;
  claimed_score?: number | null;
  verified_score?: number | null;
  verdict?: FitVerdict | string;
  knockouts?: string[];
  cap?: number | null;
  relevant?: { years: number; min_years?: number | null; roles?: FitRelevantRole[] } | null;
  template?: { key: string; label: string; stage_band?: string | null } | null;
  alt_role?: { role: string; score: number; reason?: string | null } | null;
}
export type TrustBand = "high" | "medium" | "low";
/** CV Trust Index (hr-2). score is null on share / holder views (bands only). */
export interface PersonTrust {
  score: number | null;
  band: TrustBand | string;
  coverage_pct?: number | null;
  contradicted_key?: number;
  consistency?: { overlaps?: number; date_issues?: number } | null;
}
export type DecisionQuadrant = "proceed" | "verify_first" | "other_role" | "stop";
export interface PersonDecision { quadrant: DecisionQuadrant | string; fit_lens?: FitLens | string; fit_score?: number | null; trust_band?: TrustBand | string | null; reasons?: string[]; verify?: string[] }
export interface PersonCard {
  person_id: number;
  full_name: string;
  role: string;
  kind: PersonKind;
  multiplier?: number;
  score: number;
  subscores: Record<string, PersonSubScore>;
  fit?: PersonFit | null;
  contribution?: number;
  profile?: CvProfile | null;
  facts: PersonFact[];
  self_reported?: { headline?: string | null; bio?: string | null; full_time?: boolean | null; equity_pct?: number | null; start_year?: number | null; has_cv?: boolean } | null;
  unconfirmed: { text: string; quote?: string | null; url?: string | null; reason?: string }[];
  strengths: string[];
  gaps: string[];
  questions: string[];
  functions: TeamFunction[];
  model?: string | null;
  /* hr-2 */
  fits?: Partial<Record<FitLens, PersonFit>> | null;
  trust?: PersonTrust | null;
  decision?: PersonDecision | null;
}
export interface TeamBlock {
  score: number;
  grade: string;
  people_component?: number;
  team_component?: number;
  red_flag_penalty?: number;
  components: Record<string, number>;
  component_detail?: Record<string, { score?: number; rationale?: string; fact_ids?: string[]; computed?: boolean }>;
  coverage: Record<TeamFunction, boolean>;
  strengths: string[];
  gaps: string[];
  risks: string[];
  questions: string[];
  red_flags?: { text: string; fact_ids?: string[] }[];
}
export interface HrSource { id: string; url: string; title?: string | null; sha256?: string | null; kind?: string; fetched_at?: string | null; person_id?: number | null }
export interface TeamReport {
  version: string;
  mode?: HrMode;
  team: TeamBlock | null;
  people: PersonCard[];
  method?: {
    person_weights?: Record<string, number>; fit_weights?: Record<string, number>; team_weights?: Record<string, number>;
    role_multipliers?: Record<string, number>; contribution?: string; cap_without_evidence?: number; notes?: string[];
    models?: Record<string, string>; search_providers?: string[];
  } | null;
  sources: HrSource[];
  counters?: Partial<Record<"searches" | "search_budget" | "pages_fetched" | "facts_verified" | "facts_unconfirmed" | "facts_dropped_sensitive" | "llm_calls", number>> | null;
  created_at?: string;
}
/** ReportOut: a team report (mode "team") or a person report (mode "person"). */
export interface Team {
  id: string;
  mode?: HrMode;
  name: string;
  website?: string | null;
  valuation_id?: string | null;
  company_id?: number | null;
  target?: HrTargetView | null;
  status: TeamStatus;
  error?: string | null;
  consent?: boolean;
  consented_at?: string | null;
  is_demo?: boolean;
  created_at?: string;
  updated_at?: string;
  mine?: boolean;
  can_edit?: boolean;
  share_token?: string | null;
  report_url?: string;
  steps: TeamStep[];
  people: TeamPerson[];
  result?: TeamReport | null;
  progress?: HrProgress | null;
}
export interface TeamSummary {
  id: string;
  mode?: HrMode;
  name: string;
  status: TeamStatus;
  valuation_id?: string | null;
  score: number | null;
  grade: string | null;
  people: {
    id?: number; full_name: string; role: string; kind: PersonKind; score: number | null; fit?: number | null;
    /** fit to THIS business: label, matched/missing requirements (top 3) */
    fit_label?: string | null; fit_matched?: string[]; fit_missing?: string[];
    status?: HrPartialPerson["status"]; url?: string | null; // url = hr link to the person inside the team report (/r/<team>/p/<pid>)
    /** hr-2: CV trust band and the fit to the role the person holds now */
    trust_band?: TrustBand | string | null; role_fit?: number | null; role_fit_verdict?: FitVerdict | string | null;
  }[];
  strengths: string[];
  gaps: string[];
  url?: string;
  progress?: { phase: HrPhase; pct: number; eta_s: number | null; updated_at?: string | null } | null;
  confidence?: "high" | "medium" | "low" | null; // share of weighted points backed by verified facts
  error?: string | null; // failure reason when status is "failed"
  /** on a valuation's `team` only */
  applied?: boolean; reason?: string | null; applied_at?: string | null;
}
export interface TeamListItem {
  id: string;
  mode?: HrMode;
  name: string;
  status: TeamStatus;
  valuation_id?: string | null;
  company_id?: number | null;
  score: number | null;
  grade: string | null;
  people_count: number;
  target_type?: "business" | "role" | null;
  created_at?: string;
  updated_at?: string;
}
const shareQ = (share?: string | null) => (share ? `?share=${encodeURIComponent(share)}` : "");
const hrApi = {
  hrCreateTeam: (body: { name: string; website?: string | null; valuation_id?: string | null; people: PersonIn[]; consent: true; run?: boolean }) =>
    request<Team>("POST", "/v1/hr/teams", body),
  hrCreatePersonReport: (body: { person: PersonIn; target: HrTarget | null; consent: true; run?: boolean }) =>
    request<Team>("POST", "/v1/hr/people-reports", body),
  hrSetPeople: (id: string, people: PersonIn[]) => request<Team>("PUT", `/v1/hr/teams/${enc(id)}/people`, { people }),
  hrSetTarget: (id: string, target: HrTarget | null) => request<Team>("PUT", `/v1/hr/teams/${enc(id)}/target`, { target }),
  hrRun: (id: string) => request<Team>("POST", `/v1/hr/teams/${enc(id)}/run`),
  hrTeam: (id: string, share?: string | null) => request<Team>("GET", `/v1/hr/teams/${enc(id)}${shareQ(share)}`),
  hrMyTeams: () => request<{ teams: TeamListItem[] }>("GET", "/v1/hr/teams?mine=1"),
  hrTeamSummary: (id: string, share?: string | null) => request<TeamSummary>("GET", `/v1/hr/teams/${enc(id)}/summary${shareQ(share)}`),
  hrDeletePerson: (pid: number) => request<{ ok: boolean; team_id: string }>("DELETE", `/v1/hr/people/${pid}`),
  hrDeleteReport: (id: string) => request<{ ok: boolean }>("DELETE", `/v1/hr/teams/${enc(id)}`),
  hrShare: (id: string) => request<{ share_token: string }>("POST", `/v1/hr/teams/${enc(id)}/share`),
  hrUnshare: (id: string) => request<{ ok: boolean }>("DELETE", `/v1/hr/teams/${enc(id)}/share`),
  hrSuggestPeople: (q: { valuation_id?: string | null; website?: string | null }) =>
    request<HrSuggestions>("GET", `/v1/hr/suggest-people?${q.valuation_id ? "valuation_id=" + encodeURIComponent(q.valuation_id) : "website=" + encodeURIComponent(q.website ?? "")}`),
  /** Read a pasted JD into title / must / nice / knockouts (rate-limited; callers fall back to the keyword helper). */
  hrParseJd: (text: string) => request<HrJdParse>("POST", "/v1/hr/jd/parse", { text }),
  hrApplyToValuation: (id: string) => request<{ applied: boolean; reason: string | null }>("POST", `/v1/hr/teams/${enc(id)}/apply-to-valuation`),
};

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
  createValuation: (url: string, metrics?: SelfReported, team?: { people: PersonIn[]; consent: true }) =>
    request<{ id: string; team_id?: string | null }>("POST", "/v1/studio/valuations", {
      url, ...(metrics && Object.keys(metrics).length ? { metrics } : {}), ...(team && team.people.length ? { team } : {}),
    }),
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
  putKpis: (ticker: string, period_end: string, values: Partial<Record<Metric, number | null>>, cadence: Cadence = "monthly") =>
    request<KpiPeriods>("PUT", `/v1/companies/${enc(ticker)}/kpis`, { cadence, period_end, values }),
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
  ...hrApi,
};


/* ---------- operations: incidents, errors, usage, weekly report (docs/PLAN-OPS.md) ----------
   Wire shapes = agents/src/blockid_agents/ops/__init__.py docstring (Raw*). opsApi maps them to the view types the
   admin screen uses (pages/Ops.tsx), so backend field renames only touch this block. */
export type OpsSeverity = "info" | "warn" | "critical";
export type OpsIncidentStatus = "open" | "acknowledged" | "resolved";
export type OpsMailStatus = "sent" | "failed" | "pending" | "not_configured";

export interface RawOpsIncident {
  id: number; check_id: string; fingerprint?: string | null; title: string; severity: OpsSeverity; status: OpsIncidentStatus;
  detail?: string | null; impact?: string | null; fix_steps?: string[] | null; runbook_id?: string | null; runbook_url?: string | null;
  opened_at: string; last_seen_at?: string | null; occurrences?: number | null;
  acknowledged_at?: string | null; acknowledged_by?: string | null; resolved_at?: string | null; resolved_by?: string | null;
  emailed?: boolean | null; email_reason?: string | null; last_emailed_at?: string | null; data?: Record<string, unknown> | null;
  events?: { id?: number; at: string; kind: string; actor?: string | null; detail?: string | null }[];
}
export interface RawOpsCheck {
  id: string; title: string; severity: OpsSeverity; status: "ok" | "warn" | "critical" | "info" | "unknown" | string; detail?: string | null;
  last_run_at?: string | null; last_ok_at?: string | null; incident_id?: number | null; runbook_id?: string | null; runbook_url?: string | null;
}
export interface RawOpsReport {
  id: number; kind: "weekly" | "daily" | string; period_start: string; period_end?: string | null; created_at: string; subject?: string | null;
  to?: string | null; emailed?: boolean | null; email_reason?: string | null; sent_at?: string | null; trigger?: string | null;
  html?: string | null; text?: string | null;
}
export interface RawOpsSummary {
  generated_at: string; enabled?: boolean; leader?: boolean; last_run_at: string | null; smtp_configured: boolean;
  alert_to?: string | null; report_to?: string | null; unsent_emails?: number | null;
  open_incidents: Partial<Record<OpsSeverity | "total", number>>; checks?: RawOpsCheck[]; errors_24h?: number | null;
  traffic_today?: { page_views: number; unique_visitors: number; requests: number; status_5xx: number } | null;
  last_report?: { id: number; kind: string; created_at: string; emailed: boolean; email_reason?: string | null } | null;
}
export interface RawOpsTrafficDay {
  day: string; host: string; page_views: number; unique_visitors: number; requests?: number; bot_requests?: number; api_requests?: number;
  status_4xx?: number; status_5xx?: number; top_pages?: { path: string; views: number }[] | null;
  top_referrers?: { referrer: string; count: number }[] | null; countries?: { country: string; count: number }[] | null;
}
export interface RawOpsTraffic {
  days: number; source?: "nginx" | "unavailable" | string; last_parsed_at?: string | null; hosts?: string[]; daily: RawOpsTrafficDay[];
  totals?: { page_views: number; unique_visitors: number; requests: number; bot_requests: number; status_5xx: number } | null;
}
export interface RawOpsError {
  id?: number; fingerprint: string; source?: string | null; logger?: string | null; level?: string | null; message: string;
  traceback?: string | null; count: number; first_seen: string; last_seen: string; request_id?: string | null; route?: string | null;
}
/** GET /stats is used as-is. */
export interface OpsStats {
  generated_at: string; days: number;
  accounts: { total: number; new_7d: number; new_period: number };
  wallets: { linked_total: number; signed_in_7d: number; signed_in_period: number };
  sign_ins: { "7d": Record<string, number>; period: Record<string, number> };
  active_users: { d1?: number; d7: number; d30: number };
  registrations_daily: { day: string; accounts: number; wallets: number }[];
  valuations: { started_7d: number; finished_7d: number; failed_7d: number; started_period: number; finished_period: number; failed_period: number; running: number };
  hr: { teams_7d: number; done_7d: number; failed_7d: number; teams_period: number };
  companies: { total: number; created_7d: number; by_status?: Record<string, number> };
  offerings: { total: number; open: number; created_7d: number };
  dividends: { total: number; created_7d: number; paid_7d: number };
  admin_actions_7d?: number;
}

/* view types */
export interface OpsTimelineItem { at: string; kind: string; text?: string | null; by?: string | null }
export interface OpsEmailLog { at: string; kind: string; to?: string | null; status: OpsMailStatus; error?: string | null }
export interface OpsIncident {
  id: number; check_id: string; fingerprint?: string | null; title: string; severity: OpsSeverity; status: OpsIncidentStatus;
  opened_at: string; last_seen_at: string | null; count: number; summary?: string | null; impact?: string | null;
  acked_at?: string | null; acked_by?: string | null; resolved_at?: string | null; resolved_by?: string | null;
  runbook_id?: string | null; runbook_url?: string | null; runbook_steps?: string[] | null;
  email_status: OpsMailStatus | null; email_reason?: string | null;
  details?: Record<string, unknown> | null; timeline?: OpsTimelineItem[] | null; emails?: OpsEmailLog[] | null;
}
export interface OpsSummary {
  generated_at: string; enabled: boolean; leader: boolean | null; last_check_at: string | null; checks: RawOpsCheck[];
  open_incidents: Record<OpsSeverity, number>; errors_24h: number | null; traffic_today: RawOpsSummary["traffic_today"];
  email: { configured: boolean; to: string | null; report_to: string | null; pending: number | null };
  last_report: RawOpsSummary["last_report"];
}
export interface OpsError {
  fingerprint: string; count: number; first_seen: string; last_seen: string; route: string | null; method: string | null;
  service: string | null; logger: string | null; level: string | null; message: string; stack: string | null; request_id: string | null;
}
export interface OpsTrafficDay { date: string; host: string; page_views: number; visitors: number }
export interface OpsTraffic {
  days: number; available: boolean; hosts: string[]; daily: OpsTrafficDay[]; updated_at: string | null; bots_filtered: number | null;
  top_pages: { host: string; path: string; views: number }[]; referrers: { referrer: string; views: number }[]; countries: { country: string; views: number }[];
}
export interface OpsReport {
  id: number; kind: string; week_start: string; week_end: string | null; created_at: string; sent_at: string | null; trigger: string | null;
  status: OpsMailStatus; to: string | null; subject: string | null; error: string | null; html?: string | null; text?: string | null;
}
export interface OpsSendResult { sent: boolean; status: OpsMailStatus; id: number | null; to: string | null; error: string | null }

const mailStatus = (emailed: boolean | null | undefined, reason: string | null | undefined): OpsMailStatus =>
  emailed ? "sent" : !reason || reason === "pending" ? "pending" : /smtp not configured/i.test(reason) ? "not_configured" : "failed";
const MAIL_EVENTS: Record<string, OpsMailStatus> = { emailed: "sent", email_failed: "failed", reminder: "sent" };
function toIncident(r: RawOpsIncident): OpsIncident {
  const ev = r.events ?? null;
  const emails: OpsEmailLog[] = (ev ?? []).filter((e) => e.kind in MAIL_EVENTS).map((e) => ({ at: e.at, kind: e.kind === "reminder" ? "reminder" : "open", status: MAIL_EVENTS[e.kind], error: e.kind === "email_failed" ? e.detail ?? null : null }));
  const st = mailStatus(r.emailed, r.email_reason);
  // no mail event yet: show the opening e-mail's state (pending in a batch, SMTP not configured, failed)
  if (!emails.length) emails.push({ at: r.last_emailed_at ?? r.opened_at, kind: "open", status: st, error: r.emailed ? null : r.email_reason ?? null });
  return {
    id: r.id, check_id: r.check_id, fingerprint: r.fingerprint, title: r.title, severity: r.severity, status: r.status,
    opened_at: r.opened_at, last_seen_at: r.last_seen_at ?? null, count: r.occurrences ?? 1, summary: r.detail, impact: r.impact,
    acked_at: r.acknowledged_at, acked_by: r.acknowledged_by, resolved_at: r.resolved_at, resolved_by: r.resolved_by,
    runbook_id: r.runbook_id, runbook_url: r.runbook_url, runbook_steps: r.fix_steps, email_status: st, email_reason: r.email_reason,
    details: r.data, timeline: ev ? ev.map((e) => ({ at: e.at, kind: e.kind, by: e.actor === "monitor" ? null : e.actor ?? null, text: e.detail ?? null })) : null,
    emails: ev ? emails : null,
  };
}
function toReport(r: RawOpsReport): OpsReport {
  return {
    id: r.id, kind: r.kind, week_start: r.period_start, week_end: r.period_end ?? null, created_at: r.created_at, sent_at: r.sent_at ?? null,
    trigger: r.trigger ?? null, status: mailStatus(r.emailed, r.email_reason), to: r.to ?? null, subject: r.subject ?? null,
    error: r.emailed ? null : r.email_reason ?? null, html: r.html, text: r.text,
  };
}
function toTraffic(r: RawOpsTraffic): OpsTraffic {
  const pages = new Map<string, { host: string; path: string; views: number }>(), refs = new Map<string, number>(), ctry = new Map<string, number>();
  for (const d of r.daily) {
    for (const p of d.top_pages ?? []) { const k = d.host + p.path; const x = pages.get(k) ?? { host: d.host, path: p.path, views: 0 }; x.views += p.views; pages.set(k, x); }
    for (const x of d.top_referrers ?? []) refs.set(x.referrer, (refs.get(x.referrer) ?? 0) + x.count);
    for (const x of d.countries ?? []) ctry.set(x.country, (ctry.get(x.country) ?? 0) + x.count);
  }
  const hosts = r.hosts?.length ? r.hosts : [...new Set(r.daily.map((d) => d.host))].sort();
  return {
    days: r.days, available: r.source !== "unavailable", updated_at: r.last_parsed_at ?? null, bots_filtered: r.totals?.bot_requests ?? null,
    // hosts with no rows at all (e.g. scan.blockid.au before its log is mounted) are dropped from the charts
    hosts: hosts.filter((h) => r.daily.some((d) => d.host === h)),
    daily: r.daily.map((d) => ({ date: d.day, host: d.host, page_views: d.page_views, visitors: d.unique_visitors })),
    top_pages: [...pages.values()].sort((a, b) => b.views - a.views),
    referrers: [...refs].map(([referrer, views]) => ({ referrer, views })).sort((a, b) => b.views - a.views),
    countries: [...ctry].map(([country, views]) => ({ country, views })).sort((a, b) => b.views - a.views),
  };
}
function toError(r: RawOpsError): OpsError {
  const m = /^([A-Z]+)\s+(\S.*)$/.exec(r.route ?? "");
  return {
    fingerprint: r.fingerprint, count: r.count, first_seen: r.first_seen, last_seen: r.last_seen, method: m ? m[1] : null, route: m ? m[2] : r.route ?? null,
    service: r.source ?? null, logger: r.logger ?? null, level: r.level ?? null, message: r.message, stack: r.traceback ?? null, request_id: r.request_id ?? null,
  };
}
function toSummary(r: RawOpsSummary): OpsSummary {
  return {
    generated_at: r.generated_at, enabled: r.enabled !== false, leader: r.leader ?? null, last_check_at: r.last_run_at, checks: r.checks ?? [],
    open_incidents: { critical: r.open_incidents.critical ?? 0, warn: r.open_incidents.warn ?? 0, info: r.open_incidents.info ?? 0 },
    errors_24h: r.errors_24h ?? null, traffic_today: r.traffic_today ?? null, last_report: r.last_report ?? null,
    email: { configured: !!r.smtp_configured, to: r.alert_to ?? null, report_to: r.report_to ?? null, pending: r.unsent_emails ?? null },
  };
}

const opsP = (id: number | string) => `/v1/admin/ops/incidents/${enc(String(id))}`;
export const opsApi = {
  summary: () => request<RawOpsSummary>("GET", "/v1/admin/ops/summary").then(toSummary),
  /** "active" = open + acknowledged */
  incidents: (status: "active" | "resolved" | "all" = "all") => request<{ incidents: RawOpsIncident[] }>("GET", `/v1/admin/ops/incidents?status=${status}&limit=200`).then((x) => x.incidents.map(toIncident)),
  incident: (id: number | string) => request<RawOpsIncident>("GET", opsP(id)).then(toIncident),
  ack: (id: number | string, note = "") => request<{ ok: boolean; incident: RawOpsIncident }>("POST", opsP(id) + "/ack", { note }).then((x) => toIncident(x.incident)),
  resolve: (id: number | string, note = "") => request<{ ok: boolean; incident: RawOpsIncident }>("POST", opsP(id) + "/resolve", { note }).then((x) => toIncident(x.incident)),
  errors: (days = 7) => request<{ errors: RawOpsError[]; total: number }>("GET", `/v1/admin/ops/errors?days=${days}&limit=200`).then((x) => ({ total: x.total, rows: x.errors.map(toError) })),
  traffic: (days = 30) => request<RawOpsTraffic>("GET", `/v1/admin/ops/traffic?days=${days}`).then(toTraffic),
  stats: (days = 30) => request<OpsStats>("GET", `/v1/admin/ops/stats?days=${days}`),
  reports: () => request<{ reports: RawOpsReport[] }>("GET", "/v1/admin/ops/reports?limit=50").then((x) => x.reports.map(toReport)),
  report: (id: number | string) => request<RawOpsReport>("GET", `/v1/admin/ops/reports/${enc(String(id))}`).then(toReport),
  sendNow: () => request<{ ok: boolean; report: RawOpsReport; emailed: boolean; reason: string | null }>("POST", "/v1/admin/ops/reports/send-now", { kind: "weekly" })
    .then((x): OpsSendResult => ({ sent: x.emailed, status: mailStatus(x.emailed, x.reason), id: x.report?.id ?? null, to: x.report?.to ?? null, error: x.reason })),
  testEmail: (to?: string) => request<{ ok: boolean; to: string; reason: string | null }>("POST", "/v1/admin/ops/test-email", to ? { to } : {})
    .then((x): OpsSendResult => ({ sent: x.ok, status: mailStatus(x.ok, x.reason), id: null, to: x.to, error: x.reason })),
};
