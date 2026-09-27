import { createSiweMessage } from "viem/siwe";
import { generatePrivateKey, privateKeyToAccount, type PrivateKeyAccount } from "viem/accounts";
import { api, request, type Role } from "./api";
import { SIWE_DOMAIN, SIWE_URI } from "./wallet";

/**
 * Keys created in this browser, for people without MetaMask ("Try it now" and Google sign-in).
 *
 * - The secp256k1 private key is generated here (viem, crypto.getRandomValues) and never sent to the server.
 * - At rest it is encrypted with AES-256-GCM under a non-extractable WebCrypto key; both live in IndexedDB, so page
 *   script can use the key but cannot read the wrapping key's bytes.
 * - One slot per identity: "guest", or "google:<sub>". The first Google sign-in in a browser that already has a guest
 *   key reuses it, so a guest keeps what they did; the guest slot is then emptied, so a second Google account on the
 *   same browser gets its own key (the server also refuses to link one address to two accounts).
 * - Restoring a backup signs in with it first and only then saves it, into the slot of the current sign-in method.
 * - Sign-in = a normal EIP-4361 (SIWE) message signed by this key, exactly like MetaMask.
 */

const DB = "blockid-wallet";
const STORE = "keys";

interface Stored {
  slot: string;
  address: string;
  iv: Uint8Array;
  ct: ArrayBuffer;
  wrap: CryptoKey;
  created: number;
}

function idb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const r = indexedDB.open(DB, 1);
    r.onupgradeneeded = () => r.result.createObjectStore(STORE, { keyPath: "slot" });
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error ?? new Error("IndexedDB unavailable"));
  });
}

async function tx<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await idb();
  try {
    return await new Promise<T>((resolve, reject) => {
      const req = fn(db.transaction(STORE, mode).objectStore(STORE));
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  } finally {
    db.close();
  }
}

const hexToBytes = (h: string) => Uint8Array.from((h.replace(/^0x/, "").match(/../g) ?? []).map((b) => parseInt(b, 16)));
const bytesToHex = (b: ArrayBuffer) => "0x" + [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("");

async function save(slot: string, pk: `0x${string}`): Promise<PrivateKeyAccount> {
  const account = privateKeyToAccount(pk);
  const wrap = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, wrap, hexToBytes(pk));
  const rec: Stored = { slot, address: account.address, iv, ct, wrap, created: Date.now() };
  await tx("readwrite", (s) => s.put(rec));
  return account;
}

async function load(slot: string): Promise<{ account: PrivateKeyAccount; pk: `0x${string}` } | null> {
  const rec = (await tx("readonly", (s) => s.get(slot))) as Stored | undefined;
  if (!rec) return null;
  const raw = await crypto.subtle.decrypt({ name: "AES-GCM", iv: rec.iv }, rec.wrap, rec.ct);
  const pk = bytesToHex(raw) as `0x${string}`;
  return { account: privateKeyToAccount(pk), pk };
}

async function remove(slot: string): Promise<void> {
  await tx("readwrite", (s) => s.delete(slot));
}

async function allSlots(): Promise<Stored[]> {
  return (await tx("readonly", (s) => s.getAll())) as Stored[];
}

/** The key for a slot, created on first use. */
async function ensure(slot: string): Promise<PrivateKeyAccount> {
  const have = await load(slot);
  if (have) return have.account;
  return save(slot, generatePrivateKey());
}

/** An error whose text is a dictionary key, so the page shows it in the reader's language (see errText). */
export class KeyError extends Error {
  key: string;
  vars?: Record<string, string>;
  constructor(key: string, vars?: Record<string, string>) {
    super(key);
    this.name = "KeyError";
    this.key = key;
    this.vars = vars;
  }
}

/** A pasted private key -> 0x + 64 hex, or a KeyError saying what is wrong with it. */
export function parseKey(input: string): `0x${string}` {
  const raw = input.trim();
  const words = raw.split(/\s+/).filter(Boolean);
  if (words.length >= 12 && words.every((w) => /^[a-z]+$/i.test(w))) throw new KeyError("fx.key.seed");
  const clean = raw.toLowerCase().replace(/^(0x)?/, "0x");
  if (!/^0x[0-9a-f]{64}$/.test(clean)) throw new KeyError("fx.key.format");
  try {
    privateKeyToAccount(clean as `0x${string}`); // 0 and values >= the curve order are not keys
  } catch {
    throw new KeyError("fx.key.range");
  }
  return clean as `0x${string}`;
}
/** `sub` claim of a Google ID token (only to pick the local slot; the server verifies the token). */
export function googleSub(credential: string): string {
  try {
    const p = credential.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return String(JSON.parse(atob(p + "===".slice((p.length + 3) % 4))).sub || "");
  } catch {
    return "";
  }
}

async function siweFor(account: PrivateKeyAccount): Promise<{ message: string; signature: string }> {
  const { nonce } = await api.nonce();
  const message = createSiweMessage({
    domain: SIWE_DOMAIN,
    address: account.address,
    statement: "Sign in to BlockID Business Passport.",
    uri: SIWE_URI,
    version: "1",
    chainId: 262626,
    nonce,
    issuedAt: new Date(),
    expirationTime: new Date(Date.now() + 10 * 60 * 1000),
  });
  return { message, signature: await account.signMessage({ message }) };
}

const LAST = "blockid-device-slot";

export async function signInWithDeviceKey(
  opts: { method: "guest" } | { method: "google"; credential: string },
): Promise<GoogleResult> {
  if (opts.method === "guest") {
    const account = await ensure("guest");
    const { message, signature } = await siweFor(account);
    const r = await request<{ address: string; role: Role }>("POST", "/v1/auth/siwe", { message, signature, method: "guest" });
    remember("guest");
    return r;
  }
  const sub = googleSub(opts.credential);
  if (!sub) throw new Error("Google sign-in failed. Please try again.");
  const slot = "google:" + sub;
  const have = await load(slot);
  const guest = have ? null : await load("guest");
  // a guest key that another Google account on this browser already took (older versions copied it) is not reused
  const taken = guest ? (await allSlots()).some((x) => x.slot !== "guest" && x.address.toLowerCase() === guest.account.address.toLowerCase()) : false;
  const pk = have?.pk ?? (guest && !taken ? guest.pk : generatePrivateKey());
  const account = privateKeyToAccount(pk);
  const { message, signature } = await siweFor(account);
  const lang = (() => { try { return localStorage.getItem("blockid-lang") === "vi" ? "vi" : "en"; } catch { return "en"; } })();
  // saved only once the server accepted it (409: this key is another account's wallet)
  const r = await request<GoogleResult>("POST", "/v1/auth/google", { credential: opts.credential, message, signature, lang });
  if (!have) await save(slot, pk);
  if (guest && (taken || pk === guest.pk)) await remove("guest"); // the key now lives in a Google slot
  remember(slot);
  return r;
}

export interface GoogleResult {
  address: string;
  role: Role;
  /** a new key was made on this browser while the account already has these wallets */
  new_wallet?: boolean;
  wallets?: string[];
}

function remember(slot: string) {
  try { localStorage.setItem(LAST, slot); } catch { /* private mode */ }
}

/** Slot that holds the key for this address, if any (for backup/export). */
export async function slotFor(address: string): Promise<string | null> {
  const all = await allSlots();
  return all.find((r) => r.address.toLowerCase() === address.toLowerCase())?.slot ?? null;
}

/** Private key for backup. Only called from an explicit "Show my key" action. */
export async function exportKey(address: string): Promise<string | null> {
  const slot = await slotFor(address);
  if (!slot) return null;
  return (await load(slot))?.pk ?? null;
}

/** Slot a restore goes to: the Google slot when signed in with Google on this browser, else the guest slot. */
function restoreSlot(method?: string | null): string {
  if (method === "google") {
    try {
      const last = localStorage.getItem(LAST);
      if (last?.startsWith("google:")) return last;
    } catch { /* private mode */ }
  }
  return "guest";
}

/** What a restore would do: the key's address, and the different key it would replace in this browser (if any). */
export async function restorePlan(pk: string, method?: string | null): Promise<{ address: string; replaces: string | null }> {
  const address = privateKeyToAccount(parseKey(pk)).address;
  const have = await load(restoreSlot(method)).catch(() => null);
  return { address, replaces: have && have.account.address !== address ? have.account.address : null };
}

/** Restore a backed-up key: sign in with it first, then save it into the current method's slot. Replacing a
 *  different key needs `replace` (the page asks, naming both addresses). */
export async function importKey(pk: string, method?: string | null, replace = false): Promise<{ address: string; role: Role }> {
  const clean = parseKey(pk);
  const account = privateKeyToAccount(clean);
  const slot = restoreSlot(method);
  const have = await load(slot).catch(() => null);
  if (have && have.account.address !== account.address && !replace) throw new KeyError("fx.key.confirm", { a: have.account.address, b: account.address });
  const { message, signature } = await siweFor(account);
  const r = await request<{ address: string; role: Role }>("POST", "/v1/auth/siwe", { message, signature, method: "guest" });
  await save(slot, clean);
  remember(slot);
  return r;
}

export async function hasDeviceKey(address: string): Promise<boolean> {
  try { return (await slotFor(address)) !== null; } catch { return false; }
}
