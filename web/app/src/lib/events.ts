import { chainOf } from "../wallet";

/** Kinds that mean a chain sync finished successfully. */
const SYNC_OK = new Set(["anchored", "hoodi_mirrored", "hsk_mirrored"]);
const SYNC_BAD = new Set(["sync_failed", "sync_skipped"]);

interface EvLike { kind: string; at: string; chain?: string | number | null; ticker?: string | null }

/**
 * Failed / skipped chain syncs that a later successful sync of the same chain (and company) has superseded.
 * `isDone` (optional) says whether the chain ("blockid" | "hoodi" | "hsk") of an event is currently synced ("done"):
 * then every failure on it is resolved, even if the success event is outside the window we were given.
 */
export function resolvedFailures<T extends EvLike>(events: T[], isDone?: (e: T, chain: string) => boolean): Set<T> {
  const out = new Set<T>();
  const key = (e: EvLike) => `${e.ticker ?? ""}|${chainOf(e.chain).key}`;
  const lastOk = new Map<string, number>();
  for (const e of events) {
    if (!SYNC_OK.has(e.kind)) continue;
    const t = Date.parse(e.at), k = key(e);
    if (Number.isFinite(t) && t > (lastOk.get(k) ?? -Infinity)) lastOk.set(k, t);
  }
  for (const e of events) {
    if (!SYNC_BAD.has(e.kind)) continue;
    const ch = chainOf(e.chain).key;
    const syncKey = ch === "local" ? "blockid" : ch;
    const ok = lastOk.get(key(e));
    if (isDone?.(e, syncKey) || (ok != null && ok > Date.parse(e.at))) out.add(e);
  }
  return out;
}

export const isSyncFailure = (kind: string) => SYNC_BAD.has(kind);
