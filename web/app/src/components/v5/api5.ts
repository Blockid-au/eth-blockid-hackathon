/**
 * v5 endpoints — docs/EVALUATION-V5-API.md §3 and docs/VALUATION-V5-API.md §2–§3.
 * With VALUATION_V5 off the server answers 404 on all of them; `features()` then reports off and no v5 UI shows.
 */
import { API_BASE, ApiError, isMock, request, type SelfReported } from "../../api";
import { readPriceRequest, readTok, type Check, type PriceRequest, type TokView } from "./types";

const enc = encodeURIComponent;

export interface FieldCfg { key: string; group: string; unit: string; min_stage: string }
export interface EvalConfig { enabled: boolean; stages?: string[]; fields?: FieldCfg[]; share_price_by_stage?: Record<string, number>; table_version?: string; level_labels?: Record<string, string> }
export type DocKind = "deck" | "metrics_csv" | "financials";
export interface DocIn { kind: DocKind; filename: string; sha256: string; text?: string; rows?: string }
export interface DocParsed { rows?: number; months?: string[]; series?: Record<string, (number | null)[]>; metrics?: Record<string, number | null>; flags?: { code: string; severity: string; message: string }[]; errors?: string[]; chars?: number }
export interface DocOut { doc_id: string; kind: DocKind; filename: string; sha256: string; parsed?: DocParsed | null; created_at?: string }
export interface ProjectionYearIn { year: number; actual: boolean; revenue: number; cogs: number; opex: number; ebitda?: number | null; d_and_a: number; tax?: number | null; capex: number; nwc?: number | null; change_nwc?: number | null; headcount?: number | null; customers?: number | null }
export interface ProjectionIn { currency: string; fiscal_year_end: string; audited: boolean; prepared_by?: string; basis_notes?: string; cash: number; debt: number; shares_fd: number | null; planned_raise: number; years: ProjectionYearIn[] }
export interface ProjectionView { id: number; status: "draft" | "confirmed" | "superseded"; filename?: string | null; sha256: string; parsed?: ProjectionIn | null; checks: Check[]; can_confirm?: boolean; errors?: number; warnings?: number; attested_at?: string | null }
export interface ConfirmOut { projection: ProjectionView; valuation_status?: string; value_before_aud?: number; value_after_aud?: number; moved_pct?: number; back_to_review?: boolean }
export interface FinaliseIn { price_per_share_aud?: number; note?: string; reason?: string; allow_low_confidence?: boolean; override_reason?: string }

let cfg: Promise<EvalConfig> | null = null;
/** GET /v1/studio/evaluation/config (public). Any failure → disabled. Cached for the page. */
export function evalConfig(): Promise<EvalConfig> {
  cfg ??= request<EvalConfig>("GET", "/v1/studio/evaluation/config").then((c) => ({ ...c, enabled: c?.enabled === true })).catch(() => ({ enabled: false }));
  return cfg;
}

export const api5 = {
  stagePreview: (metrics: Record<string, unknown>) => request<{ stage: string; basis: string; reasons: string[] }>("POST", "/v1/studio/evaluation/stage-preview", { metrics }),
  createValuation: (url: string, metrics: Record<string, unknown>, team?: { people: unknown[]; consent: true }) =>
    request<{ id: string; team_id?: string | null }>("POST", "/v1/studio/valuations", { url, ...(Object.keys(metrics).length ? { metrics: metrics as SelfReported } : {}), ...(team && team.people.length ? { team } : {}) }),
  addDocument: (vid: string, d: DocIn) => request<DocOut>("POST", `/v1/studio/valuations/${enc(vid)}/documents`, d),
  documents: (vid: string) => request<DocOut[]>("GET", `/v1/studio/valuations/${enc(vid)}/documents`),
  deleteDocument: (vid: string, docId: string) => request<{ deleted: boolean }>("DELETE", `/v1/studio/valuations/${enc(vid)}/documents/${enc(docId)}`),
  rescore: (vid: string) => request<unknown>("POST", `/v1/studio/valuations/${enc(vid)}/rescore`, {}),
  /** JSON ProjectionInput (parsed CSV / in-page grid) or multipart for an .xlsx the browser cannot read. */
  uploadProjections: async (vid: string, body: ProjectionIn | null, file?: File | null): Promise<ProjectionView> => {
    const path = `/v1/studio/valuations/${enc(vid)}/projections`;
    if (body && (!file || !/\.xlsx$/i.test(file.name))) return request<ProjectionView>("POST", path, body);
    if (isMock) return request<ProjectionView>("POST", path, { xlsx: file?.name ?? "forecast.xlsx" });
    const fd = new FormData();
    fd.append("file", file!);
    let res: Response;
    try { res = await fetch(API_BASE + path, { method: "POST", credentials: "same-origin", body: fd }); } catch { throw new ApiError(0, "network"); }
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new ApiError(res.status, typeof data?.detail === "string" ? data.detail : res.statusText);
    return data as ProjectionView;
  },
  projections: (vid: string) => request<{ latest: ProjectionView | null; history: ProjectionView[]; label?: string }>("GET", `/v1/studio/valuations/${enc(vid)}/projections`),
  confirmProjections: (vid: string, pid: number) => request<ConfirmOut>("POST", `/v1/studio/valuations/${enc(vid)}/projections/${pid}/confirm`, { attest: true }),
  deleteProjections: (vid: string, pid: number) => request<{ ok: boolean }>("DELETE", `/v1/studio/valuations/${enc(vid)}/projections/${pid}`),
  templateUrl: (format: "xlsx" | "csv", lang: string) => `${API_BASE}/v1/studio/projection-template?format=${format}&lang=${lang}`,
  tokenisation: async (vid: string): Promise<TokView | null> => readTok(await request<unknown>("GET", `/v1/studio/valuations/${enc(vid)}/tokenisation`)),
  finalise: async (vid: string, b: FinaliseIn): Promise<TokView | null> => readTok(await request<unknown>("POST", `/v1/studio/valuations/${enc(vid)}/finalise`, b)),
  cancelPriceRequest: async (vid: string, rid: number) => readTok(await request<unknown>("POST", `/v1/studio/valuations/${enc(vid)}/price-requests/${rid}/cancel`, {})),
  priceRequests: async (): Promise<PriceRequest[]> => (await request<unknown[]>("GET", "/v1/admin/price-requests?status=pending")).map(readPriceRequest).filter((x): x is PriceRequest => !!x),
  approvePrice: (rid: number, note: string) => request<unknown>("POST", `/v1/admin/price-requests/${rid}/approve`, note ? { note } : {}),
  rejectPrice: (rid: number, reason: string) => request<unknown>("POST", `/v1/admin/price-requests/${rid}/reject`, { reason }),
};

export async function sha256Hex(buf: ArrayBuffer): Promise<string> {
  const h = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(h)).map((b) => b.toString(16).padStart(2, "0")).join("");
}
