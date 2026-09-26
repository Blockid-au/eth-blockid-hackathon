/* Kept free of viem/wallet imports: the Home card uses it from the main chunk. */

/** Shape of /hsk-demo.json (HashKey Chain testnet deployment). Every key is optional: render defensively. */
export interface HskHolder { account?: string; amount?: number | string }
export interface HskProposal {
  id?: number; agent?: string; kind?: string; contentHash?: string; modelId?: string; status?: string;
  proposeTx?: string; approveTx?: string; executeTx?: string;
}
export interface HskDemo {
  chainId?: number;
  operator?: string; relayer?: string; approver?: string;
  identityRegistry?: string; shareToken?: string; dividendDistributor?: string; payToken?: string;
  capTableAnchor?: string; agentProvenance?: string;
  roundId?: number; claimDeadline?: number; dividendTotal?: number | string; merkleRoot?: string;
  holders?: HskHolder[];
  provenance?: HskProposal[];
  txs?: Record<string, string>;
}

/** Fetch /hsk-demo.json. Returns null when the file is missing (404, or nginx SPA fallback serving index.html). */
export async function loadHskDemo(): Promise<HskDemo | null> {
  try {
    const r = await fetch("/hsk-demo.json", { cache: "no-cache", headers: { Accept: "application/json" } });
    if (!r.ok) return null;
    const txt = await r.text();
    if (!txt.trim().startsWith("{")) return null;
    const j = JSON.parse(txt);
    return j && typeof j === "object" ? (j as HskDemo) : null;
  } catch {
    return null;
  }
}

export const okAddr = (a: unknown): a is string => typeof a === "string" && /^0x[0-9a-fA-F]{40}$/.test(a);
export const okHash = (h: unknown): h is `0x${string}` => typeof h === "string" && /^0x[0-9a-fA-F]{64}$/.test(h);
