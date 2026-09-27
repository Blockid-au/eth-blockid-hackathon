import type { Approvals, CompanyDetail, CoStatus, Valuation } from "../api";

/**
 * Single source of truth for the founder flow: 8 steps in 3 phases, 2 human gates, then the company workspace.
 * Rail, pager, gate cards and "next for you" all read from here.
 */
export type Phase = "a" | "b" | "c";
export const PHASES: { key: Phase; steps: number[] }[] = [
  { key: "a", steps: [1, 2, 3] },
  { key: "b", steps: [4, 5] },
  { key: "c", steps: [6, 7, 8] },
];
export const phaseOf = (n: number): Phase => (n <= 3 ? "a" : n <= 5 ? "b" : "c");

/** Gate shown after step 3 (valuation approval) and after step 5 (issuance approval). */
export type GateState = "none" | "wait" | "ok" | "bad";
export const GATE_AFTER: Record<number, 1 | 2> = { 3: 1, 5: 2 };

/* ---------- valuation steps (2–5) live under /v/:id/:seg ---------- */
export const VAL_SEG: Record<number, string> = { 2: "research", 3: "report", 4: "ticker", 5: "holders" };
export const VAL_STEP: Record<string, number> = { research: 2, report: 3, ticker: 4, holders: 5 };
export const valPath = (id: string, n: number) => `/v/${encodeURIComponent(id)}/${VAL_SEG[n] ?? "report"}`;

export function valAuto(v?: Valuation | null): number {
  return !v ? 2 : v.svi ? 3 : 2;
}
export function valReach(v: Valuation | null | undefined, sample: boolean): number {
  if (!v) return 2;
  if (sample) return 3;
  return v.status === "approved" ? 5 : v.svi ? 3 : 2;
}
export function valGate(v?: Valuation | null): GateState {
  if (!v) return "none";
  return v.status === "approved" ? "ok" : v.status === "waiting_approval" ? "wait" : v.status === "rejected" ? "bad" : "none";
}

/* ---------- company steps (6–8) and workspace live under /c/:ticker/:seg ---------- */
export const CO_SEG: Record<number, string> = { 6: "issue", 7: "sync", 8: "wallet" };
export const CO_STEP: Record<string, number> = { issue: 6, sync: 7, wallet: 8 };
export const LIVE: CoStatus[] = ["issued", "pending_anchor", "anchoring", "anchored", "partially_anchored"];

export function coGate(c?: Pick<CompanyDetail, "status"> | null): GateState {
  if (!c) return "none";
  if (c.status === "draft") return "none";
  if (c.status === "pending_issue") return "wait";
  if (c.status === "rejected") return "bad";
  return "ok";
}
function blockidDone(c: CompanyDetail) {
  return (c.sync?.blockid ?? (c.local?.token ? "done" : "pending")) === "done";
}
function chainsDone(c: CompanyDetail) {
  if (c.status === "anchored" && !c.sync) return true;
  return c.sync?.hoodi === "done" && c.sync?.hsk === "done";
}
/** The flow step a company is on right now. */
export function coStep(c: CompanyDetail): number {
  if (!blockidDone(c)) return 6;
  return chainsDone(c) ? 8 : 7;
}
export function coReach(c: CompanyDetail): number {
  return coStep(c);
}

/** Workspace sections in pager order (after the flow steps). */
export const WS = ["overview", "updates", "offering", "cap-table", "transfers", "mint", "dividends", "activity", "team"] as const;
export type WsSection = (typeof WS)[number];
export const coPath = (tk: string, seg: string) => `/c/${tk}/${seg}`;

/* ---------- admin queues, in the order a company moves through the flow ---------- */
export type QueueKey = "valuations" | "issuance" | "sync" | "mints" | "dividends" | "policies" | "updates" | "offerings";
export const QUEUES: { key: QueueKey; gate: boolean }[] = [
  { key: "valuations", gate: true },
  { key: "issuance", gate: true },
  { key: "sync", gate: false },
  { key: "mints", gate: true },
  { key: "dividends", gate: true },
  { key: "policies", gate: true },
  { key: "updates", gate: true },
  { key: "offerings", gate: true },
];
export function queueItems(a: Approvals | undefined) {
  const cos = a?.companies ?? [];
  return {
    valuations: a?.valuations ?? [],
    issuance: cos.filter((c) => c.status === "pending_issue"),
    sync: cos.filter((c) => c.status === "issued" || c.status === "pending_anchor" || c.status === "partially_anchored"),
    mints: a?.mints ?? [],
    dividends: a?.dividends ?? [],
    policies: a?.policies ?? [],
    updates: a?.updates ?? [],
    offerings: a?.offerings ?? [],
  };
}
export function queueCounts(a: Approvals | undefined): Record<QueueKey, number> & { total: number } {
  const q = queueItems(a);
  const r = { valuations: q.valuations.length, issuance: q.issuance.length, sync: q.sync.length, mints: q.mints.length, dividends: q.dividends.length, policies: q.policies.length, updates: q.updates.length, offerings: q.offerings.length };
  return { ...r, total: r.valuations + r.issuance + r.sync + r.mints + r.dividends + r.policies + r.updates + r.offerings };
}

/** Admin deep link for a gate, with the founder page to return to after the decision. */
export const adminLink = (path: string, back: string) => `${path}?return=${encodeURIComponent(back)}`;
