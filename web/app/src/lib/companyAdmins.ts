/* Company admins API (agents/src/blockid_agents/studio/company_admins.py). */
import { useEffect, useState } from "react";
import { request, type MintReq, type DividendReq } from "../api";
import { useAuth } from "../auth";

export type CoAdminRole = "owner" | "manager";
export type CoAdminStatus = "active" | "pending_grant" | "revoked";
/** audit role of the viewer on one company */
export type CoViewerRole = "platform_admin" | "company_owner" | "company_manager";

export interface CompanyAdmin {
  id: number;
  company_id: number;
  address: string;
  label: string;
  role: CoAdminRole;
  status: CoAdminStatus;
  onchain: boolean;
  grant_tx?: string | null;
  revoke_tx?: string | null;
  error?: string | null;
  added_by?: string | null;
  added_at?: string | null;
  revoked_at?: string | null;
}
export interface CompanyAdminList {
  ticker: string;
  company_id: number;
  you: CoViewerRole;
  issued: boolean;
  admins: CompanyAdmin[];
}
export interface MyCompany {
  id: number;
  ticker: string;
  name: string;
  status: string;
  local_token?: string | null;
  role: CoAdminRole;
  onchain: boolean;
  label?: string;
}
export interface TransferReq {
  id: number;
  company_id: number;
  ticker?: string;
  from_wallet: string;
  to_wallet: string;
  to_name?: string;
  shares: number;
  mode: string;
  status: string;
  created_at?: string;
}
export interface ScopedApprovals {
  scope?: "platform" | "company";
  company_ids?: number[] | null;
  mints: MintReq[];
  dividends: DividendReq[];
}

const enc = encodeURIComponent;

export const coAdminApi = {
  list: (ticker: string) => request<CompanyAdminList>("GET", `/v1/companies/${enc(ticker)}/admins`),
  add: (ticker: string, body: { address: string; label: string; role: CoAdminRole; onchain: boolean }) =>
    request<CompanyAdmin & { issuer?: string }>("POST", `/v1/companies/${enc(ticker)}/admins`, body),
  revoke: (ticker: string, address: string) =>
    request<CompanyAdmin & { issuer?: string }>("POST", `/v1/companies/${enc(ticker)}/admins/${enc(address)}/revoke`),
  mine: () => request<MyCompany[]>("GET", "/v1/me/companies"),
  approvals: () => request<ScopedApprovals>("GET", "/v1/admin/approvals"),
  transfers: () => request<TransferReq[]>("GET", "/v1/admin/transfers"),
  approveTransfer: (id: number) => request<unknown>("POST", `/v1/admin/transfers/${id}/approve`),
  rejectTransfer: (id: number, reason: string) => request<unknown>("POST", `/v1/admin/transfers/${id}/reject`, { reason }),
};

/** Companies the signed-in wallet administers (empty for password / signed-out sessions). */
export function useMyCompanies(): { list: MyCompany[]; reload: () => void } {
  const { me } = useAuth();
  const [list, setList] = useState<MyCompany[]>([]);
  const [n, setN] = useState(0);
  const addr = me?.address ?? null;
  useEffect(() => {
    let alive = true;
    if (!addr) { setList([]); return; }
    coAdminApi.mine().then((x) => { if (alive) setList(Array.isArray(x) ? x : []); }).catch(() => { if (alive) setList([]); });
    return () => { alive = false; };
  }, [addr, n]);
  return { list, reload: () => setN((x) => x + 1) };
}
